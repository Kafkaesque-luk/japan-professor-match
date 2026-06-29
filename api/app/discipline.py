"""
Discipline (中分類) resolution — faithful port of
``php傀儡/app/common/services/ai/DisciplineCategoryService.php``.

Two jobs:
  1. Map a user-selected mid-category name (e.g. "经济学与管理学") to its set of ResearchMap
     ``cate_id``s, used as a HARD Qdrant payload filter (cate_id any) so an "economics" search
     can never surface law/literature professors.
  2. When the user did not pick a discipline, deterministically infer one from the free-text
     research interest — but only when EXACTLY ONE mid-category matches (0 or >=2 -> no filter).

Token rule (the anti-pollution heart): recognition tokens = the full mid-category name plus the
sub-parts split on 「与 / 、 / 和」 that are >= 2 chars AND end with 「学」 (经济学, 管理学, 社会学…).
Generic words (政策/思想/语言/历史/文化/地理/艺术…) are intentionally excluded — they cross
mid-categories and would turn a clean unique hit into an ambiguous miss.

Fail-safe: if the taxonomy JSON is missing/corrupt, every method degrades to "no discipline
constraint" and never blocks the match.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

_SPLIT_RE = re.compile(r"[与、和]")

_DEFAULT_MAPPING_FILE = os.path.join(os.path.dirname(__file__), "data", "category_id_to_url_mapping.json")


class DisciplineCategoryService:
    """Stateless-ish helper; the taxonomy is loaded once per instance (cheap, ~300 rows)."""

    def __init__(self, mapping_file: Optional[str] = None) -> None:
        self._middle_to_cate_ids: Dict[str, List[int]] = {}
        self._middle_to_tokens: Dict[str, List[str]] = {}
        self._load(mapping_file or _DEFAULT_MAPPING_FILE)

    def _load(self, path: str) -> None:
        # Default empty mapping => safe "no constraint" degrade even if anything below fails.
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            return
        mapping = data.get("mapping") if isinstance(data, dict) else None
        if not mapping:
            return

        middle_to_cate_ids: Dict[str, List[int]] = {}
        for info in mapping.values():
            try:
                cate_id = int(info.get("category_id") or 0)
            except (ValueError, TypeError):
                cate_id = 0
            if cate_id <= 0:
                continue
            # Match the frontend: fall back to japanese_name when middle_category is blank.
            middle = info.get("middle_category") or ""
            if not middle:
                middle = info.get("japanese_name") or ""
            if not middle:
                continue
            middle_to_cate_ids.setdefault(middle, []).append(cate_id)

        middle_to_tokens: Dict[str, List[str]] = {}
        for middle in middle_to_cate_ids:
            tokens = [middle]
            for part in _SPLIT_RE.split(middle):
                part = part.strip()
                if len(part) >= 2 and part[-1:] == "学":
                    tokens.append(part)
            # Dedup, longest first (prefer long matches; reduces accidental hits).
            tokens = list(dict.fromkeys(tokens))
            tokens.sort(key=len, reverse=True)
            middle_to_tokens[middle] = tokens

        self._middle_to_cate_ids = middle_to_cate_ids
        self._middle_to_tokens = middle_to_tokens

    def middles(self) -> List[str]:
        """All known mid-category names (for the web terminal's discipline picker)."""
        return list(self._middle_to_cate_ids.keys())

    def is_valid_middle(self, middle: str) -> bool:
        return bool(middle) and middle in self._middle_to_cate_ids

    def get_cate_ids_by_middle(self, middle: str) -> List[int]:
        return self._middle_to_cate_ids.get(middle, [])

    def detect_middle_from_text(self, text: str) -> Optional[str]:
        """Return the unique mid-category whose tokens appear in ``text``; ``None`` if 0 or >=2."""
        text = (text or "").strip()
        if not text or not self._middle_to_tokens:
            return None
        matched: Dict[str, bool] = {}
        for middle, tokens in self._middle_to_tokens.items():
            for token in tokens:
                if token and token in text:
                    matched[middle] = True
                    break
        if len(matched) == 1:
            return next(iter(matched))
        return None
