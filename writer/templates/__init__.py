"""写作模板：公众号内容类型到 prompt 模板的映射。"""

from types import SimpleNamespace

from db import ContentType
from writer.templates import product_review, tutorial


BASE_SYSTEM = """你是一位 AI 领域中文公众号作者。
你的风格特点：
- 观点清晰，先给结论，再给依据
- 用具体场景、事实和例子说明问题
- 中文为主，专有名词保留英文（GPT、Claude、API 等）
- 避免假大空、避免营销口吻、避免无依据的数字
"""


def _template(
    *,
    name: str,
    display_name: str,
    focus: str,
    structure: str,
    item_count: str = "5-7",
    length_hint: str = "全文 1500-2500 字",
):
    return SimpleNamespace(
        NAME=name,
        DISPLAY_NAME=display_name,
        SYSTEM_PROMPT=f"{BASE_SYSTEM}\n你这次专写「{display_name}」类文章，重点是：{focus}\n",
        STRUCTURE=structure,
        DRAFT_LENGTH_HINT=length_hint,
        OUTLINE_ITEM_COUNT=item_count,
    )


news_analysis = _template(
    name="news_analysis",
    display_name="新闻/发布解读",
    focus="把最新事件讲清楚，解释它为什么重要，以及接下来可能影响谁。",
    structure="""## 结构骨架
1. **一句话发生了什么**：先交代事件和核心变化
2. **背景补齐**：这件事之前的上下文
3. **关键看点**：3-5 个变化点，每点配例子或影响
4. **对用户/行业的影响**：分别写短期和中期影响
5. **不确定性与局限**：哪些还需要观察
6. **结论**：给出克制判断""",
    item_count="6-8",
)

industry_analysis = _template(
    name="industry_analysis",
    display_name="行业趋势分析",
    focus="从多个信号归纳趋势，避免把单个新闻放大成结论。",
    structure="""## 结构骨架
1. **趋势判断**：一句话说清当前变化
2. **信号 1/2/3**：列出支撑判断的事实或现象
3. **为什么现在发生**：技术、成本、需求或政策因素
4. **受影响角色**：开发者、产品团队、公司、普通用户
5. **风险和反例**：哪些情况会让判断失效
6. **行动建议**：读者可以怎么跟进""",
    item_count="6-8",
)

tool_comparison = _template(
    name="tool_comparison",
    display_name="工具对比",
    focus="帮助读者在多个工具之间做选择，而不是堆功能清单。",
    structure="""## 结构骨架
1. **一句话选择建议**：先给适合谁
2. **对比维度**：价格、能力、易用性、生态、限制
3. **工具 A/B/C 分析**：每个工具写优点、短板、适用场景
4. **场景化推荐**：按个人、团队、开发者等角色推荐
5. **避坑提醒**：迁移成本、隐私、稳定性
6. **结论表格**：用简短表格收束""",
    item_count="6-8",
)

case_study = _template(
    name="case_study",
    display_name="案例拆解",
    focus="拆清楚一个具体案例的背景、做法、结果和可复用经验。",
    structure="""## 结构骨架
1. **案例概述**：谁做了什么，结果是什么
2. **问题背景**：原本卡在哪里
3. **关键做法**：3-5 个动作，尽量具体
4. **结果与代价**：收益、成本、限制都写
5. **可复用经验**：抽象成读者可执行的方法
6. **适用边界**：哪些场景不适合照搬""",
    item_count="5-7",
)

opinion = _template(
    name="opinion",
    display_name="观点评论",
    focus="表达明确判断，但要有证据、有边界，不写情绪化宣言。",
    structure="""## 结构骨架
1. **明确观点**：开头直接说判断
2. **为什么这样看**：2-4 个论据
3. **反方可能怎么说**：认真处理反对意见
4. **边界条件**：什么情况下观点不成立
5. **对读者的启发**：把判断落到行动或认知
6. **收束**：短结论，不喊口号""",
    item_count="5-7",
)

listicle = _template(
    name="listicle",
    display_name="清单盘点",
    focus="用清单降低阅读成本，每一项都要有选择理由和使用建议。",
    structure="""## 结构骨架
1. **清单标准**：说明为什么选这些项
2. **条目 1-N**：每项包含定位、亮点、适合谁、注意事项
3. **快速对比**：用表格或分组帮助选择
4. **优先推荐**：给不同场景下的首选
5. **结尾提醒**：说明更新频率或选择边界""",
    item_count="6-10",
)

other = _template(
    name="other",
    display_name="其它",
    focus="根据标题和备注自行选择最合适的文章结构，保持公众号可读性。",
    structure="""## 结构骨架
1. **开头**：快速说明主题和读者收益
2. **正文结构**：根据素材自动组织 4-6 个一级段落
3. **例子或场景**：至少加入 1-2 个具体例子
4. **限制与注意事项**：避免绝对化
5. **结论**：给出清晰 take-away""",
    item_count="5-7",
)


# content_type → 模板模块
TEMPLATES = {
    ContentType.TUTORIAL: tutorial,
    ContentType.PRODUCT_REVIEW: product_review,
    ContentType.NEWS_ANALYSIS: news_analysis,
    ContentType.INDUSTRY_ANALYSIS: industry_analysis,
    ContentType.TOOL_COMPARISON: tool_comparison,
    ContentType.CASE_STUDY: case_study,
    ContentType.OPINION: opinion,
    ContentType.LISTICLE: listicle,
    ContentType.OTHER: other,
}


def get_template(content_type: ContentType):
    """按 ContentType 取模板模块（含 SYSTEM_PROMPT / STRUCTURE / 长度提示）。"""
    try:
        key = ContentType(content_type)
    except ValueError:
        key = ContentType.OTHER
    return TEMPLATES[key]


__all__ = [
    "TEMPLATES",
    "get_template",
    "tutorial",
    "product_review",
    "news_analysis",
    "industry_analysis",
    "tool_comparison",
    "case_study",
    "opinion",
    "listicle",
    "other",
]
