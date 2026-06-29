"""
Restore the bundled Qdrant snapshot into Qdrant — the zero-cost, zero-key path that makes
`docker compose run --rm seed` produce a searchable index instantly.

Reads ``data/qdrant_snapshot/points.jsonl`` (id + vector + payload, pulled from production with
exact parity) and ``collection.json`` (size + distance), recreates the collection, and upserts.
"""

from __future__ import annotations

import json
import os
import sys

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import get_settings
from app.io_utils import open_text

_CANDIDATES = [
    "/data/qdrant_snapshot",
    os.path.join(os.path.dirname(__file__), "..", "data", "qdrant_snapshot"),
    "data/qdrant_snapshot",
]


def _snapshot_dir() -> str:
    for d in _CANDIDATES:
        if (os.path.exists(os.path.join(d, "points.jsonl"))
                or os.path.exists(os.path.join(d, "points.jsonl.gz"))):
            return d
    sys.exit("snapshot not found — run scripts/export_from_prod.py first (or load_snapshot docs)")


def _distance(name: str) -> qm.Distance:
    return {
        "cosine": qm.Distance.COSINE,
        "dot": qm.Distance.DOT,
        "euclid": qm.Distance.EUCLID,
        "manhattan": qm.Distance.MANHATTAN,
    }.get((name or "cosine").lower(), qm.Distance.COSINE)


def main() -> None:
    s = get_settings()
    snap = _snapshot_dir()
    points_path = os.path.join(snap, "points.jsonl")

    size = s.embedding_dim
    distance = qm.Distance.COSINE
    coll_meta = os.path.join(snap, "collection.json")
    if os.path.exists(coll_meta):
        with open(coll_meta, encoding="utf-8") as fh:
            meta = json.load(fh)
        size = int(meta.get("size") or size)
        distance = _distance(meta.get("distance"))

    client = QdrantClient(url=s.qdrant_url, timeout=120)
    client.recreate_collection(
        collection_name=s.qdrant_collection,
        vectors_config=qm.VectorParams(size=size, distance=distance),
    )

    batch, total = [], 0
    with open_text(points_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            batch.append(qm.PointStruct(id=int(p["id"]), vector=p["vector"],
                                        payload=p.get("payload") or {}))
            if len(batch) >= 256:
                client.upsert(collection_name=s.qdrant_collection, points=batch)
                total += len(batch)
                batch = []
                print(f"  upserted {total}", end="\r")
    if batch:
        client.upsert(collection_name=s.qdrant_collection, points=batch)
        total += len(batch)
    print(f"\nseeded {total} points into '{s.qdrant_collection}' (size={size}, distance={distance})")


if __name__ == "__main__":
    main()
