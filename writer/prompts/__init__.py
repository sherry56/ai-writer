"""prompt 模板（大纲、初稿、修订）。"""

from writer.prompts.draft import build_draft_prompt, generate_draft
from writer.prompts.outline import build_outline_prompt, generate_outline
from writer.prompts.revise import build_revise_prompt, generate_revision

__all__ = [
    "build_outline_prompt",
    "generate_outline",
    "build_draft_prompt",
    "generate_draft",
    "build_revise_prompt",
    "generate_revision",
]
