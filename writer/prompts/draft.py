"""
初稿生成 prompt 与调用。

输入：Topic + outline
输出：markdown 初稿
"""

from __future__ import annotations

import logging
import os

from db import Topic
from writer.style_lib_loader import (
    banned_words_block,
    load_style_examples,
    style_preferences_block,
)
from writer.templates import get_template

logger = logging.getLogger(__name__)


def build_draft_prompt(topic: Topic, outline: str) -> tuple[str, str]:
    tpl = get_template(topic.content_type)
    style_examples = load_style_examples()
    banned = banned_words_block()
    prefer = style_preferences_block()

    system = tpl.SYSTEM_PROMPT

    user = f"""请基于以下大纲与素材，写一篇完整初稿。

# 选题
- 标题：{topic.title}
- 内容类型：{tpl.DISPLAY_NAME}
- 作者备注与素材：
{topic.notes or "（无）"}

# 大纲（必须严格遵守）
{outline}

# 模板结构提示
{tpl.STRUCTURE}

# 风格偏好
{prefer or "（沿用默认风格）"}

{banned}

# 风格样本（few-shot）
{style_examples}

# 输出要求
- markdown 格式，可直接用作公众号草稿
- {tpl.DRAFT_LENGTH_HINT}
- 开头不要重复标题，直接进入钩子
- 不要在结尾写"以上"或自夸的总结性套话
- 不准确或无依据的数字必须标 [待核实]，不要编造
"""
    return system, user


def generate_draft(topic: Topic, outline: str) -> dict:
    import anthropic

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("未设置 ANTHROPIC_API_KEY，请在 .env 中配置")

    model = os.getenv("WRITER_MODEL", "claude-opus-4-7")
    system, user = build_draft_prompt(topic, outline)

    logger.info("[draft] calling Claude (%s) for topic #%s", model, topic.id)
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
    return {"draft": text, "model": model}
