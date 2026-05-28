"""写作层：模板 + prompt + 风格库。"""

from writer.prompts import (
    build_draft_prompt,
    build_outline_prompt,
    build_revise_prompt,
    generate_draft,
    generate_outline,
    generate_revision,
)
from writer.style_lib_loader import (
    StyleConfig,
    banned_words_block,
    load_style_config,
    load_style_examples,
    style_preferences_block,
)
from writer.templates import TEMPLATES, get_template

__all__ = [
    "TEMPLATES",
    "get_template",
    "StyleConfig",
    "load_style_config",
    "load_style_examples",
    "banned_words_block",
    "style_preferences_block",
    "build_outline_prompt",
    "generate_outline",
    "build_draft_prompt",
    "generate_draft",
    "build_revise_prompt",
    "generate_revision",
]
