import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ictlab.models import NewsArticle


CATEGORY_AI = "AI"
CATEGORY_NETWORK = "통신·네트워크"
CATEGORY_SECURITY = "정보보안"
CATEGORY_POLICY = "정책·산업"
CATEGORY_HARDWARE = "반도체·하드웨어"
CATEGORY_OTHER = "기타"
CATEGORY_INTERNATIONAL = "해외"

CATEGORY_OPTIONS = (
    CATEGORY_AI,
    CATEGORY_NETWORK,
    CATEGORY_SECURITY,
    CATEGORY_POLICY,
    CATEGORY_HARDWARE,
    CATEGORY_OTHER,
    CATEGORY_INTERNATIONAL,
)

INTERNATIONAL_SOURCE_NAMES = frozenset({"TechCrunch"})

# The tuple order is the deterministic tie-break priority.
KEYWORD_RULES = (
    (
        CATEGORY_SECURITY,
        (
            "보안",
            "해킹",
            "해커",
            "랜섬웨어",
            "취약점",
            "악성코드",
            "사이버",
            "개인정보",
            "피싱",
            "암호",
            "침해",
            "제로데이",
        ),
    ),
    (
        CATEGORY_HARDWARE,
        (
            "반도체",
            "파운드리",
            "팹리스",
            "웨이퍼",
            "hbm",
            "d램",
            "낸드",
            "메모리",
            "gpu",
            "cpu",
            "칩셋",
        ),
    ),
    (
        CATEGORY_NETWORK,
        (
            "통신",
            "네트워크",
            "이동통신",
            "5g",
            "6g",
            "와이파이",
            "위성통신",
            "광통신",
            "주파수",
            "기지국",
            "라우터",
        ),
    ),
    (
        CATEGORY_AI,
        (
            "ai",
            "인공지능",
            "생성형",
            "llm",
            "머신러닝",
            "딥러닝",
            "챗gpt",
            "chatgpt",
            "거대언어모델",
        ),
    ),
    (
        CATEGORY_POLICY,
        (
            "정책",
            "정부",
            "과기정통부",
            "과학기술정보통신부",
            "규제",
            "법안",
            "산업",
            "시장",
            "투자",
            "기업",
            "스타트업",
            "사업",
            "수출",
            "공급망",
        ),
    ),
)


def classify_article(title: str, content: str | None, source_name: str) -> str:
    """Classify an article using its source and deterministic keyword scores."""
    if source_name in INTERNATIONAL_SOURCE_NAMES:
        return CATEGORY_INTERNATIONAL

    text = f"{title}\n{content or ''}".lower()
    best_category = CATEGORY_OTHER
    best_score = 0
    for category, keywords in KEYWORD_RULES:
        score = sum(_contains_keyword(text, keyword) for keyword in keywords)
        if score > best_score:
            best_category = category
            best_score = score
    return best_category


def classify_existing_articles(session: Session) -> tuple[int, Counter[str]]:
    """Classify all stored articles and return updated and category counts."""
    updated = 0
    counts: Counter[str] = Counter()
    for article in session.scalars(select(NewsArticle)):
        category = classify_article(article.title, article.content, article.source_name)
        counts[category] += 1
        if article.category != category:
            article.category = category
            updated += 1
    session.commit()
    return updated, counts


def _contains_keyword(text: str, keyword: str) -> bool:
    lowered = keyword.lower()
    if lowered.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return lowered in text
