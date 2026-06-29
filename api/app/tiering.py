"""
Three-tier bucketing, school grouping, title-tier sorting and statistics — faithful port of
the relevant parts of ``AI.php::matchProfessors`` / ``groupProfessorsBySchool`` /
``getProfessorTitleTier`` / ``calculateMatchStatistics``.

The three tiers are three independent *views* over ONE recall pool (overlap allowed), not a
relevance pool sliced into thirds:
  - 海选匹配 / popular   : the top ~50 by vector relevance (no rerank) — "who fits best"
  - 年富力强 / prime-age : keep only high|medium-confidence age in [33, 55] — "who can still take me on"
  - 潜力洼地 / value      : strong matches at non-top schools (school_rank not in 1..30) — "easier landing / better value"
"""

from __future__ import annotations

import json
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

from .age_estimation import estimate_from_extend

# Prime-age window (年富力强). Faithful to production: 33 <= age <= 55, "确定年龄" only.
PRIME_MIN_AGE = 33
PRIME_MAX_AGE = 55

# Default target counts with the production random jitter (±10/15/20%).
POPULAR_RANGE = (45, 55)
NICHE_RANGE = (17, 23)
HIDDEN_RANGE = (8, 12)


def random_targets(rng: Optional[random.Random] = None) -> Tuple[int, int, int]:
    """Production-style jittered targets. Pass a seeded Random for reproducible demos."""
    r = rng or random
    return (
        r.randint(*POPULAR_RANGE),
        r.randint(*NICHE_RANGE),
        r.randint(*HIDDEN_RANGE),
    )


