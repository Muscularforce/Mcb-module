import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).parent))

import models


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import main as backend_main

    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(test_engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    backend_main.app.dependency_overrides[backend_main.get_db] = override_get_db
    with TestClient(backend_main.app) as test_client:
        yield test_client
    backend_main.app.dependency_overrides.clear()
    models.Base.metadata.drop_all(test_engine)
    test_engine.dispose()


def payload(**overrides):
    data = {
        "entry_type": "DiaryEntry",
        "subject": "Mathematics",
        "teacher": "Ms Rao",
        "date": "2026-06-03",
        "summary": "Complete the worksheet.",
        "label": "Mathematics",
        "attachments": [
            {"name": "worksheet.pdf", "url": "https://example.test/worksheet.pdf"}
        ],
        "attachment_url": "https://example.test/worksheet.pdf",
        "source_id": "source-1",
    }
    data.update(overrides)
    return data


def test_source_id_reuse_updates_one_row(client):
    first = client.post("/api/entries", json=payload())
    second = client.post(
        "/api/entries",
        json=payload(
            subject="Mathematics revised",
            summary="Complete the revised worksheet.",
            attachments=[],
            attachment_url=None,
        ),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["subject"] == "Mathematics revised"
    assert second.json()["attachments"] == first.json()["attachments"]
    assert second.json()["attachment_url"] == first.json()["attachment_url"]
    assert len(client.get("/api/entries").json()) == 1


def test_source_update_merges_exact_content_conflict(client):
    first_attachment = {"name": "old.pdf", "url": "https://example.test/old.pdf"}
    conflicting_attachment = {
        "name": "conflicting.pdf",
        "url": "https://example.test/conflicting.pdf",
    }
    incoming_attachment = {
        "name": "incoming.pdf",
        "url": "https://example.test/incoming.pdf",
    }
    first = client.post(
        "/api/entries",
        json=payload(
            source_id="source-a",
            subject="Mathematics",
            summary="Original content.",
            attachments=[first_attachment],
            attachment_url=json.dumps([first_attachment]),
        ),
    )
    conflicting = client.post(
        "/api/entries",
        json=payload(
            source_id="source-b",
            subject="Physics",
            summary="Conflicting content.",
            attachments=[conflicting_attachment],
            attachment_url=json.dumps([conflicting_attachment]),
        ),
    )
    updated = client.post(
        "/api/entries",
        json=payload(
            source_id="source-a",
            subject="Physics",
            summary="Conflicting content.",
            attachments=[incoming_attachment],
            attachment_url=json.dumps([incoming_attachment]),
        ),
    )

    assert first.status_code == 200
    assert conflicting.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["id"] == first.json()["id"]
    assert updated.json()["source_id"] == "source-a"
    assert updated.json()["attachments"] == [
        first_attachment,
        conflicting_attachment,
        incoming_attachment,
    ]
    assert updated.json()["attachment_url"] == json.dumps(
        updated.json()["attachments"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    rows = client.get("/api/entries").json()
    assert len(rows) == 1
    assert rows[0]["id"] == first.json()["id"]
    assert rows[0]["attachments"] == updated.json()["attachments"]


def test_legacy_upsert_uses_exact_content_key(client):
    first = client.post("/api/entries", json=payload(source_id=None))
    second = client.post(
        "/api/entries",
        json=payload(source_id=None, teacher="Mr Rao", label="General"),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["teacher"] == "Mr Rao"
    assert len(client.get("/api/entries").json()) == 1


def test_source_null_row_is_claimed_by_a_new_source_id(client):
    first = client.post("/api/entries", json=payload(source_id=None))
    second = client.post(
        "/api/entries",
        json=payload(source_id="diary-2026-06-03-1", teacher="Mr Rao"),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["source_id"] is None
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["source_id"] == "diary-2026-06-03-1"
    assert second.json()["teacher"] == "Mr Rao"

    rows = client.get("/api/entries").json()
    assert len(rows) == 1
    assert rows[0]["source_id"] == "diary-2026-06-03-1"


def test_concurrent_insert_race_is_retried_as_a_lookup(client, monkeypatch):
    original_commit = Session.commit
    state = {"raced": False}

    def racing_commit(self, *args, **kwargs):
        if not state["raced"]:
            state["raced"] = True
            original_commit(self)
            raise IntegrityError(
                "INSERT",
                {},
                Exception("UNIQUE constraint failed: entries.source_id"),
            )
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(Session, "commit", racing_commit)

    response = client.post("/api/entries", json=payload(source_id="racy"))

    assert response.status_code == 200
    assert state["raced"] is True
    assert response.json()["source_id"] == "racy"
    assert len(client.get("/api/entries").json()) == 1


def test_distinct_content_keeps_its_own_row(client):
    first = client.post("/api/entries", json=payload(source_id="one"))
    second = client.post(
        "/api/entries",
        json=payload(source_id="two", summary="Complete the worksheet at home."),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] != first.json()["id"]
    assert len(client.get("/api/entries").json()) == 2


def test_type_alias_is_accepted_for_importer_payloads(client):
    data = payload()
    data.pop("entry_type")
    data["type"] = "Announcement"

    response = client.post("/api/entries", json=data)

    assert response.status_code == 200
    assert response.json()["entry_type"] == "Announcement"


def test_attachment_shape_is_validated(client):
    response = client.post(
        "/api/entries",
        json=payload(
            attachments=[
                {
                    "name": "worksheet.pdf",
                    "url": "https://example.test/a.pdf",
                    "extra": True,
                }
            ]
        ),
    )

    assert response.status_code == 422


def test_entry_type_filter_is_exact(client):
    client.post("/api/entries", json=payload(source_id="diary"))
    client.post(
        "/api/entries",
        json=payload(entry_type="Worksheet", source_id="worksheet"),
    )

    response = client.get("/api/entries", params={"entry_type": "DiaryEntry"})

    assert response.status_code == 200
    assert [row["entry_type"] for row in response.json()] == ["DiaryEntry"]


def test_source_id_filter_is_exact(client):
    client.post("/api/entries", json=payload(source_id="diary", summary="Diary."))
    client.post(
        "/api/entries",
        json=payload(source_id="diary-extra", summary="Diary extra."),
    )
    client.post("/api/entries", json=payload(source_id="worksheet", summary="Worksheet."))

    response = client.get("/api/entries", params={"source_id": "diary"})

    assert response.status_code == 200
    assert [row["source_id"] for row in response.json()] == ["diary"]


def test_pagination_is_deterministic(client):
    client.post("/api/entries", json=payload(source_id="old", date="2026-06-01"))
    client.post("/api/entries", json=payload(source_id="middle", date="2026-06-02"))
    client.post("/api/entries", json=payload(source_id="new", date="2026-06-03"))

    first = client.get("/api/entries", params={"skip": 0, "limit": 1})
    second = client.get("/api/entries", params={"skip": 1, "limit": 1})
    third = client.get("/api/entries", params={"skip": 2, "limit": 1})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert [first.json()[0]["date"], second.json()[0]["date"], third.json()[0]["date"]] == [
        "2026-06-03",
        "2026-06-02",
        "2026-06-01",
    ]


def test_migration_guards_exact_content_conflicts_and_merges_attachments():
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "20260925000000_canonical_entries.sql"
    ).read_text(encoding="utf-8")

    # Migration has separate BEFORE INSERT and BEFORE UPDATE triggers
    assert "BEFORE INSERT ON public.entries" in migration
    assert "BEFORE UPDATE ON public.entries" in migration
    assert "entries_merge_attachments" in migration
    # Content-key dedupe uses the entries_content_key function in trigger
    assert "public.entries_content_key(" in migration
    assert "DELETE FROM public.entries" in migration
    assert "entries_merge_attachments" in migration
