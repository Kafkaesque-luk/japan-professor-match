"""
Keyword expansion — faithful port of
``php傀儡/app/common/services/ai/KeywordExpansionService.php`` (no-profile path).

Expands a Chinese research interest into 5-10 Japanese academic terms via an LLM. The terms are
blended (top-5) into the embedding query to widen recall, exactly as production does. This step
is OPTIONAL: on any failure, or ``LLM_PROVIDER=none``, it degrades to ``[user_input]`` and the
match still runs on the raw input — never a hard dependency.

Providers: ``dashscope`` (Qwen, OpenAI-compatible endpoint) | ``openai`` | ``none``.
"""

from __future__ import annotations

import json
import re
from typing import List

import httpx

from ..config import Settings, get_settings

# Verbatim production system prompt (KeywordExpansionService::buildPromptWithoutProfile).
_SYSTEM_PROMPT = """你是一位专业的日本留学规划顾问，擅长将中文研究方向转换为日语专业术语。

任务：
1. 分析用户输入的中文关键词
2. 扩展为5-10个相关的日语专业术语
3. **按照与用户输入的相关性从高到低排序**
4. 返回JSON格式：{"keywords": ["日语关键词1", "日语关键词2", ...]}

要求：
- 关键词必须是日语（平假名、片假名或汉字）
- 关键词应该是学术/专业术语
- 关键词应该涵盖相关的研究领域
- 返回5-10个关键词
- **关键词数组必须按相关性从高到低排序（第一个最相关，最后一个最不相关）**
- 必须返回有效的JSON格式

排序规则：
1. 第1-3个关键词：与用户输入直接相关的核心术语（高相关性）
2. 第4-7个关键词：与用户输入间接相关的扩展术语（中相关性）
3. 第8-10个关键词：相关领域的补充术语（低相关性）"""

_DASHSCOPE_CHAT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
_OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"

_MAX_KEYWORDS = 10


def expand_keywords(user_input: str, settings: Settings | None = None) -> List[str]:
    """Return up to 10 Japanese keywords; degrades to ``[user_input]`` on any failure."""
    s = settings or get_settings()
    user_input = (user_input or "").strip()
    if not user_input:
        return []
    if s.llm_provider == "none":
        return [user_input]

    user_prompt = f"用户输入：{user_input}\n\n请扩展为日语专业术语关键词，并按相关性从高到低排序。"
    try:
        if s.llm_provider == "openai":
            content = _chat(_OPENAI_CHAT, s.openai_api_key, s.openai_llm_model, user_prompt)
        else:
            content = _chat(_DASHSCOPE_CHAT, s.qwen_api_key, s.qwen_model, user_prompt)
        keywords = _extract_keywords(content)
        return keywords if keywords else [user_input]
    except Exception:
        # Any failure (no key, network, bad JSON) -> degrade, never block the match.
        return [user_input]


def _chat(url: str, api_key: str, model: str, user_prompt: str) -> str:
    if not api_key:
        raise RuntimeError("LLM api key not configured")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 1000,
    }
    r = httpx.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _extract_keywords(content: str) -> List[str]:
    """Parse ``{"keywords": [...]}`` from the model output, tolerating code fences/prose."""
    if not content:
        return []
    text = content.strip()
    # Strip ```json fences if present, then grab the first {...} block.
    text = re.sub(r"^```[a-zA-Z]*", "", text).strip().strip("`").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    kws = data.get("keywords") if isinstance(data, dict) else None
    if not isinstance(kws, list):
        return []
    out = [str(k).strip() for k in kws if isinstance(k, (str, int, float)) and str(k).strip()]
    return out[:_MAX_KEYWORDS]
