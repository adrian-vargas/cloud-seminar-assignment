"""API tests with an in-memory repo: no database needed, so they run in CI."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repo import Note


class FakeRepo:
    def __init__(self) -> None:
        self.notes: dict[int, Note] = {}
        self.next_id = 1
        self.healthy = True

    def list(self, limit: int = 100) -> list[Note]:
        return sorted(self.notes.values(), key=lambda n: n.id, reverse=True)[:limit]

    def create(self, text: str) -> Note:
        note = Note(id=self.next_id, text=text, created_at=datetime.now(timezone.utc))
        self.notes[note.id] = note
        self.next_id += 1
        return note

    def delete(self, note_id: int) -> bool:
        return self.notes.pop(note_id, None) is not None

    def ping(self) -> bool:
        return self.healthy

    def close(self) -> None:
        pass


@pytest.fixture
def repo():
    return FakeRepo()


@pytest.fixture
def client(repo):
    with TestClient(create_app(repo)) as c:
        yield c


def test_message_uses_env(client, monkeypatch):
    monkeypatch.setenv("APP_MESSAGE", "Hi from tests")
    monkeypatch.setenv("APP_VERSION", "abc123")
    assert client.get("/api/message").json() == {"message": "Hi from tests", "version": "abc123"}


def test_create_list_delete(client):
    assert client.get("/api/notes").json() == []

    r = client.post("/api/notes", json={"text": "  first note  "})
    assert r.status_code == 201
    note = r.json()
    assert note["text"] == "first note"

    assert [n["id"] for n in client.get("/api/notes").json()] == [note["id"]]

    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get("/api/notes").json() == []


def test_delete_missing_returns_404(client):
    assert client.delete("/api/notes/999").status_code == 404


@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
def test_rejects_invalid_text(client, text):
    assert client.post("/api/notes", json={"text": text}).status_code == 422


def test_health_checks(client, repo):
    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code == 200
    repo.healthy = False
    assert client.get("/readyz").status_code == 503
    assert client.get("/livez").status_code == 200
