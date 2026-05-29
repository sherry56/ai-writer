"""
初稿生成 prompt 与调用。
"""

from __future__ import annotations

import logging

from db import Topic
from writer.llm_client import chat, resolve_model
from writer.style_lib_loader import (
    banned_words_block,
    load_style_examples,
    style_preferences_block,
)
from writer.templates import get_template
from writer.writing_skill import (
    draft_length_block,
    hard_check_block,
    normalize_draft,
    reference_block,
    skill_block,
)

logger = logging.getLogger(__name__)


def build_draft_prompt(topic: Topic, outline: str) -> tuple[str, str]:
    tpl = get_template(topic.content_type)
    style_examples = load_style_examples()
    banned = banned_words_block()
    prefer = style_preferences_block()
    target_length = getattr(topic, "target_length", None)

    system = tpl.SYSTEM_PROMPT + ("\n\n" + skill_block() if skill_block() else "")

    user = f"""请基于以下大纲与素材,写一篇完整初稿(必须遵守上方写作 Skill)。

# 选题
- 标题:{topic.title}
- 内容类型:{tpl.DISPLAY_NAME}
- 作者备注与素材:
{topic.notes or "(无)"}

# 大纲(必须严格遵守)
{outline}

# 模板结构提示(供参考,Skill 优先级更高)
{tpl.STRUCTURE}

{draft_length_block(target_length)}

# 风格偏好
{prefer or "(沿用默认风格)"}

{banned}

{reference_block()}

# 风格样本(few-shot)
{style_examples}

# 输出要求
- markdown 格式,可直接用作公众号草稿
- 必须按 Skill 的结构骨架:开篇钩子 → 主体(多个二级标题) → 总结收束
- 二级标题最长 12 个汉字,中文序数前缀(一、二、…)
- 开头不要重复一级标题,直接进入钩子
- 不要在结尾写"以上"或自夸的总结性套话
- 不准确或无依据的数字必须标 [待核实],不要编造

{hard_check_block(for_draft=True, target_chars=target_length)}
"""
    return system, user


def generate_draft(topic: Topic, outline: str) -> dict:
    system, user = build_draft_prompt(topic, outline)
    model = resolve_model(getattr(topic, "model", None))
    logger.info("[draft] generate for topic #%s target_length=%s", topic.id, getattr(topic, "target_length", None))
    text = chat(system=system, user=user, max_tokens=8192, model=model)
    text = normalize_draft(text)
    return {"draft": text, "model": model}
