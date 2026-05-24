"""prompt 模板（大纲、初稿等）。"""

from writer.prompts.draft import build_draft_prompt, generate_draft
from writer.prompts.outline import build_outline_prompt, generate_outline

__all__ = [
    "build_outline_prompt",
    "generate_outline",
    "build_draft_prompt",
    "generate_draft",
]
