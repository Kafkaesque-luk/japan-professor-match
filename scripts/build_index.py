"""
Rebuild the Qdrant index from raw professor rows — the "bring your own data" path.

This RE-EMBEDS each professor (so it needs an embedding API key) and is for users who want to
swap in their own dataset or a different embedding model. For the bundled sample, prefer the
snapshot path (`seed.py`) which reuses the exact production vectors at zero cost.

CAVEAT: the original production index's embedded document text was produced by a server-side
indexer that is not part of this repo. This script reconstructs a reasonable document from the
professor's fields (name + school + research areas/keywords + self-introduction). It is faithful
in spirit but may differ slightly from the original; the snapshot remains the ground truth.

Usage:
    # in api/ env (so `app` imports resolve), with EMBEDDING_API_KEY set:
    python scripts/build_index.py --rows data/professors_5000.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from app.config import get_settings            # noqa: E402
from app.providers.embedding import EmbeddingClient  # noqa: E402
from qdrant_client import QdrantClient          # noqa: E402
from qdrant_client.http import models as qm      # noqa: E402

MER_ID = 7


def _coerce(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}
    return {}


def build_document(row: dict) -> str:
    """Reconstruct the text to embed from a professor row (best-effort; see CAVEAT)."""
    ext = _coerce(row.get("extend"))
    aff = ext.get("affiliation") if isinstance(ext.get("affiliation"), dict) else {}
    parts = [
        row.get("store_name", ""),
        row.get("school_name", "") or aff.get("institution", ""),
        " ".join(ext.get("research_areas", []) if isinstance(ext.get("research_areas"), list) else []),
        " ".join(ext.get("research_keywords", []) if isinstance(ext.get("research_keywords"), list) else []),
        str(ext.get("self_introduction", "") or "")[:500],
    ]
    return " ".join(p for p in parts if p).strip()


def payload_for(row: dict) -> dict:
    return {
        "mer_id": MER_ID,
        "cate_id": int(row.get("cate_id") or 0),
        "school_region_id": int(row.get("school_region_id") or 0),
        "school_rank": int(row.get("school_rank") or 0),
        "school_type": int(row.get("school_type") or 0),
        "school_name": row.get("school_name", "") or "",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True, help="professors_*.jsonl")
    ap.add_argument("--batch", type=int, default=10)
    args = ap.parse_args()

    s = get_settings()
    emb = EmbeddingClient(s)
    client = QdrantClient(url=s.qdrant_url, timeout=120)
    client.recreate_collection(
        collection_name=s.qdrant_collection,
        vectors_config=qm.VectorParams(size=s.embedding_dim, distance=qm.Distance.COSINE),
    )

    rows = []
    with open(args.rows, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    total = 0
    for i in range(0, len(rows), args.batch):
        chunk = rows[i:i + args.batch]
        vectors = emb.embed([build_document(r) for r in chunk])
        pts = [
            qm.PointStruct(id=int(r["product_id"]), vector=v, payload=payload_for(r))
            for r, v in zip(chunk, vectors)
        ]
        client.upsert(collection_name=s.qdrant_collection, points=pts)
        total += len(pts)
        print(f"  embedded+upserted {total}/{len(rows)}", end="\r")
    print(f"\nbuilt index: {total} points in '{s.qdrant_collection}'")


if __name__ == "__main__":
    main()