def _coerce_extend(raw: Any) -> Optional[dict]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def bucket_candidates(
    all_candidates: List[Dict[str, Any]],
    meta_map: Dict[int, Dict[str, Any]],
    targets: Tuple[int, int, int],
    cur_year: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split the (already relevance-ordered) Qdrant candidates into the three tiers.

    ``all_candidates`` : list of {id, score, metadata}, vector-relevance descending.
    ``meta_map``       : product_id -> {"extend": <str|dict>, "school_rank": <int>}.
    Returns ``(popular_raw, prime_raw, value_raw)`` — still candidate dicts, not enriched.
    """
    popular_target, niche_target, hidden_target = targets
    total = len(all_candidates)

    # 1. Popular: top-N by relevance, no rerank.
    popular = all_candidates[: min(popular_target, total)]

    # 2. Prime-age: same algorithm the frontend uses for the age badge; high|medium only, [33,55].
    prime: List[Dict[str, Any]] = []
    for c in all_candidates:
        if len(prime) >= niche_target:
            break
        pid = int(c.get("id") or 0)
        if pid <= 0 or pid not in meta_map:
            continue
        extend = _coerce_extend(meta_map[pid].get("extend"))
        if not extend:
            continue
        est = estimate_from_extend(extend, cur_year)
        if not est or est["confidence"] not in ("high", "medium"):
            continue
        age = int(est["age"])
        if age < PRIME_MIN_AGE or age > PRIME_MAX_AGE:
            continue
        prime.append(c)
    prime = prime[:niche_target]

    # 3. Value: skip top-30 schools; DB rank authoritative, fall back to payload rank.
    value: List[Dict[str, Any]] = []
    for c in all_candidates:
        pid = int(c.get("id") or 0)
        if pid in meta_map and meta_map[pid].get("school_rank") is not None:
            rank = int(meta_map[pid]["school_rank"] or 0)
        else:
            rank = int((c.get("metadata") or {}).get("school_rank") or 0)
        if 1 <= rank <= 30:
            continue
        value.append(c)
    value = value[:hidden_target]

    return popular, prime, value


# Title -> sort tier (smaller = shown first). Ordered MOST-SPECIFIC FIRST so that e.g.
# "准教授" is classified Tier 2 before the bare "教授" check can grab it as Tier 1.
# (Distinct from age_estimation._TITLE_AGE, which preserves the opposite, looser order.)
_TITLE_TIERS = [
    ("特任准教授", 2), ("客員准教授", 2), ("名誉教授", 2), ("准教授", 2),
    ("特任教授", 1), ("客員教授", 1), ("教授", 1),
    ("特任講師", 3), ("客員講師", 3), ("講師", 3),
    ("特任助教", 4), ("客員助教", 4), ("助教", 4), ("助手", 4),
    ("シニアリサーチ・フェロー", 5), ("シニアフェロー", 5), ("リサーチ・フェロー", 5),
    ("フェロー", 5), ("特任研究員", 5), ("客員研究員", 5), ("特別研究員", 5),
    ("博士研究員", 5), ("招聘研究員", 5), ("研究員", 5), ("技術職員", 5), ("事務職員", 5),
]


def _score_of(prof: Dict[str, Any]) -> float:
    v = prof.get("match_score")
    if v is None:
        v = prof.get("similarity_score")
    if v is None:
        v = 0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def get_professor_title_tier(prof: Dict[str, Any]) -> int:
    """Sort tier 1..6 from ``extend.affiliation.position`` (6 = unknown/empty -> last)."""
    extend = _coerce_extend(prof.get("extend"))
    position = ""
    if extend:
        aff = extend.get("affiliation")
        if isinstance(aff, dict):
            position = aff.get("position") or ""
    if not position:
        return 6
    for title, tier in _TITLE_TIERS:
        if title in position:
            return tier
    return 6


def group_professors_by_school(professors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group enriched professor dicts by ``extend.affiliation.institution``.

    Within a school: sort by title tier asc, then score desc. Across schools: sort by avg
    score desc. Returns ``[{school_name, avg_score, professor_count, professors}, ...]``.
    """
    if not professors:
        return []

    groups: Dict[str, Dict[str, Any]] = {}
    for prof in professors:
        institution = "未知学校"
        extend = _coerce_extend(prof.get("extend"))
        if extend:
            aff = extend.get("affiliation")
            if isinstance(aff, dict) and aff.get("institution"):
                institution = aff["institution"]
        g = groups.setdefault(institution, {"professors": [], "scores": []})
        g["professors"].append(prof)
        g["scores"].append(_score_of(prof))

    result: List[Dict[str, Any]] = []
    for institution, g in groups.items():
        avg = (sum(g["scores"]) / len(g["scores"])) if g["scores"] else 0.0
        g["professors"].sort(key=lambda p: (get_professor_title_tier(p), -_score_of(p)))
        result.append({
            "school_name": institution,
            "avg_score": round(avg, 3),
            "professor_count": len(g["professors"]),
            "professors": g["professors"],
        })

    result.sort(key=lambda x: x["avg_score"], reverse=True)
    return result


def calculate_match_statistics(
    popular: List[Dict[str, Any]],
    niche: List[Dict[str, Any]],
    hidden: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Counts, cross-tier overlap, and per-tier average scores (faithful field shape)."""
    def ids(xs):
        return [p.get("product_id") for p in xs]

    all_ids = ids(popular) + ids(niche) + ids(hidden)
    unique_ids = set(all_ids)

    def avg(xs):
        scores = [float(p["match_score"]) for p in xs
                  if isinstance(p.get("match_score"), (int, float))
                  or (isinstance(p.get("match_score"), str) and p["match_score"].replace(".", "", 1).isdigit())]
        return round(sum(scores) / len(scores), 3) if scores else 0.0

    return {
        "popular_count": len(popular),
        "niche_count": len(niche),
        "hidden_count": len(hidden),
        "total_count": len(unique_ids),
        "overlap_count": len(all_ids) - len(unique_ids),
        "popular_avg_score": avg(popular),
        "niche_avg_score": avg(niche),
        "hidden_avg_score": avg(hidden),
    }
