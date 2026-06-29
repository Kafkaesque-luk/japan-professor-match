"""
Professor age estimation — faithful port of
``php傀儡/app/common/services/ai/ProfessorAgeEstimateService.php``.

Multi-angle birth-year inference from a researchmap CV (the ``extend`` blob), then a
consensus (median) birth year + a confidence grade:

  - explicit birth year in ``self_introduction`` (「19xx年…生まれ」) -> highest confidence
  - undergrad graduation (学部/学士)                               -> grad_year - 22
  - PhD (博士) / Master (修士/研究科/大学院)                        -> grad_year - 27 / - 24
  - earliest faculty appointment + title                          -> 助手/助教 -28, 講師 -33,
                                                                     准教授 -40, 教授 -47
  - fallbacks                                                     -> earliest edu year - 18,
                                                                     earliest career - 30

Confidence: explicit -> high; else median of estimates with high (>=2 strong anchors and
spread <= 5y) / medium (>=1 strong) / low. Age outside [25, 92] is downgraded to low.

This is the single source of truth shared with the production system; the matcher uses it
to populate the "年富力强 / prime-age" tier (keep only high|medium confidence, age in [33, 55]).
Behaviour is byte-faithful to production; the quirks below are preserved on purpose.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

RETIRE_AGE = 65

# Title -> typical appointment age (anchor: subtract from first-appointment year -> birth year).
#
# NOTE (preserved quirk): the order matters and matches PHP exactly. '教授' is tested before
# '准教授', and because a 准教授 line contains the substring '教授', a 准教授 career entry
# substring-matches '教授' first and yields offset 47 (not 40). This is the exact production
# behaviour — do NOT reorder to "fix" it, or estimates will diverge from the live system.
# (The separate title *tiering* sorter in tiering.py deliberately uses the careful order.)
_TITLE_AGE = [("教授", 47), ("准教授", 40), ("助教授", 40), ("講師", 33), ("助教", 28), ("助手", 28)]

_YEAR_RE = re.compile(r"(19\d\d|20\d\d)")
_BIRTH_RE = re.compile(r"(19\d\d)年.{0,10}(生まれ|生)")


def _years_in(s: Any) -> List[int]:
    """Extract every 4-digit year (1900-2099) from a string, in order."""
    if not isinstance(s, str) or s == "":
        return []
    return [int(y) for y in _YEAR_RE.findall(s)]


def estimate_from_extend(extend: Any, cur_year: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Estimate age from a decoded ``extend`` dict.

    Returns ``None`` when there is no usable year signal at all (the honest "give up"),
    otherwise a dict with keys: ``birth_year``, ``age``, ``confidence``
    ('high'|'medium'|'low'), ``method``, ``retire_in``, ``anchors``.
    """
    if not isinstance(extend, dict):
        return None
    cur = int(cur_year) if cur_year else datetime.now().year

    intro = str(extend.get("self_introduction") or "")
    edu = extend.get("education") if isinstance(extend.get("education"), list) else []
    car = extend.get("career_history") if isinstance(extend.get("career_history"), list) else []

    ests: List[Dict[str, Any]] = []  # each: {"birth": int, "label": str}

    # 1. Explicit birth year (highest confidence).
    m = _BIRTH_RE.search(intro)
    if m:
        ests.append({"birth": int(m.group(1)), "label": "birth_explicit"})

    # 2. Education milestones.
    for raw in edu:
        e = str(raw)
        ys = _years_in(e)
        if not ys:
            continue
        mx, mn = max(ys), min(ys)
        if "学部" in e or "学士" in e:
            ests.append({"birth": mx - 22, "label": "undergrad"})
        elif "博士" in e:
            ests.append({"birth": mx - 27, "label": "phd"})
        elif "修士" in e or "研究科" in e or "大学院" in e:
            ests.append({"birth": mx - 24, "label": "master"})
        else:
            ests.append({"birth": mn - 18, "label": "edu_gen"})

    # 3. Earliest faculty appointment (skip in-progress student entries).
    fac: List[Dict[str, Any]] = []
    for raw in car:
        c = str(raw)
        if "学生" in c or "student" in c.lower():
            continue
        ys = _years_in(c)
        if not ys:
            continue
        age = None
        for title, off in _TITLE_AGE:
            if title in c:
                age = off
                break
        fac.append({"start": min(ys), "age": age})
    if fac:
        fac.sort(key=lambda x: x["start"])
        f = fac[0]
        ests.append({
            "birth": f["start"] - (f["age"] if f["age"] is not None else 30),
            "label": "career_first" if f["age"] is not None else "career_notitle",
        })

    if not ests:
        return None

    # Consensus.
    explicit = [e["birth"] for e in ests if e["label"] == "birth_explicit"]
    if explicit:
        birth = explicit[0]
        conf = "high"
        method = "birth_explicit"
    else:
        bs = sorted(e["birth"] for e in ests)
        birth = bs[len(bs) // 2]  # median index == PHP intdiv(count, 2)
        spread = (bs[-1] - bs[0]) if len(bs) > 1 else 99
        labels: Dict[str, bool] = {}
        strong: List[Dict[str, Any]] = []
        for e in ests:
            labels[e["label"]] = True
            if e["label"] in ("undergrad", "phd", "master", "career_first"):
                strong.append(e)
        if len(strong) >= 2 and spread <= 5:
            conf = "high"
        elif strong:
            conf = "medium"
        else:
            conf = "low"
        method = "+".join(sorted(labels.keys()))

    age = cur - birth
    if age < 25 or age > 92:
        conf = "low"

    return {
        "birth_year": birth,
        "age": age,
        "confidence": conf,
        "method": method,
        "retire_in": RETIRE_AGE - age,
        "anchors": len(ests),
    }


def estimate_from_json(extend_json: Any, cur_year: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Tolerant variant: parse a JSON string then estimate. Returns ``None`` on bad JSON."""
    if not isinstance(extend_json, str) or extend_json == "":
        return None
    import json
    try:
        data = json.loads(extend_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return estimate_from_extend(data, cur_year)
