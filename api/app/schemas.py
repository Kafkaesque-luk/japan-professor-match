"""Request/response schemas for the match API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MatchFilters(BaseModel):
    region: List[str] = Field(default_factory=list, description="macro-region keys, e.g. ['kanto']")
    university_ranks: List[str] = Field(default_factory=list, description="rank labels, e.g. ['SSS','S']")
    school_types: List[Any] = Field(default_factory=list, description="['national','private'] or [1,2]")
    universities: List[str] = Field(default_factory=list, description="exact school names, max 3")
    discipline: Optional[str] = Field(default=None, description="mid-category name (hard filter)")


class MatchRequest(BaseModel):
    user_input: str = Field(..., min_length=1, max_length=200, description="research interest text")
    filters: MatchFilters = Field(default_factory=MatchFilters)


class HealthResponse(BaseModel):
    status: str
    professor_count: int
    demo_mode: bool
    embedding_provider: str
    llm_provider: str
    qdrant_url: str
    has_embedding_key: bool
