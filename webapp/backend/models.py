from sqlalchemy import Column, Integer, String, Date
from database import Base

class Entry(Base):
    __tablename__ = "entries"

    id = Column(Integer, primary_key=True, index=True)
    entry_type = Column(String, index=True) # e.g., "DiaryEntry", "Worksheet", "Announcement"
    subject = Column(String, index=True)
    teacher = Column(String)
    date = Column(Date)
    summary = Column(String)
    attachment_url = Column(String, nullable=True)
