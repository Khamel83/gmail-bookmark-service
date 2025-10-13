"""Database models for Gmail bookmark service."""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column

Base = declarative_base()


class Bookmark(Base):
    """Bookmark model representing a processed Gmail message."""

    __tablename__ = "bookmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(Text, nullable=True)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # URLs extracted from message
    urls: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    url_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Attachments
    attachments: Mapped[List[dict]] = mapped_column(JSON, nullable=False, default=list)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Message content (for reference)
    snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    gmail_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Processing status
    processing_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True
    )
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Deduplication
    message_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True, unique=True)

    # Metadata
    labels: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    is_unread: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<Bookmark(id={self.id}, gmail_message_id={self.gmail_message_id}, sender={self.sender_email})>"


class ProcessingState(Base):
    """Track processing state and configuration."""

    __tablename__ = "processing_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<ProcessingState(key={self.key}, value={self.value})>"


class FailedMessage(Base):
    """Track messages that failed processing for retry/debugging."""

    __tablename__ = "failed_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    raw_message_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<FailedMessage(gmail_message_id={self.gmail_message_id}, error_type={self.error_type})>"