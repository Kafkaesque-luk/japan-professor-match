"""
The match orchestration — faithful port of the live ``AI.php::matchProfessors`` flow, minus the
production-only concerns that don't belong in an open-source extraction (points/billing, login,
history persistence, performance logging). The algorithm itself is identical.

Flow:
  validate -> expand keywords (LLM, optional) -> resolve discipline -> convert filters
  -> blend retrieval query -> embed -> Qdrant recall(150) -> three-tier bucket
  -> enrich/label -> group by school -> statistics
"""

from __future__ import annotations

import random
from typing import Any, Dict, Optional

from .config import Settings, get_settings
from .discipline import DisciplineCategoryService
from .filters import convert_ranks_to_ranges, convert_regions_to_ids, convert_school_types
from .providers.embedding import EmbeddingClient
from .providers.llm import expand_keywords
from .qdrant_client import QdrantProfessorClient
from .query import get_store
from .tiering import (
    bucket_candidates,
    calculate_match_statistics,
    group_professors_by_school,
    random_targets,
)

RECALL = 150  # production recall size before bucketing.


class MatchError(ValueError):
    pass


def match_professors(
    user_input: str,
    filters: Optional[Dict[str, Any]] = None,
    *,
    rng: Optional[random.Random] = None,
    cur_year: Optional[int] = None,
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    s = settings or get_settings()
    filters = filters or {}

    # 1. Validate (mirror production bounds).
    if not isinstance(user_input, str) or not user_input.strip():
        raise MatchError("user_input must not be empty")
    user_input = user_input.strip()
    if not (1 <= len(user_input) <= 200):
        raise MatchError("user_input length must be between 1 and 200 characters")
    universities = filters.get("universities") or []
    if isinstance(universities, list) and len(universities) > 3:
        raise MatchError("at most 3 universities may be specified")

    # 2. Keyword expansion (optional, degrades to [user_input]).
    expanded = expand_keywords(user_input, s)

    # 3. Discipline resolution (selected > inferred-from-text).
    disc = DisciplineCategoryService()
    applied_discipline = ""
    discipline_source = ""
    raw_disc = filters.get("discipline")
    raw_disc = raw_disc.strip() if isinstance(raw_disc, str) else ""
    if raw_disc and disc.is_valid_middle(raw_disc):
        applied_discipline, discipline_source = raw_disc, "selected"
    else:
        inferred = disc.detect_middle_from_text(user_input)
        if inferred:
            applied_discipline, discipline_source = inferred, "inferred"
    cate_ids = disc.get_cate_ids_by_middle(applied_discipline) if applied_discipline else []

    # 4. Convert frontend filters -> Qdrant search filters.
    sf: Dict[str, Any] = {}
    if filters.get("region"):
        region_ids = convert_regions_to_ids(filters["region"])
        if region_ids:
            sf["region_ids"] = region_ids
    if filters.get("university_ranks"):
        ranges = convert_ranks_to_ranges(filters["university_ranks"])
        if ranges:
            sf["rank_ranges"] = ranges
    if filters.get("school_types"):
        types = convert_school_types(filters["school_types"])
        if types:
            sf["school_types"] = types
    if universities:
        sf["school_names"] = universities
    if cate_ids:
        sf["cate_ids"] = cate_ids

    # 5. Blend top-5 expansion keywords into the embedding query (recall booster).
    retrieval_query = user_input
    if expanded and expanded != [user_input]:
        top = [k for k in expanded if isinstance(k, str) and k and k != user_input][:5]
        if top:
            retrieval_query = user_input + " " + " ".join(top)

    # 6. Embed + 7. retrieve.
    vector = EmbeddingClient(s).embed_one(retrieval_query)
    candidates = QdrantProfessorClient(s).retrieve(vector, sf, RECALL)

    # 8. Meta for bucketing + three-tier split.
    store = get_store()
    meta = store.meta_map([c["id"] for c in candidates])
    targets = random_targets(rng)
    popular_raw, prime_raw, value_raw = bucket_candidates(candidates, meta, targets, cur_year)

    # 9. Enrich + 10. group by school + 11. statistics.
    popular = store.enrich(popular_raw)
    niche = store.enrich(prime_raw)
    hidden = store.enrich(value_raw)

    stats = calculate_match_statistics(popular, niche, hidden)
    stats.update({
        "popular_expected": 50, "niche_expected": 15, "hidden_expected": 10,
        "is_popular_full": len(popular) >= 50,
        "is_niche_full": len(niche) >= 10,
        "is_hidden_full": len(hidden) >= 5,
    })

    def _slim(groups):
        # Drop the heavy CV blob from the response; title is pre-derived as `position`.
        for g in groups:
            for p in g["professors"]:
                p.pop("extend", None)
        return groups

    return {
        "popular_choices": _slim(group_professors_by_school(popular)),
        "niche_research": _slim(group_professors_by_school(niche)),
        "hidden_gems": _slim(group_professors_by_school(hidden)),
        "statistics": stats,
        "expanded_keywords": expanded,
        "applied_discipline": applied_discipline,
        "discipline_source": discipline_source,
        "retrieval": {"query": retrieval_query, "recall": len(candidates)},
    }
