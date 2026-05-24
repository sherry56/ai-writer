"""
LLM 调用统一入口。

根据 LLM_PROVIDER 环境变量分发到 Anthropic 或 OpenAI 兼容接口。
- LLM_PROVIDER=anthropic  -> anthropic SDK
- LLM_PROVIDER=openai     -> openai SDK（支持自定义 base_url，可对接 DeepSeek/Moonshot/Ollama 等）
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def get_provider() -> str:
    return os.getenv("LLM_PROVIDER", "anthropic").strip().lower()


def get_model() -> str:
    return os.getenv("WRITER_MODEL", "claude-opus-4-7")


def chat(*, system: str, user: str, max_tokens: int = 4096) -> str:
    """统一对话调用。返回纯文本。"""
    provider = get_provider()
    model = get_model()
    if provider == "anthropic":
        return _anthropic_chat(system=system, user=user, max_tokens=max_tokens, model=model)
    if provider == "openai":
        return _openai_chat(system=system, user=user, max_tokens=max_tokens, model=model)
    raise ValueError(f"未知 LLM_PROVIDER: {provider}（仅支持 anthropic / openai）")


def _anthropic_chat(*, system: str, user: str, max_tokens: int, model: str) -> str:
    import anthropic

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("未设置 ANTHROPIC_API_KEY")

    logger.info("[llm] anthropic %s", model)
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()


def _openai_chat(*, system: str, user: str, max_tokens: int, model: str) -> str:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 OPENAI_API_KEY")

    base_url = os.getenv("OPENAI_BASE_URL") or None  # None -> 默认 OpenAI 官方
    logger.info("[llm] openai-compatible %s (base_url=%s)", model, base_url or "default")
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip()
