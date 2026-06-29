"""
Behavioural tests pinning the deterministic core to the production PHP semantics.

Run:  cd api && python -m pytest -q
These assert the exact documented behaviour (including the preserved quirks). Golden parity
against live PHP output over real CVs is added in Phase 3 once the 5000-row sample is exported.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.age_estimation import estimate_from_extend  # noqa: E402
from app.discipline import DisciplineCategoryService  # noqa: E402
from app.filters import (  # noqa: E402
    convert_ranks_to_ranges,
    convert_regions_to_ids,
    convert_school_types,
)
from app.tiering import bucket_candidates, get_professor_title_tier, group_professors_by_school


# ---- age estimation -------------------------------------------------------------------

def test_explicit_birth_year_is_high_confidence():
    est = estimate_from_extend({"self_introduction": "私は1975年に東京で生まれました。"}, cur_year=2026)
    assert est["birth_year"] == 1975
    assert est["age"] == 51
    assert est["confidence"] == "high"
    assert est["method"] == "birth_explicit"


def test_undergrad_offset_minus_22():
    est = estimate_from_extend({"education": ["1998年 京都大学 経済学部 卒業"]}, cur_year=2026)
    assert est["birth_year"] == 1998 - 22  # 1976
    assert est["method"] == "undergrad"


def test_two_strong_anchors_tight_spread_is_high():
    est = estimate_from_extend(
        {"education": ["1998年 学部 卒業", "2003年 博士課程 修了"]},  # 1976 & 1976
        cur_year=2026,
    )
    assert est["confidence"] == "high"  # undergrad(1976) + phd(1976), spread 0 <= 5


def test_no_year_signal_returns_none():
    assert estimate_from_extend({"self_introduction": "研究者です。"}) is None
    assert estimate_from_extend({}) is None


def test_age_out_of_range_downgrades_to_low():
    # 1955 undergrad -> birth 1933 -> age 93 (>92) -> downgraded to low.
    # (A pre-1900 year would be ignored by the year regex entirely and return None — by design.)
    est = estimate_from_extend({"education": ["1955年 学部 卒業"]}, cur_year=2026)
    assert est["age"] == 93
    assert est["confidence"] == "low"


def test_junkyoju_substring_quirk_is_preserved():
    # PRESERVED QUIRK: '准教授' substring-matches '教授' first -> offset 47 (not 40).
    est = estimate_from_extend({"career_history": ["2010年 准教授 着任"]}, cur_year=2026)
    assert est["birth_year"] == 2010 - 47


# ---- discipline -----------------------------------------------------------------------

def test_discipline_unique_hit():
    svc = DisciplineCategoryService()
    # "经济学" is a 学-ending token of its mid-category and should resolve uniquely.
    middle = svc.detect_middle_from_text("我想研究经济学方向")
    assert middle is not None
    assert svc.is_valid_middle(middle)
    assert len(svc.get_cate_ids_by_middle(middle)) > 0


def test_discipline_no_signal_returns_none():
    svc = DisciplineCategoryService()
    assert svc.detect_middle_from_text("随便看看") is None


# ---- filters --------------------------------------------------------------------------

def test_region_mapping():
    assert convert_regions_to_ids(["kanto"]) == [165, 166, 167, 168, 169, 170, 171]
    assert convert_regions_to_ids(["KANTO", "kanto"]) == [165, 166, 167, 168, 169, 170, 171]
    assert convert_regions_to_ids(["nope"]) == []


def test_rank_ranges():
    assert convert_ranks_to_ranges(["SSS", "s"]) == [[1, 10], [11, 30]]


def test_school_types_accepts_int_and_string():
    assert convert_school_types(["national", "private"]) == [1, 2]
    assert convert_school_types([2, 1]) == [1, 2]
    assert convert_school_types([9]) == []


# ---- tiering --------------------------------------------------------------------------

def _cand(pid, score, rank=None):
    md = {} if rank is None else {"school_rank": rank}
    return {"id": pid, "score": score, "metadata": md}


def test_value_tier_skips_top30_schools():
    cands = [_cand(1, 0.9, rank=5), _cand(2, 0.8, rank=45), _cand(3, 0.7, rank=0)]
    _, _, value = bucket_candidates(cands, meta_map={}, targets=(50, 20, 10))
    ids = [c["id"] for c in value]
    assert 1 not in ids       # rank 5 -> top school, excluded
    assert 2 in ids and 3 in ids  # rank 45 and unranked(0) -> value opportunities


def test_title_tier_ordering():
    assert get_professor_title_tier({"extend": {"affiliation": {"position": "教授"}}}) == 1
    assert get_professor_title_tier({"extend": {"affiliation": {"position": "准教授"}}}) == 2
    assert get_professor_title_tier({"extend": {"affiliation": {"position": "名誉教授"}}}) == 2
    assert get_professor_title_tier({"extend": {}}) == 6


def test_group_by_school_orders_professor_then_avg():
    profs = [
        {"product_id": 1, "match_score": 0.7, "extend": {"affiliation": {"institution": "A大学", "position": "助教"}}},
        {"product_id": 2, "match_score": 0.9, "extend": {"affiliation": {"institution": "A大学", "position": "教授"}}},
    ]
    groups = group_professors_by_school(profs)
    assert groups[0]["school_name"] == "A大学"
    # Within school: 教授 (tier 1) before 助教 (tier 4) regardless of score.
    assert groups[0]["professors"][0]["product_id"] == 2
