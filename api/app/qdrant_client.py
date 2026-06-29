"""
Qdrant retrieval — faithful port of the live parts of
``php傀儡/app/common/clients/QdrantRAGClient.php`` (``buildQdrantFilter`` + vector search).

The live ``matchProfessors`` path calls retrieval with rerank DISABLED, so the rerank API is
intentionally not ported. Filter is an all-must conjunction:

  mer_id == 7  (always)
  school_region_id in region_ids        (if provided)
  school_rank in [min(all mins), max(all maxs)]   (rank_ranges merged to one band, if provided)
  school_type == / in school_types      (if provided)
  school_name in school_names           (if provided)
  cate_id in cate_ids                   (discipline hard filter, if provided)
"""

from __future__ import annotations

from typing import Any, Dict, List

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from .config import Settings, get_settings

MER_ID = 7


def build_qdrant_filter(filters: Dict[str, Any]) -> qm.Filter:
    must: List[qm.FieldCondition] = [
        qm.FieldCondition(key="mer_id", match=qm.MatchValue(value=MER_ID)),
    ]

    region_ids = filters.get("region_ids")
    if region_ids:
        must.append(qm.FieldCondition(
            key="school_region_id", match=qm.MatchAny(any=[int(x) for x in region_ids])))

    rank_ranges = filters.get("rank_ranges")
    if rank_ranges:
        mins = [r[0] for r in rank_ranges]
        maxs = [r[1] for r in rank_ranges]
        must.append(qm.FieldCondition(
            key="school_rank", range=qm.Range(gte=min(mins), lte=max(maxs))))

    school_types = filters.get("school_types")
    if school_types:
        st = [int(x) for x in school_types]
        if len(st) == 1:
            must.append(qm.FieldCondition(key="school_type", match=qm.MatchValue(value=st[0])))
        else:
            must.append(qm.FieldCondition(key="school_type", match=qm.MatchAny(any=st)))

    school_names = filters.get("school_names")
    if school_names:
        must.append(qm.FieldCondition(
            key="school_name", match=qm.MatchAny(any=[str(x) for x in school_names])))

    cate_ids = filters.get("cate_ids")
    if cate_ids:
        must.append(qm.FieldCondition(
            key="cate_id", match=qm.MatchAny(any=[int(x) for x in cate_ids])))

    return qm.Filter(must=must)


class QdrantProfessorClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()
        self.client = QdrantClient(url=self.s.qdrant_url, timeout=self.s.qdrant_timeout)

    def retrieve(self, query_vector: List[float], filters: Dict[str, Any], top_k: int = 150
                 ) -> List[Dict[str, Any]]:
        """Vector search -> candidate dicts ``{id, score, metadata}`` in relevance order."""
        flt = build_qdrant_filter(filters)
        res = self.client.query_points(
            collection_name=self.s.qdrant_collection,
            query=query_vector,
            query_filter=flt,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        ).points
        return [{"id": p.id, "score": p.score, "metadata": p.payload or {}} for p in res]
