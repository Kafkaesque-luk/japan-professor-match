#!/usr/bin/env python3
"""
Sanity-check the exported sample (no server / no API key needed).

Validates that data/professors_5000.jsonl and data/qdrant_snapshot/points.jsonl are consistent,
that vectors are the right dimension, and — using the real age estimator — reports how many
professors are confidently age-estimable in the prime-age window, i.e. proves the 年富力强 tier
will actually fill. Run:  python scripts/verify_sample.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "api"))

from app.age_estimation import estimate_from_extend  # noqa: E402
from app.discipline import DisciplineCategoryService  # noqa: E402
from app.io_utils import open_text  # noqa: E402

ROWS = os.path.join(HERE, "data", "professors_5000.jsonl")
POINTS = os.path.join(HERE, "data", "qdrant_snapshot", "points.jsonl")


def load_jsonl(path):
    out = []
    with open_text(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main():
    rows = load_jsonl(ROWS)
    points = load_jsonl(POINTS)
    print(f"rows:   {len(rows)}   from {ROWS}")
    print(f"points: {len(points)} from {POINTS}")

    row_ids = {int(r["product_id"]) for r in rows}
    pt_ids = {int(p["id"]) for p in points}
    print(f"id intersection: {len(row_ids & pt_ids)}  (rows-only {len(row_ids - pt_ids)}, points-only {len(pt_ids - row_ids)})")

    dims = Counter(len(p["vector"]) for p in points)
    print(f"vector dims: {dict(dims)}")
    payload_keys = Counter()
    for p in points:
        payload_keys.update((p.get("payload") or {}).keys())
    print(f"payload keys present: {dict(payload_keys)}")

    # Age estimation over the real CVs.
    conf = Counter()
    prime = 0
    for r in rows:
        ext = r.get("extend")
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except ValueError:
                ext = None
        est = estimate_from_extend(ext) if isinstance(ext, dict) else None
        if not est:
            conf["none"] += 1
            continue
        conf[est["confidence"]] += 1
        if est["confidence"] in ("high", "medium") and 33 <= est["age"] <= 55:
            prime += 1
    print(f"\nage confidence: {dict(conf)}")
    print(f"prime-age (high|medium, 33-55): {prime}  -> 年富力强 tier source pool")

    # Discipline coverage + a couple of detection spot-checks.
    disc = DisciplineCategoryService()
    print(f"\ndistinct cate_id in sample: {len({r.get('cate_id') for r in rows})}")
    for q in ["经济学", "机械工程的振动控制", "随便看看"]:
        print(f"  detect_middle_from_text({q!r}) -> {disc.detect_middle_from_text(q)}")

    # Rank bands (the 潜力洼地 tier needs non-top-30).
    bands = Counter()
    for r in rows:
        rk = int(r.get("school_rank") or 0)
        bands["top30(1-30)" if 1 <= rk <= 30 else "value(31+/unranked)"] += 1
    print(f"\nrank split: {dict(bands)}  -> 潜力洼地 draws from value pool")


if __name__ == "__main__":
    main()
