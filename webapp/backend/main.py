import html
import json
import re
from typing import List, Optional
from urllib.parse import unquote, urljoin, urlparse

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
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
def read_entries(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1),
    entry_type: Optional[schemas.EntryType] = None,
    source_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(models.Entry).order_by(
        models.Entry.date.desc(),
        models.Entry.updated_at.desc(),
        models.Entry.created_at.desc(),
        models.Entry.id.desc(),
    )
    if entry_type is not None:
        query = query.filter(models.Entry.entry_type == entry_type)
    if source_id is not None:
        query = query.filter(models.Entry.source_id == source_id)
    return query.offset(skip).limit(limit).all()


def _clean_text(value):
    if value is None:
        return ""
    return " ".join(str(value).split())


def _attachment_url(value):
    if not isinstance(value, str):
        return None
    value = html.unescape(_clean_text(value))
    if not value:
        return None
    low = value.lower()
    if low.startswith(("javascript:", "void", "#", "mailto:", "tel:", "data:")):
        return None
    if low.startswith("//"):
        value = "https:" + value
    elif not low.startswith(("http://", "https://")):
        if value.startswith("~/"):
            value = value[1:]
        value = urljoin("https://rainbow.myclassboard.com/StudentERP/", value)
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _attachment_filename(value):
    return unquote(urlparse(value).path).rsplit("/", 1)[-1]


def _is_icon_url(value):
    path = value.lower().split("?", 1)[0].split("#", 1)[0]
    return bool(re.search(r"(?:^|[/_-])(?:favicon|icon|logo)(?:[/_.-]|$)", path))


def _is_generic_attachment_name(value):
    return _clean_text(value).lower().rstrip(":") in {
        "",
        "attachment",
        "attachments",
        "file",
        "download",
        "view file",
    }


def _attachment_item(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif hasattr(value, "dict") and not isinstance(value, dict):
        value = value.dict()
    if isinstance(value, str):
        value = {"url": value}
    if not isinstance(value, dict):
        return None
    url = _attachment_url(value.get("url") or value.get("href") or value.get("path"))
    if url is None or _is_icon_url(url):
        return None
    name = _clean_text(value.get("name") or value.get("filename") or "")
    if _is_generic_attachment_name(name):
        name = ""
    return {"name": name or _attachment_filename(url) or "Attachment", "url": url}


def _normalize_attachments(value):
    if value is None or value == "":
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") or text.startswith("{"):
            try:
                value = json.loads(text)
            except (TypeError, ValueError):
                value = [{"url": text}]
        else:
            value = [{"url": text}]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    seen = set()
    for item in value:
        attachment = _attachment_item(item)
        if attachment is None or attachment["url"] in seen:
            continue
        seen.add(attachment["url"])
        result.append(attachment)
    return result


def _merge_attachments(*values):
    merged = []
    for value in values:
        merged.extend(_normalize_attachments(value))
    return _normalize_attachments(merged)


def _serialize_attachments(value):
    attachments = _normalize_attachments(value)
    if not attachments:
        return None
    return json.dumps(attachments, ensure_ascii=False, separators=(",", ":"))


def _prepare_entry_data(entry_data):
    data = dict(entry_data)
    data.pop("updated_at", None)
    incoming = []
    if "attachments" in data:
        incoming.extend(_normalize_attachments(data.get("attachments")))
    if "attachment_url" in data:
        incoming.extend(_normalize_attachments(data.get("attachment_url")))
    attachments = _normalize_attachments(incoming)
    data["attachments"] = attachments
    data["attachment_url"] = _serialize_attachments(attachments)
    source_id = data.get("source_id")
    if isinstance(source_id, str):
        data["source_id"] = source_id.strip() or None
    return data


def _row_attachments(db_entry):
    return _merge_attachments(db_entry.attachments, db_entry.attachment_url)


def _source_entries(db, source_id):
    if source_id is None:
        return []
    return (
        db.query(models.Entry)
        .filter(models.Entry.source_id == source_id)
        .order_by(
            models.Entry.updated_at.desc(),
            models.Entry.created_at.desc(),
            models.Entry.id.desc(),
        )
        .all()
    )


def _content_entries(db, entry_data):
    return (
        db.query(models.Entry)
        .filter(
            models.Entry.entry_type == entry_data["entry_type"],
            models.Entry.date == entry_data["date"],
            models.Entry.subject == entry_data["subject"],
            models.Entry.summary == entry_data["summary"],
        )
        .order_by(
            models.Entry.updated_at.desc(),
            models.Entry.created_at.desc(),
            models.Entry.id.desc(),
        )
        .all()
    )


def _assign_entry_data(db_entry, entry_data, attachments):
    for key, value in entry_data.items():
        if key in {"attachments", "attachment_url"}:
            continue
        if key == "source_id" and value is None and db_entry.source_id is not None:
            continue
        setattr(db_entry, key, value)
    db_entry.attachments = attachments
    db_entry.attachment_url = _serialize_attachments(attachments)


def apply_entry_data(db_entry, entry_data):
    data = _prepare_entry_data(entry_data)
    attachments = _merge_attachments(_row_attachments(db_entry), data["attachments"])
    _assign_entry_data(db_entry, data, attachments)


def locate_entry(db, entry_data):
    data = _prepare_entry_data(entry_data)
    source_entries = _source_entries(db, data.get("source_id"))
    if source_entries:
        return source_entries[0]
    content_entries = _content_entries(db, data)
    return content_entries[0] if content_entries else None


def upsert_entry(db, entry_data):
    data = _prepare_entry_data(entry_data)
    for attempt in range(3):
        source_entries = _source_entries(db, data.get("source_id"))
        content_entries = _content_entries(db, data)
        db_entry = source_entries[0] if source_entries else (
            content_entries[0] if content_entries else None
        )
        conflicts = []
        conflict_ids = set()
        if db_entry is not None:
            for candidate in source_entries + content_entries:
                if candidate.id == db_entry.id or candidate.id in conflict_ids:
                    continue
                conflicts.append(candidate)
                conflict_ids.add(candidate.id)

        try:
            if db_entry is None:
                db_entry = models.Entry(**data)
                db.add(db_entry)
            else:
                for conflict in conflicts:
                    db.delete(conflict)
                if conflicts:
                    db.flush()
                attachments = _merge_attachments(
                    _row_attachments(db_entry),
                    *[_row_attachments(conflict) for conflict in conflicts],
                    data["attachments"],
                )
                _assign_entry_data(db_entry, data, attachments)
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt < 2:
                continue
            raise
        except Exception:
            db.rollback()
            raise

        db.refresh(db_entry)
        return db_entry


@app.post("/api/entries", response_model=schemas.Entry)
def create_entry(entry: schemas.EntryCreate, db: Session = Depends(get_db)):
    # Use model_dump for Pydantic v2, fallback to dict for v1
    entry_data = entry.model_dump() if hasattr(entry, "model_dump") else entry.dict()
    entry_data.pop("updated_at", None)

    return upsert_entry(db, entry_data)
