"""
FastAPI entry point for japan-professor-match.

Endpoints
  GET  /api/health           liveness + config visibility (no secrets)
  GET  /api/meta             form options for the web terminal (regions, ranks, types, disciplines)
  POST /api/match            run the match pipeline
  GET  /api/professor/{id}       full detail for one professor (the terminal's detail page)
  POST /api/professor/{id}/chat  stateless persona chat (the terminal's AI simulated dialog)
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

app = FastAPI(title="japan-professor-match", version="0.1.0")

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


@app.get("/api/professor/{product_id}")
def professor_detail(product_id: int) -> dict:
    """Full detail for one matched professor — powers the terminal's app-identical detail page."""
    row = get_store().detail(product_id)
    if row is None:
        raise HTTPException(status_code=404, detail="professor not found")
    return row


@app.post("/api/professor/{product_id}/chat")
def professor_chat(product_id: int, payload: dict) -> dict:
    """Stateless professor persona chat (the production five-layer prompt, no sessions/billing).

    Body: {"message": str, "history": [{"role": "user"|"assistant", "content": str}, ...]}.
    Empty message + empty history -> the persona's opening greeting.
    """
    from datetime import date

    from app.persona import (OPENING_TRIGGER, build_professor_system_prompt,
                             parse_professor_profile, sanitize_history)
    from app.providers.llm import chat_completion
    from app.query import _coerce_extend  # same coercion the store uses

    row = get_store().detail(product_id)
    if row is None:
        raise HTTPException(status_code=404, detail="professor not found")
    extend = _coerce_extend(row.get("extend")) or {}

    payload = payload or {}
    message = payload.get("message")
    message = message.strip() if isinstance(message, str) else ""
    if len(message) > 500:
        raise HTTPException(status_code=400, detail="消息长度不能超过500字")
    history = sanitize_history(payload.get("history"))

    profile = parse_professor_profile(row, extend, date.today().year)
    messages = [{"role": "system", "content": build_professor_system_prompt(profile)}]
    messages.extend(history)
    if not message and not history:
        messages.append({"role": "user", "content": OPENING_TRIGGER})
        max_tokens = 600
    elif not message:
        raise HTTPException(status_code=400, detail="message 不能为空")
    else:
        messages.append({"role": "user", "content": message})
        max_tokens = 800

    try:
        reply = chat_completion(messages, max_tokens=max_tokens)
    except RuntimeError as e:  # unconfigured provider -> clear, actionable error
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"chat failed: {e}")
    if not reply or not reply.strip():
        raise HTTPException(status_code=502, detail="AI暂时无法回复，请重试")
    return {
        "reply": reply.strip(),
        "professor_name": row.get("store_name", ""),
        "professor_image": row.get("image", ""),
        "institution": profile["institution"],
        "title": profile["title"],
    }


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
