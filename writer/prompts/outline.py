"""
大纲生成 prompt 与调用。
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
    OUTLINE_TARGET_LENGTH,
    hard_check_block,
    outline_length_block,
    reference_block,
    skill_block,
)

logger = logging.getLogger(__name__)


def build_outline_prompt(topic: Topic) -> tuple[str, str]:
    tpl = get_template(topic.content_type)
    style_examples = load_style_examples()
    banned = banned_words_block()
    prefer = style_preferences_block()
    target_length = OUTLINE_TARGET_LENGTH  # 大纲固定 ~500 字

    system = tpl.SYSTEM_PROMPT + ("\n\n" + skill_block() if skill_block() else "")

    user = f"""为以下选题写一份大纲(必须遵守上方写作 Skill)。

# 选题
- 标题：{topic.title}
- 内容类型：{tpl.DISPLAY_NAME}
- 作者备注与素材：
{topic.notes or "（无）"}

# 模板结构提示(供参考,Skill 优先级更高)
{tpl.STRUCTURE}

{outline_length_block(target_length)}

# 风格偏好
{prefer or "（沿用默认风格）"}

{banned}

{reference_block()}

# 风格样本(few-shot)
{style_examples}

# 输出要求
- markdown 列表,4-6 个一级条目(对应 4-6 个二级标题)
- 每个条目:一句话二级标题(粗体,**最长 12 个汉字**) + 1-2 句要点说明
- 必须含「开篇钩子」「主体步骤(若干)」「总结收束」三个段落骨架
- 不要写正文,只给大纲
- 不要加序号 emoji

{hard_check_block(for_draft=False, target_chars=target_length)}
"""
    return system, user


def generate_outline(topic: Topic) -> dict:
    system, user = build_outline_prompt(topic)
    model = resolve_model(getattr(topic, "model", None))
    logger.info("[outline] generate for topic #%s", topic.id)
    text = chat(system=system, user=user, max_tokens=2048, model=model)
    return {"outline": text, "model": model}
