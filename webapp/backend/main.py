from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List

import models, schemas
from database import SessionLocal, engine

# Create the database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="MCB Backend API")

# Configure CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/api/entries", response_model=List[schemas.Entry])
def read_entries(skip: int = 0, limit: int = 100, entry_type: str = None, db: Session = Depends(get_db)):
    query = db.query(models.Entry)
    if entry_type:
        query = query.filter(models.Entry.entry_type == entry_type)
    entries = query.offset(skip).limit(limit).all()
    return entries

@app.post("/api/entries", response_model=schemas.Entry)
def create_entry(entry: schemas.EntryCreate, db: Session = Depends(get_db)):
    # Use model_dump for Pydantic v2, fallback to dict for v1
    entry_data = entry.model_dump() if hasattr(entry, "model_dump") else entry.dict()
    
    # Check for duplicate entry (matching type, date, subject, and summary)
    db_entry = db.query(models.Entry).filter(
        models.Entry.entry_type == entry_data["entry_type"],
        models.Entry.date == entry_data["date"],
        models.Entry.subject == entry_data["subject"],
        models.Entry.summary == entry_data["summary"]
    ).first()
    
    if db_entry:
        # Update existing
        for key, value in entry_data.items():
            setattr(db_entry, key, value)
    else:
        db_entry = models.Entry(**entry_data)
        db.add(db_entry)
        
    db.commit()
    db.refresh(db_entry)
    return db_entry

