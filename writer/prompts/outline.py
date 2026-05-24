"""
大纲生成 prompt 与调用。
"""

from __future__ import annotations

import logging

from db import Topic
from writer.llm_client import chat, get_model
from writer.style_lib_loader import (
    banned_words_block,
    load_style_examples,
    style_preferences_block,
)
from writer.templates import get_template

logger = logging.getLogger(__name__)


def build_outline_prompt(topic: Topic) -> tuple[str, str]:
    tpl = get_template(topic.content_type)
    style_examples = load_style_examples()
    banned = banned_words_block()
    prefer = style_preferences_block()

    system = tpl.SYSTEM_PROMPT

    user = f"""为以下选题写一份大纲。

# 选题
- 标题：{topic.title}
- 内容类型：{tpl.DISPLAY_NAME}
- 作者备注与素材：
{topic.notes or "（无）"}

# 模板结构要求
{tpl.STRUCTURE}

# 风格偏好
{prefer or "（沿用默认风格）"}

{banned}

# 风格样本（few-shot）
{style_examples}

# 输出要求
- markdown 列表，{tpl.OUTLINE_ITEM_COUNT} 个一级条目
- 每个条目：一句话标题（粗体）+ 1-2 句要点说明
- 不要写正文，只给大纲
- 不要加序号 emoji
"""
    return system, user


def generate_outline(topic: Topic) -> dict:
    system, user = build_outline_prompt(topic)
    logger.info("[outline] generate for topic #%s", topic.id)
    text = chat(system=system, user=user, max_tokens=2048)
    return {"outline": text, "model": get_model()}
