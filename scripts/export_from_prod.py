#!/usr/bin/env python3
"""
Reference exporter: build a curated professor sample (rows + vectors) from an EXISTING
CRMEB-style source (MySQL + a Qdrant `professors` collection) over SSH, for bundling into this
repo. READ-ONLY: only runs SELECTs and Qdrant point reads. Configure the source via the PM_*
environment variables at the top (never commit real host/credentials).

It:
  1. dumps lightweight candidate metadata (id, cate_id, school_rank, extend length) from MySQL,
  2. stratifies locally by discipline (sqrt-proportional) so the sample is broad and all three
     tiers fill (diverse disciplines, mix of ranks, age-estimable CVs),
  3. pulls the full rows for the chosen ids from MySQL,
  4. pulls the matching vectors + payloads from the source Qdrant `professors` collection,
  5. keeps only ids present in BOTH and writes:
        data/professors_5000.jsonl.gz        (display rows for the ProfessorStore)
        data/qdrant_snapshot/points.jsonl.gz (id + vector + payload for the local Qdrant)

The DB password is read from the source .env *on the server* and never leaves it or touches disk
here. Requires: pip install paramiko

Usage:
    PM_SSH_HOST=10.0.0.5 PM_DB_NAME=mydb PM_DB_USER=mydb PM_SRC_ENV=/www/site/.env \\
        python scripts/export_from_prod.py --target 5000
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import random
import shlex
import sys
from collections import defaultdict

try:
    import paramiko
except ImportError:
    sys.exit("paramiko is required: pip install paramiko")

# ---- SOURCE server config — set via environment variables; do NOT commit real values. ----
# Reads MySQL rows + Qdrant vectors from an existing CRMEB-style deployment over SSH.
SSH_HOST = os.environ.get("PM_SSH_HOST", "")                      # e.g. 10.0.0.5  (required)
SSH_PORT = int(os.environ.get("PM_SSH_PORT", "22"))
SSH_USER = os.environ.get("PM_SSH_USER", "ubuntu")
SSH_KEY = os.environ.get("PM_SSH_KEY", os.path.expanduser("~/.ssh/id_ed25519"))

SRC_ENV = os.environ.get("PM_SRC_ENV", "/path/to/site/.env")     # .env holding [DATABASE] PASSWORD
MYSQL_BIN = os.environ.get("PM_MYSQL_BIN", "mysql")
DB_NAME = os.environ.get("PM_DB_NAME", "")                        # (required)
DB_USER = os.environ.get("PM_DB_USER", "")                        # (required)
QDRANT = os.environ.get("PM_QDRANT", "http://127.0.0.1:21121")
COLLECTION = os.environ.get("PM_COLLECTION", "professors")

SEED = 20260629
OVER_SELECT = 1.08          # over-pull, then trim to target after vector intersection
MYSQL_BATCH = 1000
QDRANT_BATCH = 256

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROWS = os.path.join(HERE, "data", "professors_5000.jsonl.gz")
OUT_POINTS = os.path.join(HERE, "data", "qdrant_snapshot", "points.jsonl.gz")


def connect() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if os.path.exists(SSH_KEY):
        key = paramiko.Ed25519Key.from_private_key_file(SSH_KEY)
        c.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, pkey=key,
                  allow_agent=False, look_for_keys=False, timeout=20)
    else:
        import getpass
        pw = getpass.getpass(f"password for {SSH_USER}@{SSH_HOST}: ")
        c.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=pw, timeout=20)
    return c


def run(ssh: paramiko.SSHClient, cmd: str) -> str:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=300)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f"remote command failed ({code}): {err.strip()[:400]}")
    return out


def mysql(ssh: paramiko.SSHClient, sql: str) -> str:
    """Run a SELECT on prod; DB password is resolved from the prod .env on the server."""
    inner = (
        f"DBPW=$(sudo grep -A8 '^\\[DATABASE\\]' {SRC_ENV} "
        f"| grep -iE '^[[:space:]]*PASSWORD' | head -1 "
        f"| sed -E \"s/^[^=]*=[[:space:]]*'?([^']*)'?[[:space:]]*$/\\1/\"); "
        f"{MYSQL_BIN} -u{DB_USER} -p\"$DBPW\" {DB_NAME} -N --raw -e {shlex.quote(sql)}"
    )
    return run(ssh, inner)


def qdrant_points(ssh: paramiko.SSHClient, ids: list) -> list:
    body = json.dumps({"ids": ids, "with_vector": True, "with_payload": True})
    cmd = (f"curl -s {QDRANT}/collections/{COLLECTION}/points -X POST "
           f"-H 'Content-Type: application/json' -d {shlex.quote(body)}")
    out = run(ssh, cmd)
    data = json.loads(out)
    return data.get("result", []) or []


def stratify(cands: list, target: int) -> list:
    """sqrt-proportional allocation across cate_id; random pick within each (seeded)."""
    groups = defaultdict(list)
    for c in cands:
        groups[c[1]].append(c)  # c = (pid, cate, rank, elen)
    weights = {k: math.sqrt(len(v)) for k, v in groups.items()}
    total_w = sum(weights.values()) or 1.0
    rnd = random.Random(SEED)
    chosen = []
    for k, v in groups.items():
        alloc = max(1, round(target * weights[k] / total_w))
        rnd.shuffle(v)
        chosen.extend(v[:alloc])
    rnd.shuffle(chosen)
    return chosen[:target]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=5000)
    args = ap.parse_args()
    target = args.target
    over = int(target * OVER_SELECT)

    missing = [n for n, v in (("PM_SSH_HOST", SSH_HOST), ("PM_DB_NAME", DB_NAME), ("PM_DB_USER", DB_USER)) if not v]
    if missing:
        sys.exit("missing required env: " + ", ".join(missing) + " (see the header of this file)")

    os.makedirs(os.path.dirname(OUT_ROWS), exist_ok=True)
    os.makedirs(os.path.dirname(OUT_POINTS), exist_ok=True)

    print(f"connecting to {SSH_USER}@{SSH_HOST}:{SSH_PORT} ...")
    ssh = connect()
    try:
        # Stage 0: capture the collection's vector config (size + distance) for a faithful reseed.
        try:
            info = json.loads(run(ssh, f"curl -s {QDRANT}/collections/{COLLECTION}"))
            vc = info["result"]["config"]["params"]["vectors"]
            if "size" not in vc:           # named-vector schema -> take the first
                vc = next(iter(vc.values()))
            coll = {"size": int(vc["size"]), "distance": str(vc["distance"])}
            with open(os.path.join(os.path.dirname(OUT_POINTS), "collection.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(coll, fh)
            print(f"  collection config: size={coll['size']} distance={coll['distance']}")
        except Exception as e:  # noqa: BLE001 - non-fatal; seed.py falls back to cosine/dim
            print(f"  warn: could not read collection config ({e}); seed will use defaults")

        # Stage A: candidate metadata for stratification.
        print("stage A: dumping candidate metadata (this scans ~150k professors) ...")
        sql_a = (
            "SELECT product_id, IFNULL(cate_id,0), IFNULL(school_rank,0), CHAR_LENGTH(extend) "
            "FROM eb_store_product "
            "WHERE mer_id=7 AND brand_id=0 AND is_show=1 AND is_del=0 "
            "AND extend IS NOT NULL AND CHAR_LENGTH(extend) > 200;"
        )
        cands = []
        for line in mysql(ssh, sql_a).splitlines():
            parts = line.split("\t")
            if len(parts) != 4:
                continue
            try:
                cands.append((int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])))
            except ValueError:
                continue
        print(f"  candidates: {len(cands)}  distinct disciplines: {len({c[1] for c in cands})}")
        if not cands:
            sys.exit("no candidates found — check filters/table name")

        chosen = stratify(cands, over)
        chosen_ids = [c[0] for c in chosen]
        print(f"stage B/C: pulling rows + vectors for {len(chosen_ids)} ids ...")

        # Stage B: full rows.
        rows = {}
        for i in range(0, len(chosen_ids), MYSQL_BATCH):
            batch = chosen_ids[i:i + MYSQL_BATCH]
            in_list = ",".join(str(x) for x in batch)
            sql_b = (
                "SELECT JSON_OBJECT("
                "'product_id', product_id, 'store_name', store_name, 'extend', extend, "
                "'school_rank', school_rank, 'school_name', school_name, "
                "'school_type', school_type, 'school_region_id', school_region_id, "
                "'cate_id', cate_id, 'image', image) "
                f"FROM eb_store_product WHERE product_id IN ({in_list});"
            )
            for line in mysql(ssh, sql_b).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                rows[int(obj["product_id"])] = obj
            print(f"  rows {len(rows)}/{len(chosen_ids)}", end="\r")
        print()

        # Stage C: vectors + payloads.
        points = {}
        for i in range(0, len(chosen_ids), QDRANT_BATCH):
            batch = chosen_ids[i:i + QDRANT_BATCH]
            for p in qdrant_points(ssh, batch):
                pid = int(p["id"])
                points[pid] = {"id": pid, "vector": p["vector"], "payload": p.get("payload") or {}}
            print(f"  vectors {len(points)}/{len(chosen_ids)}", end="\r")
        print()
    finally:
        ssh.close()

    # Intersect (need both row and vector), keep stratified order, trim to target.
    final_ids = [pid for pid in chosen_ids if pid in rows and pid in points][:target]
    print(f"intersection with both row+vector: {len(final_ids)} (target {target})")

    with gzip.open(OUT_ROWS, "wt", encoding="utf-8") as fh:
        for pid in final_ids:
            fh.write(json.dumps(rows[pid], ensure_ascii=False) + "\n")
    with gzip.open(OUT_POINTS, "wt", encoding="utf-8") as fh:
        for pid in final_ids:
            fh.write(json.dumps(points[pid], ensure_ascii=False) + "\n")

    # Summary.
    rank_band = defaultdict(int)
    for pid in final_ids:
        r = int(rows[pid].get("school_rank") or 0)
        band = ("top30" if 1 <= r <= 30 else "31-150" if 31 <= r <= 150
                else "151+" if r > 150 else "unranked")
        rank_band[band] += 1
    disc = len({rows[pid].get("cate_id") for pid in final_ids})
    print(f"\nwrote {len(final_ids)} professors")
    print(f"  -> {OUT_ROWS}")
    print(f"  -> {OUT_POINTS}")
    print(f"  disciplines: {disc}   rank bands: {dict(rank_band)}")


if __name__ == "__main__":
    main()
