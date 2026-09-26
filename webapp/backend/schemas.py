from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EntryType = Literal["DiaryEntry", "Worksheet", "Announcement"]


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("attachment name must not be blank")
        return value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("attachment url must not be blank")
        return value


class EntryBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_type: EntryType
    subject: str
    teacher: Optional[str] = None
    date: date
    summary: str
    label: str = "General"
    attachments: list[Attachment] = Field(default_factory=list)
    attachment_url: Optional[str] = None
    source_id: Optional[str] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_entry_type(cls, value):
        if isinstance(value, dict) and "entry_type" not in value and "type" in value:
            value = dict(value)
            value["entry_type"] = value.pop("type")
        return value

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("subject must not be blank")
        return value

    @field_validator("date", mode="before")
    @classmethod
    def validate_date(cls, value):
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            raise ValueError("date must not be blank")
        return value

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("source_id must not be blank")
        return value


class EntryCreate(EntryBase):
    pass


class Entry(EntryBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
