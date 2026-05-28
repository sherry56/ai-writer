"""
模型注册表。

每个模型有自己的 provider / api_key / base_url。优先读取:
1. 环境变量 MODELS_JSON (整段 JSON 字符串)
2. 文件 config/models.json
3. 兜底:从 .env 单模型 (WRITER_MODEL + LLM_PROVIDER + OPENAI_API_KEY/OPENAI_BASE_URL/ANTHROPIC_API_KEY)

文件格式:
{
  "default": "gpt-5.5",
  "models": [
    {
      "value": "gpt-5.5",          # 实际下发到 API 的 model 名
      "label": "GPT-5.5",          # 下拉显示名
      "provider": "openai",        # openai | anthropic
      "api_key": "sk-xxx",
      "base_url": "https://..."    # 仅 openai 兼容时需要;留空走官方
    },
    ...
  ]
}
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MODELS_FILE = ROOT / "config" / "models.json"


def _from_env_single() -> dict:
    """兼容旧的单模型 .env 配置。"""
    name = (os.getenv("WRITER_MODEL") or "gpt-5.5").strip()
    provider = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()
    entry = {
        "value": name,
        "label": name,
        "provider": provider,
    }
    if provider == "openai":
        entry["api_key"] = os.getenv("OPENAI_API_KEY", "")
        if base := os.getenv("OPENAI_BASE_URL"):
            entry["base_url"] = base
    else:
        entry["api_key"] = os.getenv("ANTHROPIC_API_KEY", "")
    return {"default": name, "models": [entry]}


def _load_raw() -> dict:
    if env := os.getenv("MODELS_JSON"):
        try:
            return json.loads(env)
        except Exception as e:  # noqa: BLE001
            logger.error("MODELS_JSON 解析失败,回退文件/env: %s", e)
    if MODELS_FILE.exists():
        try:
            return json.loads(MODELS_FILE.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.error("读取 %s 失败,回退 env: %s", MODELS_FILE, e)
    return _from_env_single()


def _normalize(entry: dict) -> dict:
    value = (entry.get("value") or entry.get("name") or "").strip()
    if not value:
        return {}
    provider = (entry.get("provider") or "openai").strip().lower()
    return {
        "value": value,
        "label": (entry.get("label") or value).strip(),
        "provider": provider,
        "api_key": (entry.get("api_key") or "").strip(),
        "base_url": (entry.get("base_url") or "").strip() or None,
    }


def load_registry() -> dict:
    """返回 {default: str, models: [normalized,...]}。"""
    raw = _load_raw() or {}
    models = []
    seen = set()
    for e in raw.get("models", []) or []:
        n = _normalize(e)
        if not n["value"] or n["value"] in seen:
            continue
        seen.add(n["value"])
        models.append(n)
    if not models:
        # fall back to env single
        models = [_normalize(m) for m in _from_env_single()["models"]]
    default = (raw.get("default") or "").strip() or models[0]["value"]
    if default not in {m["value"] for m in models}:
        default = models[0]["value"]
    return {"default": default, "models": models}


def list_models() -> list[dict]:
    """对外暴露的模型列表（只含 value/label,不泄露 api_key）。"""
    reg = load_registry()
    return [{"value": m["value"], "label": m["label"]} for m in reg["models"]]


def default_model() -> str:
    return load_registry()["default"]


def get_model_config(name: Optional[str] = None) -> dict:
    reg = load_registry()
    target = (name or "").strip() or reg["default"]
    for m in reg["models"]:
        if m["value"] == target:
            return m
    # 未注册的模型,按默认 provider/api_key 处理(便于临时填新名)
    fallback = next((m for m in reg["models"] if m["value"] == reg["default"]), reg["models"][0])
    return {**fallback, "value": target, "label": target}
