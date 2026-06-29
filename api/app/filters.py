"""
Frontend filter -> Qdrant filter conversion — faithful port of
``php傀儡/app/common/services/ai/FilterConversionService.php``.

  - 8 macro-regions  -> prefecture cate_ids (school_region_id)
  - rank labels      -> [min, max] rank ranges (school_rank)
  - school types     -> brand_ids (1 = national/public, 2 = private)

The natural-language description method from the PHP is intentionally omitted: in the live
``matchProfessors`` path it is computed and discarded (vestigial), so the port doesn't need it.
"""

from __future__ import annotations

from typing import Any, Iterable, List

# 8 macro-region -> prefecture cate_ids (source: eb_store_category, cate_id 165-211).
REGION_MAPPING = {
    "hokkaido": [179],
    "tohoku": [188, 189, 190, 191, 192, 193],
    "kanto": [165, 166, 167, 168, 169, 170, 171],
    "chubu": [199, 200, 201, 202, 203, 204, 205, 206, 207],
    "kinki": [172, 173, 174, 175, 176, 177, 178],
    "chugoku": [194, 195, 196, 197, 198],
    "shikoku": [208, 209, 210, 211],
    "kyushu": [180, 181, 182, 183, 184, 185, 186, 187],
}

# Rank label -> inclusive [min, max] ranking band.
RANK_RANGES = {
    "SSS": [1, 10],
    "S": [11, 30],
    "A": [31, 80],
    "B": [81, 150],
    "C": [151, 250],
    "D": [251, 300],
    "E": [301, 9999],
}

# School nature -> brand_id.
SCHOOL_TYPE_MAPPING = {
    "national": 1,  # 国公立
    "private": 2,   # 私立
}


def convert_regions_to_ids(regions: Iterable[Any]) -> List[int]:
    """Macro-region keys -> sorted unique prefecture ids. Unknown keys are skipped."""
    if not regions:
        return []
    out: List[int] = []
    for region in regions:
        if not isinstance(region, str):
            continue
        key = region.strip().lower()
        if key in REGION_MAPPING:
            out.extend(REGION_MAPPING[key])
    return sorted(set(out))


def convert_ranks_to_ranges(ranks: Iterable[Any]) -> List[List[int]]:
    """Rank labels -> list of [min, max] ranges (order preserved, no dedup, matching PHP)."""
    if not ranks:
        return []
    ranges: List[List[int]] = []
    for rank in ranks:
        if not isinstance(rank, str):
            continue
        key = rank.strip().upper()
        if key in RANK_RANGES:
            ranges.append(list(RANK_RANGES[key]))
    return ranges


def convert_school_types(types: Iterable[Any]) -> List[int]:
    """School types -> sorted unique brand_ids. Accepts ints (1/2) or strings (national/private)."""
    if not types:
        return []
    brand_ids: List[int] = []
    for t in types:
        if isinstance(t, bool):
            continue
        if isinstance(t, int) or (isinstance(t, str) and t.strip().lstrip("-").isdigit()):
            ti = int(t)
            if ti in (1, 2):
                brand_ids.append(ti)
            continue
        if isinstance(t, str):
            key = t.strip().lower()
            if key in SCHOOL_TYPE_MAPPING:
                brand_ids.append(SCHOOL_TYPE_MAPPING[key])
    return sorted(set(brand_ids))
