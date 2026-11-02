from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ictlab.db import Base


class PeSummary(Base):
    __tablename__ = "pe_summaries"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    field: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    keywords: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    assets: Mapped[list["PeSummaryAsset"]] = relationship(back_populates="summary", cascade="all, delete-orphan", order_by="PeSummaryAsset.id")


class PeSummaryAsset(Base):
    __tablename__ = "pe_summary_assets"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    summary_id: Mapped[int] = mapped_column(ForeignKey("pe_summaries.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    conversion_status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_applicable")
    preview_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    lyrics: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    summary: Mapped[PeSummary] = relationship(back_populates="assets")
