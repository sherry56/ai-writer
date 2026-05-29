"""
基于用户指令对初稿进行局部修改。

输入：Topic + outline + 当前初稿 + 用户指令
输出：修改后的完整初稿（markdown）
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
from writer.writing_skill import draft_length_block, hard_check_block, normalize_draft, skill_block

logger = logging.getLogger(__name__)


def build_revise_prompt(topic: Topic, outline: str, draft: str, instruction: str) -> tuple[str, str]:
    tpl = get_template(topic.content_type)
    style_examples = load_style_examples()
    banned = banned_words_block()
    prefer = style_preferences_block()
    target_length = getattr(topic, "target_length", None)

    system = tpl.SYSTEM_PROMPT + ("\n\n" + skill_block() if skill_block() else "")

    user = f"""请根据用户的修改指令，对下面的初稿做有针对性的改写。
- 只改动指令要求的部分，其余段落保持原文不动（包括标点、用词、断行）。
- 输出完整的修改后初稿，markdown 格式，不要附加解释、不要写"修改说明"。

# 选题
- 标题：{topic.title}
- 内容类型：{tpl.DISPLAY_NAME}
- 作者备注与素材：
{topic.notes or "（无）"}

# 大纲（参考结构，可在修改时对齐）
{outline or "（无）"}

# 当前初稿
{draft}

# 用户的修改指令
{instruction}

# 风格偏好
{prefer or "（沿用默认风格）"}

{banned}

# 风格样本（few-shot）
{style_examples}

{draft_length_block(target_length)}

# 输出要求
- 只输出修改后的完整初稿正文(markdown)
- 必须保持 Skill 规定的开篇钩子 → 主体 → 总结收束骨架
- 二级标题最长 12 个汉字
- 开头不要重复一级标题,直接进入正文
- 不准确或无依据的数字必须标 [待核实],不要编造

{hard_check_block(for_draft=True, target_chars=target_length)}
"""
    return system, user


def generate_revision(topic: Topic, outline: str, draft: str, instruction: str) -> dict:
    if not draft or not draft.strip():
        raise ValueError("当前没有初稿可修改")
    if not instruction or not instruction.strip():
        raise ValueError("请填写修改指令")
    system, user = build_revise_prompt(topic, outline or "", draft, instruction.strip())
    model = resolve_model(getattr(topic, "model", None))
    logger.info("[revise] generate for topic #%s instruction=%r", topic.id, instruction[:60])
    text = chat(system=system, user=user, max_tokens=8192, model=model)
    text = normalize_draft(text)
    return {"draft": text, "model": model}
