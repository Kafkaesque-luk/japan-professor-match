"""
Professor detail store + enrichment — the standalone replacement for the DB-backed
``ProfessorQueryService::getProfessorsByIdsWithScores`` and the ``store_product`` meta lookups
in ``matchProfessors``.

Production reads ``eb_store_product`` rows by id; here the 5,000-professor sample lives in a
JSONL file and is loaded once into an in-memory dict keyed by ``product_id``. Enrichment merges
the Qdrant relevance score, formats the rank/type labels, and attaches a convenience age badge
(computed with the single-source-of-truth estimator) for the web terminal to render.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

from .age_estimation import estimate_from_extend
from .config import Settings, get_settings
from .io_utils import open_text, resolve_data


def format_rank_label(rank: Any) -> str:
    r = int(rank or 0)
    if 1 <= r <= 10:
        return "SSS"
    if 11 <= r <= 30:
        return "S"
    if 31 <= r <= 80:
        return "A"
    if 81 <= r <= 150:
        return "B"
    if 151 <= r <= 250:
        return "C"
    if r > 250:
        return "D"
    return ""


def format_type_label(t: Any) -> str:
    return {1: "国公立", 2: "私立"}.get(int(t or 0), "")


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


class ProfessorStore:
    def __init__(self, path: Optional[str] = None, settings: Optional[Settings] = None) -> None:
        self.s = settings or get_settings()
        self.by_id: Dict[int, dict] = {}
        self.path = resolve_data(path) if path else self._resolve_path()
        if self.path and os.path.exists(self.path):
            self._load(self.path)

    def _resolve_path(self) -> str:
        here = os.path.dirname(__file__)
        candidates = [
            self.s.professors_data_path,
            "data/professors_5000.jsonl",
            os.path.join(here, "..", "..", "data", "professors_5000.jsonl"),
            "/data/professors_5000.jsonl",
        ]
        for c in candidates:
            if not c:
                continue
            r = resolve_data(c)
            if os.path.exists(r):
                return r
        return ""

    def _load(self, path: str) -> None:
        with open_text(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                pid = int(row.get("product_id") or row.get("id") or 0)
                if pid > 0:
                    self.by_id[pid] = row

    @property
    def count(self) -> int:
        return len(self.by_id)

    def meta_map(self, ids: Iterable[Any]) -> Dict[int, Dict[str, Any]]:
        out: Dict[int, Dict[str, Any]] = {}
        for raw in ids:
            pid = int(raw or 0)
            row = self.by_id.get(pid)
            if row is not None:
                out[pid] = {"extend": row.get("extend"), "school_rank": row.get("school_rank")}
        return out

    def enrich(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Candidates ``{id, score, metadata}`` -> enriched professor dicts (order preserved, deduped)."""
        seen = set()
        result: List[Dict[str, Any]] = []
        for c in candidates:
            pid = int(c.get("id") or 0)
            if pid <= 0 or pid in seen:
                continue
            row = self.by_id.get(pid)
            if row is None:
                continue
            seen.add(pid)
            score = c.get("score") or 0
            extend = _coerce_extend(row.get("extend"))
            aff = extend.get("affiliation") if (extend and isinstance(extend.get("affiliation"), dict)) else {}
            prof: Dict[str, Any] = {
                "product_id": pid,
                "store_name": row.get("store_name", ""),
                "position": (aff.get("position") or "") if isinstance(aff, dict) else "",
                "image": row.get("image", ""),
                "school_name": row.get("school_name", ""),
                "school_rank": row.get("school_rank", 0),
                "school_type": row.get("school_type", 0),
                "school_region_id": row.get("school_region_id", 0),
                "cate_id": row.get("cate_id", 0),
                "extend": row.get("extend"),
                "school_rank_label": format_rank_label(row.get("school_rank")),
                "school_type_label": format_type_label(row.get("school_type")),
                "match_score": score,
                "similarity_score": score,
            }
            # Convenience age badge (high|medium only) — single source of truth.
            est = estimate_from_extend(extend) if extend else None
            if est and est["confidence"] in ("high", "medium"):
                prof["age_estimate"] = {"age": est["age"], "confidence": est["confidence"],
                                        "retire_in": est["retire_in"]}
            else:
                prof["age_estimate"] = None
            result.append(prof)
        return result


@lru_cache
def get_store() -> ProfessorStore:
    return ProfessorStore()
