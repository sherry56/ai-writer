"""
写作 Skill — 从两个 markdown 文件实时加载,注入到大纲/初稿/修改 prompt。

- `config/skill.md`        :必须遵守的结构/排版/语感规则(每次都读,改完文件立刻生效)
- `data/articles/<ref>.md` :范文样本(默认是 doocs/手把手...md,可用 REFERENCE_SKILL_PATH 覆盖)

两个文件都不存在时,各自返回空串(不阻断生成,只是没注入)。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SKILL_FILE = ROOT / "config" / "skill.md"
DEFAULT_REF = ROOT / "data" / "articles" / "20260527-033700-手把手教你从设计工具到上线为自己的网址.md"

# 默认长度规则(可被 topic.target_length 覆盖)
DEFAULT_DRAFT_LENGTH = 1500
OUTLINE_TARGET_LENGTH = 500
HEADING_MAX_CHARS = 12


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("read %s failed: %s", path, e)
        return ""


def load_skill() -> str:
    """读取 config/skill.md,每次调用都重新读(支持热改)。"""
    path = Path(os.getenv("SKILL_FILE_PATH", SKILL_FILE)).resolve()
    text = _read(path)
    if not text:
        logger.warning("写作 Skill 文件不存在或为空: %s", path)
    return text


def load_reference_excerpt(max_chars: int = 4500) -> str:
    """读取范文,截到 max_chars。"""
    path = Path(os.getenv("REFERENCE_SKILL_PATH", DEFAULT_REF)).resolve()
    text = _read(path)
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n…(范文较长,以上为前部节选)"
    return text


def skill_block() -> str:
    text = load_skill()
    if not text:
        return ""
    return text + "\n\n(以上写作 Skill 优先级高于其它要求,必须遵守。)"


def reference_block() -> str:
    excerpt = load_reference_excerpt()
    if not excerpt:
        return ""
    return f"""## 范文(请贴合该节奏与排版,但不要照抄措辞)
{excerpt}
"""


def outline_length_block(target: Optional[int] = None) -> str:
    n = int(target or OUTLINE_TARGET_LENGTH)
    return (
        f"## 输出篇幅\n"
        f"- 大纲整体长度约 {n} 个汉字(±20%)\n"
        f"- 二级条目 4-6 条,每条标题最长 {HEADING_MAX_CHARS} 个汉字\n"
        f"- 每条 1-2 行说明,不写正文\n"
    )


def draft_length_block(target: Optional[int]) -> str:
    n = int(target or DEFAULT_DRAFT_LENGTH)
    return (
        f"## 输出篇幅\n"
        f"- 初稿正文约 {n} 个汉字(±15%),用户已明确字数则按用户字数为准\n"
        f"- 二级标题最长 {HEADING_MAX_CHARS} 个汉字,不允许折行\n"
        f"- 开篇 / 中间主体 / 总结三段比例约 1 : 3 : 1\n"
    )


_CN_DIGITS = "一二三四五六七八九十"
_SUMMARY_WORDS = ("小结", "总结", "总而言之", "结语", "写在最后", "最后")


def _strip_md_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[A-Za-z0-9_-]*\s*\n?", "", t)
        t = re.sub(r"\n?```\s*$", "", t)
    return t


def _serial_prefix(idx: int) -> str:
    if idx < len(_CN_DIGITS):
        return f"{_CN_DIGITS[idx]}、"
    return f"{idx + 1}、"


def _truncate(text: str, max_chars: int = HEADING_MAX_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= max_chars else text[:max_chars]


def _strip_existing_prefix(title: str) -> str:
    # 去掉已有的「一、」「1、」「1.」「一. 」前缀,统一交给后面补
    return re.sub(r"^([一二三四五六七八九十]{1,2}|\d{1,2})\s*[、.．]\s*", "", title).strip()


def normalize_draft(text: str) -> str:
    """对模型返回的初稿做硬性修齐:
    - 剥掉外层 ```markdown 围栏
    - 每个 `##` 主体段:
      * 自动加 `一、二、三、…` 序号前缀(以"总结/小结"结尾的最后一段不编号)
      * 标题截到 12 个字以内(去除原有前缀后再算)
      * 标题前补一行 `---` 分割线(若缺)
    - `###` 不动(允许的细分)
    """
    text = _strip_md_fence(text or "")
    if not text:
        return text

    lines = text.split("\n")
    h2_idxs = [i for i, ln in enumerate(lines) if re.match(r"^##\s+\S", ln)]
    if not h2_idxs:
        return text

    # 找出"总结型"最后一个 h2 — 不给它编号
    last_h2 = h2_idxs[-1]
    last_title = re.sub(r"^##\s+", "", lines[last_h2]).strip()
    last_is_summary = any(w in last_title for w in _SUMMARY_WORDS)

    out: list[str] = []
    serial = 0
    for i, line in enumerate(lines):
        m = re.match(r"^##\s+(.+?)\s*#*\s*$", line)
        if not m:
            out.append(line)
            continue
        title_raw = m.group(1).strip()
        bare = _strip_existing_prefix(title_raw)
        if i == last_h2 and last_is_summary:
            new_title = _truncate(bare or title_raw)
        else:
            new_title = f"{_serial_prefix(serial)}{_truncate(bare or title_raw, max_chars=HEADING_MAX_CHARS - 2)}"
            serial += 1
        # 确保前面有一行 ---
        # 找当前 out 最后一个非空行
        j = len(out) - 1
        while j >= 0 and out[j].strip() == "":
            j -= 1
        prev = out[j] if j >= 0 else ""
        if prev.strip() != "---":
            if out and out[-1].strip() != "":
                out.append("")
            out.append("---")
            out.append("")
        out.append(f"## {new_title}")
    return "\n".join(out).rstrip() + "\n"


def hard_check_block(*, for_draft: bool, target_chars: Optional[int] = None) -> str:
    """放在 user prompt 末尾的强约束检查清单,对弱指令跟随模型(如 deepseek)非常重要。"""
    n = int(target_chars or (DEFAULT_DRAFT_LENGTH if for_draft else OUTLINE_TARGET_LENGTH))
    common = [
        f"[ ] 主体段全部用 `##` 二级标题,**没有任何 `###` 用作主体段**(`###` 仅在二级下需要细分时出现)",
        f"[ ] 每个二级标题都是 `## 中文序数、xxx` 形式(一、二、三、…)",
        f"[ ] **每个二级标题含序号总长 ≤ {HEADING_MAX_CHARS} 个汉字**;太长立刻缩",
        f"[ ] **每个 `##` 之前必须有一行 `---` 分割线**(第一个 `##` 也要)",
        f"[ ] `#` 一级标题只出现一次,而且就是给定的选题标题",
    ]
    if for_draft:
        common += [
            f"[ ] 全文汉字数 ≈ {n}(±15%)",
            f"[ ] 开篇有具体钩子,结尾有「总结」段落收回开头痛点",
            f"[ ] 不出现「赋能 / 颠覆 / 重磅 / 小白 5 分钟」之类的营销腔",
        ]
    else:
        common += [
            f"[ ] 大纲整体 ≈ {n} 个汉字(±20%)",
            f"[ ] 4-6 条二级条目,顺序覆盖:开篇钩子 → 主体步骤 → 总结收束",
        ]
    items = "\n".join(common)
    return (
        "## 输出前自检(违反任一条都要改回再输出)\n"
        + items
        + "\n\n请直接输出最终内容,不要解释,不要包裹 ```markdown``` 围栏。"
    )
