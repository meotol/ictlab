from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ictlab.db import Base


CONTENT_TYPE_NEWS_BRIEFING = "news_briefing"
CONTENT_TYPE_PE_QA = "pe_qa"
CONTENT_TYPE_LABELS = {
    CONTENT_TYPE_NEWS_BRIEFING: "ICT 뉴스 브리핑",
    CONTENT_TYPE_PE_QA: "정보통신기술사 문제 및 답안",
}


class Content(Base):
    """Long-form content entered manually in the administrator screen."""

    __tablename__ = "contents"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    authored_at: Mapped[date] = mapped_column(Date, nullable=False)
    is_published: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
