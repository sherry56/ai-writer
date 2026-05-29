"""
LLM 调用统一入口。

每个模型独立配置 provider / api_key / base_url(见 writer.model_config)。
调用 chat(model=...) 会按该模型的配置去发起请求。
"""

from __future__ import annotations

import logging

from writer.model_config import default_model, get_model_config

logger = logging.getLogger(__name__)


def get_model() -> str:
    return default_model()


def resolve_model(model: str | None = None) -> str:
    value = (model or "").strip()
    return value or default_model()


def chat(*, system: str, user: str, max_tokens: int = 4096, model: str | None = None) -> str:
    """按所选模型路由到对应 provider + api_key + base_url。返回纯文本。"""
    cfg = get_model_config(model)
    provider = (cfg.get("provider") or "openai").lower()
    target = cfg["value"]
    if provider == "anthropic":
        return _anthropic_chat(system=system, user=user, max_tokens=max_tokens, cfg=cfg, model=target)
    if provider == "openai":
        return _openai_chat(system=system, user=user, max_tokens=max_tokens, cfg=cfg, model=target)
    raise ValueError(f"未知 provider: {provider}(仅支持 anthropic / openai)")


def _anthropic_chat(*, system: str, user: str, max_tokens: int, cfg: dict, model: str) -> str:
    import anthropic

    api_key = cfg.get("api_key")
    if not api_key:
        raise RuntimeError(f"模型 {model} 未配置 api_key")
    base_url = cfg.get("base_url") or None  # None → 走 anthropic 官方
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    logger.info("[llm] anthropic %s base_url=%s", model, base_url or "default")
    client = anthropic.Anthropic(**kwargs)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()


def _openai_chat(*, system: str, user: str, max_tokens: int, cfg: dict, model: str) -> str:
    from openai import OpenAI

    api_key = cfg.get("api_key")
    if not api_key:
        raise RuntimeError(f"模型 {model} 未配置 api_key")
    base_url = cfg.get("base_url") or None
    logger.info("[llm] openai-compatible %s base_url=%s", model, base_url or "default")
    # 一些第三方网关(如 packyapi)拒绝带 "OpenAI/Python" 的 UA,覆盖掉。
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers={"User-Agent": "ai-writer/0.4"},
    )
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip()
