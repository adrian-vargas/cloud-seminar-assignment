"""Notes API: a tiny CRUD service backed by a managed Postgres database.

All configuration comes from environment variables:
  DATABASE_URL   Postgres connection string (secret, never in code)
  CORS_ORIGINS   comma-separated origins allowed to call the API (the frontend URL)
  APP_MESSAGE    greeting returned by /api/message
  APP_VERSION    set at build time to the git commit SHA
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .repo import Note, NotesRepo, PostgresNotesRepo

log = logging.getLogger("notes-api")


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be blank")
        return v


def create_app(repo: NotesRepo | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.shutting_down = False
        if app.state.repo is None:
            url = os.environ.get("DATABASE_URL")
            if not url:
                raise RuntimeError("DATABASE_URL is not set")
            pg = PostgresNotesRepo(url)
            pg.open()
            app.state.repo = pg
            log.info("connected to database")
        yield
        # Tell the platform to stop sending traffic before we close connections.
        app.state.shutting_down = True
        app.state.repo.close()

    app = FastAPI(title="Notes API", lifespan=lifespan)
    app.state.repo = repo
    app.state.shutting_down = False

    # Browsers send the Origin without a trailing slash, so strip it here.
    origins = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type"],
        )

    def get_repo(request: Request) -> NotesRepo:
        return request.app.state.repo

    @app.get("/api/message")
    def message():
        return {
            "message": os.environ.get("APP_MESSAGE", "Hello from the Notes API"),
            "version": os.environ.get("APP_VERSION", "dev"),
        }

    @app.get("/api/notes", response_model=list[Note])
    def list_notes(repo: NotesRepo = Depends(get_repo)):
        return repo.list()

    @app.post("/api/notes", response_model=Note, status_code=status.HTTP_201_CREATED)
    def create_note(body: NoteIn, repo: NotesRepo = Depends(get_repo)):
        return repo.create(body.text)

    @app.delete("/api/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_note(note_id: int, repo: NotesRepo = Depends(get_repo)):
        if not repo.delete(note_id):
            raise HTTPException(status_code=404, detail="note not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/livez")
    def livez():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(request: Request, response: Response, repo: NotesRepo = Depends(get_repo)):
        if request.app.state.shutting_down or not repo.ping():
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not ready"}
        return {"status": "ready"}

    return app


logging.basicConfig(level=logging.INFO)
app = create_app()
