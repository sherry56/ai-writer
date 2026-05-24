"""
风格库加载器。

- 加载 config/style.yaml（禁用词、tone、prefer）
- 加载 data/style_lib/*.md 作为 few-shot 示例
- 风格库为空时返回 fallback 描述
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STYLE_YAML = ROOT / "config" / "style.yaml"
DEFAULT_STYLE_LIB_DIR = os.getenv("STYLE_LIB_DIR", "data/style_lib")

# 风格库为空时使用的 fallback few-shot 描述
FALLBACK_STYLE_EXAMPLES = """（暂无样本文章，请按以下风格描述写作：）
- 短句优先，避免排比堆砌
- 多用具体数字、产品名、操作步骤
- 第二人称口吻（"你"），避免"我们"开篇
- 避免空泛形容词与营销口吻
- 中文为主，专有名词保留英文（GPT、Claude、API 等）
"""


@dataclass
class StyleConfig:
    tone: list[str] = field(default_factory=list)
    banned_words: list[str] = field(default_factory=list)
    prefer: list[str] = field(default_factory=list)
    style_lib_dir: str = DEFAULT_STYLE_LIB_DIR


def load_style_config() -> StyleConfig:
    """从 config/style.yaml 加载。"""
    if not STYLE_YAML.exists():
        return StyleConfig()
    with open(STYLE_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return StyleConfig(
        tone=data.get("tone", []) or [],
        banned_words=data.get("banned_words", []) or [],
        prefer=data.get("prefer", []) or [],
        style_lib_dir=data.get("style_lib_dir", DEFAULT_STYLE_LIB_DIR),
    )


def load_style_examples(max_files: int = 3, max_chars_per_file: int = 3000) -> str:
    """
    加载 data/style_lib/ 下的 .md 文件，拼成 few-shot 字符串。
    返回 fallback 描述当目录为空。
    """
    cfg = load_style_config()
    lib_dir = ROOT / cfg.style_lib_dir
    if not lib_dir.exists():
        return FALLBACK_STYLE_EXAMPLES

    md_files = sorted(lib_dir.glob("*.md"))[:max_files]
    if not md_files:
        return FALLBACK_STYLE_EXAMPLES

    chunks: list[str] = []
    for p in md_files:
        try:
            text = p.read_text(encoding="utf-8")[:max_chars_per_file]
        except Exception as e:  # noqa: BLE001
            logger.warning("读取风格样本失败 %s: %s", p, e)
            continue
        chunks.append(f"--- 样本：{p.name} ---\n{text}")
    return "\n\n".join(chunks) if chunks else FALLBACK_STYLE_EXAMPLES


def banned_words_block() -> str:
    """拼成 prompt 里的禁用词提示段。"""
    cfg = load_style_config()
    if not cfg.banned_words:
        return ""
    words = "、".join(cfg.banned_words)
    return f"严格禁用以下词汇（包括同义夸张表达）：{words}"


def style_preferences_block() -> str:
    """拼成 prompt 里的偏好描述段。"""
    cfg = load_style_config()
    lines: list[str] = []
    if cfg.tone:
        lines.append("整体语气：" + "、".join(cfg.tone))
    if cfg.prefer:
        lines.append("写作偏好：")
        lines.extend(f"  - {p}" for p in cfg.prefer)
    return "\n".join(lines)
