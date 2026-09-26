from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from database import Base


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (
        Index(
            "entries_source_id_unique_idx",
            "source_id",
            unique=True,
            postgresql_where=text("source_id IS NOT NULL"),
        ),
        Index(
            "entries_date_updated_idx",
            "date",
            "updated_at",
            "created_at",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    entry_type = Column(String(32), nullable=False, index=True)
    subject = Column(Text, nullable=False, index=True)
    teacher = Column(Text, nullable=True)
    date = Column(Date, nullable=False)
    summary = Column(Text, nullable=False)
    label = Column(
        String(255),
        nullable=False,
        default="General",
        server_default=text("'General'"),
    )
    attachments = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    attachment_url = Column(Text, nullable=True)
    source_id = Column(Text, nullable=True, index=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
