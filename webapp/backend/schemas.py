from pydantic import BaseModel, ConfigDict
from datetime import date
from typing import Optional

class EntryBase(BaseModel):
    entry_type: str
    subject: str
    teacher: str
    date: date
    summary: str
    attachment_url: Optional[str] = None

class EntryCreate(EntryBase):
    pass

class Entry(EntryBase):
    id: int
    
    model_config = ConfigDict(from_attributes=True)
