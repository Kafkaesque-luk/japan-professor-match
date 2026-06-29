"""
FastAPI entry point for professor-match.

Endpoints
  GET  /api/health   liveness + config visibility (no secrets)
  GET  /api/meta     form options for the web terminal (regions, ranks, types, disciplines)
  POST /api/match    run the match pipeline
Static web terminal (if built) is served at /.
"""

from __future__ import annotations

import os

from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.discipline import DisciplineCategoryService
from app.filters import RANK_RANGES, REGION_MAPPING, SCHOOL_TYPE_MAPPING
from app.pipeline import MatchError, match_professors
from app.query import get_store
from app.schemas import HealthResponse, MatchRequest

app = FastAPI(title="professor-match", version="0.1.0")

# CORS: the public demo is read-only; allow the static terminal + cross-origin previews.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        status="ok",
        professor_count=get_store().count,
        demo_mode=s.demo_mode,
        embedding_provider=s.embedding_provider,
        llm_provider=s.llm_provider,
        qdrant_url=s.qdrant_url,
        has_embedding_key=bool(s.effective_embedding_key),
    )


@app.get("/api/meta")
def meta() -> dict:
    disc = DisciplineCategoryService()
    return {
        "regions": sorted(REGION_MAPPING.keys()),
        "ranks": list(RANK_RANGES.keys()),
        "school_types": list(SCHOOL_TYPE_MAPPING.keys()),
        "disciplines": sorted(disc.middles()),
    }


@app.post("/api/match")
def match(req: MatchRequest) -> dict:
    try:
        return match_professors(req.user_input, req.filters.model_dump())
    except MatchError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # provider/qdrant failures -> 502 with a readable message
        raise HTTPException(status_code=502, detail=f"match failed: {e}")


# ---- admin: runtime deployment config (gated; disabled in demo mode; never leaks secrets) ----
_ADMIN_SETTABLE = {
    "embedding_provider", "embedding_model", "qwen_api_key", "qwen_model",
    "llm_provider", "embedding_api_key", "openai_api_key",
    "openai_embedding_model", "openai_llm_model",
}
_SECRET_FIELDS = {"embedding_api_key", "qwen_api_key", "openai_api_key"}


def _require_admin(token: Optional[str]) -> None:
    s = get_settings()
    if s.demo_mode:
        raise HTTPException(status_code=403, detail="admin disabled in demo mode")
    if not s.admin_token:
        raise HTTPException(status_code=403, detail="admin disabled: set ADMIN_TOKEN to enable")
    if token != s.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")


@app.get("/api/admin/config")
def admin_get_config(x_admin_token: Optional[str] = Header(default=None)) -> dict:
    _require_admin(x_admin_token)
    s = get_settings()
    out = {}
    for f in _ADMIN_SETTABLE:
        if f in _SECRET_FIELDS:
            out[f + "_set"] = bool(getattr(s, f))   # booleans only — never the secret
        else:
            out[f] = getattr(s, f)
    return out


@app.post("/api/admin/config")
def admin_set_config(payload: dict, x_admin_token: Optional[str] = Header(default=None)) -> dict:
    _require_admin(x_admin_token)
    s = get_settings()
    applied = []
    for k, v in (payload or {}).items():
        if k in _ADMIN_SETTABLE and isinstance(v, str):
            setattr(s, k, v)           # mutates the cached Settings for this process
            applied.append(k)
    return {"applied": applied}


# Serve the built web terminal at / if present (web/dist or web/).
_here = os.path.dirname(__file__)
for _candidate in (os.path.join(_here, "..", "web", "dist"), os.path.join(_here, "..", "web")):
    if os.path.isdir(_candidate) and os.path.exists(os.path.join(_candidate, "index.html")):
        app.mount("/", StaticFiles(directory=_candidate, html=True), name="web")
        break
