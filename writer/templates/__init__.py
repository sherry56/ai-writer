"""写作模板：上手教程型、模型/产品解读型。"""

from db import ContentType
from writer.templates import product_review, tutorial

# content_type → 模板模块
TEMPLATES = {
    ContentType.TUTORIAL: tutorial,
    ContentType.PRODUCT_REVIEW: product_review,
}


def get_template(content_type: ContentType):
    """按 ContentType 取模板模块（含 SYSTEM_PROMPT / STRUCTURE / 长度提示）。"""
    if content_type not in TEMPLATES:
        raise ValueError(f"未知 content_type：{content_type}")
    return TEMPLATES[content_type]


__all__ = ["TEMPLATES", "get_template", "tutorial", "product_review"]
