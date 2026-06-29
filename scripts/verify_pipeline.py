#!/usr/bin/env python3
"""
End-to-end pipeline check on the REAL sample, with NO Docker and NO API key.

Loads the 5,000 exported vectors into an in-memory Qdrant, then uses one professor's own vector
as the query (so we don't need to call an embedding API) and runs the actual app pipeline:
build_qdrant_filter -> vector search -> three-tier bucketing -> enrich -> group by school.
This exercises everything except the live embedding/keyword-expansion calls (trivial HTTP).

Run:  python scripts/verify_pipeline.py
"""

from __future__ import annotations

import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "api"))

from qdrant_client import QdrantClient                # noqa: E402
from qdrant_client.http import models as qm           # noqa: E402

from app.io_utils import open_text                     # noqa: E402
from app.qdrant_client import build_qdrant_filter      # noqa: E402
from app.query import ProfessorStore                   # noqa: E402
from app.tiering import (                              # noqa: E402
    bucket_candidates,
    calculate_match_statistics,
    group_professors_by_school,
)

POINTS = os.path.join(HERE, "data", "qdrant_snapshot", "points.jsonl")


def load_points():
    pts = []
    with open_text(POINTS) as fh:
        for line in fh:
            line = line.strip()
            if line:
                pts.append(json.loads(line))
    return pts


def search(client, vector, filters, top_k):
    res = client.query_points(
        collection_name="professors",
        query=vector,
        query_filter=build_qdrant_filter(filters),
        limit=top_k,
        with_payload=True,
        with_vectors=False,
    ).points
    return [{"id": p.id, "score": p.score, "metadata": p.payload or {}} for p in res]


def show(title, groups, limit=3):
    n = sum(g["professor_count"] for g in groups)
    print(f"\n{title}: {n} professors across {len(groups)} schools")
    for g in groups[:limit]:
        top = g["professors"][0]
        age = top.get("age_estimate")
        age_s = f", ~{age['age']}y({age['confidence']})" if age else ""
        print(f"  - {g['school_name']} (avg {g['avg_score']:.3f}, {g['professor_count']} profs)"
              f"  e.g. {top.get('store_name','?')}{age_s}")


def main():
    pts = load_points()
    print(f"loaded {len(pts)} points; building in-memory Qdrant ...")
    client = QdrantClient(":memory:")
    client.recreate_collection(
        collection_name="professors",
        vectors_config=qm.VectorParams(size=len(pts[0]["vector"]), distance=qm.Distance.COSINE),
    )
    client.upsert(
        collection_name="professors",
        points=[qm.PointStruct(id=int(p["id"]), vector=p["vector"], payload=p.get("payload") or {})
                for p in pts],
    )

    store = ProfessorStore()
    # Query = a professor's own vector (top hit should be itself; neighbours are similar work).
    q = pts[123]
    qprof = store.by_id.get(int(q["id"]), {})
    print(f"query professor: {qprof.get('store_name','?')} @ {qprof.get('school_name','?')} "
          f"(cate_id {qprof.get('cate_id')})")

    candidates = search(client, q["vector"], {}, 150)
    print(f"recall: {len(candidates)} candidates")

    meta = store.meta_map([c["id"] for c in candidates])
    targets = (50, 20, 10)  # fixed (not jittered) for a stable readout
    popular_raw, prime_raw, value_raw = bucket_candidates(candidates, meta, targets)
    popular = store.enrich(popular_raw)
    niche = store.enrich(prime_raw)
    hidden = store.enrich(value_raw)

    show("海选匹配 (best match)", group_professors_by_school(popular))
    show("年富力强 (prime-age 33-55)", group_professors_by_school(niche))
    show("潜力洼地 (value, non-top-30)", group_professors_by_school(hidden))

    stats = calculate_match_statistics(popular, niche, hidden)
    print(f"\nstatistics: {json.dumps(stats, ensure_ascii=False)}")

    # Filter spot-check: same query, restricted to top-30 schools only.
    flt = search(client, q["vector"], {"rank_ranges": [[1, 30]]}, 150)
    ranks = [int((c['metadata'] or {}).get('school_rank') or 0) for c in flt]
    bad = [r for r in ranks if not (1 <= r <= 30)]
    print(f"\nfilter check (rank 1-30): {len(flt)} hits, out-of-range={len(bad)} (expect 0 among ranked)")


if __name__ == "__main__":
    main()
