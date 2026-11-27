"""Notes module routes: the catalog and note reader, pasting notes, and note corrections queued as worker jobs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from stock_ontology.i18n import translate
from stock_ontology.services import NoteSaveError, NotesService, ServiceError
from stock_ontology.services.corrections import review_note_correction
from stock_ontology.web.notes.views import build_catalog_context
from stock_ontology.web.shared import build_rail_context
from stock_ontology.web.shell import WebShell, http_error


class NoteCreateRequest(BaseModel):
    title: str
    content: str


class NoteProcessRequest(BaseModel):
    file: str


class NewNoteEntity(BaseModel):
    name: str
    facets: dict[str, Any]


class NoteEntityRequest(NoteProcessRequest):
    entity_id: str
    expected_hash: str | None = None


class NoteRelinkRequest(NoteEntityRequest):
    replacement_id: str | None = None
    new_entity: NewNoteEntity | None = None


class NoteRelationshipRequest(NoteProcessRequest):
    """A relationship correction in the Ontology page's shape; the URL names its kind."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str = ""
    changes: dict[str, Any] = {}
    expected_hash: str | None = None


def build_router(shell: WebShell) -> APIRouter:
    router = APIRouter()
    settings = shell.settings
    note_actions = shell.note_actions
    processing = shell.processing
    notes = NotesService(settings, processing)

    @router.get("/catalog", response_class=HTMLResponse)
    def catalog_page(
        request: Request,
        view: str = "company",
        dir: str = "",
        author: str = "",
        person: str = "",
        alpha: str = "",
        file: str = "",
        format: str = "rendered",
        back: str = "",
    ) -> HTMLResponse:
        lang = shell.lang(request)
        with shell.open_db(lang) as db:
            try:
                ctx = build_catalog_context(
                    db,
                    settings.data_dir,
                    view=view,
                    selected_dir=dir,
                    selected_author=author,
                    selected_person=person,
                    selected_alpha=alpha,
                    selected_file=file,
                    note_format=format,
                    return_to=back,
                    actions_enabled=note_actions,
                    note_job_state=_note_job_state if note_actions else None,
                    lang=lang,
                )
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=translate("api.raw_note_not_found", lang=lang, file=file),
                ) from exc
            ctx["rail"] = build_rail_context(db)
        return shell.render(request, "catalog.html", ctx, lang)

    @router.get("/notes/new", response_class=HTMLResponse)
    def note_new_page(request: Request) -> HTMLResponse:
        lang = shell.lang(request)
        with shell.open_db(lang) as db:
            ctx = {"rail": build_rail_context(db)}
        return shell.render(request, "note_new.html", ctx, lang)

    def _note_job_state(file: str) -> str:
        latest = processing.latest_for_note(file)
        return str(latest["state"]) if latest else ""

    @router.post("/api/notes", status_code=201)
    def create_note(request: Request, payload: NoteCreateRequest) -> dict[str, str]:
        """Save pasted text as a note and queue its processing job. The demo has only a root user."""
        lang = shell.lang(request)
        try:
            ref = notes.save(payload.title, payload.content)
        except NoteSaveError as exc:
            raise HTTPException(
                status_code=400,
                detail=translate(f"notes_new.error_{exc.code}", lang=lang),
            ) from exc
        return {"file": ref.file, "job_id": ref.job_id}

    def _note_error(request: Request, file: str, exc: ServiceError) -> HTTPException:
        if exc.code == "not_found":
            return HTTPException(404, translate("api.raw_note_not_found", lang=shell.lang(request), file=file))
        return http_error(exc, shell.lang(request))

    def _submitted(request: Request, file: str, submit: Any) -> JSONResponse:
        shell.require_note_actions(request)
        try:
            ref = submit()
        except ServiceError as exc:
            raise _note_error(request, file, exc) from exc
        return JSONResponse({"file": file, "job_id": ref.job_id, "state": ref.state}, status_code=202)

    def _correction(request: Request, kind: str, payload: BaseModel) -> JSONResponse:
        params = payload.model_dump(exclude={"file"})
        file = getattr(payload, "file")
        return _submitted(request, file, lambda: processing.submit_correction(kind, file, params))

    @router.post("/api/notes/process", status_code=202)
    def process_note(request: Request, payload: NoteProcessRequest) -> JSONResponse:
        return _submitted(request, payload.file, lambda: processing.request_processing(payload.file))

    @router.post("/api/notes/relink", status_code=202)
    def relink_note(request: Request, payload: NoteRelinkRequest) -> JSONResponse:
        return _correction(request, "note.relink", payload)

    @router.post("/api/notes/entity/add", status_code=202)
    def add_note_entity(request: Request, payload: NoteEntityRequest) -> JSONResponse:
        return _correction(request, "note.entity.add", payload)

    @router.post("/api/notes/entity/delete", status_code=202)
    def delete_note_entity(request: Request, payload: NoteEntityRequest) -> JSONResponse:
        return _correction(request, "note.entity.delete", payload)

    def _reviewed_correction(request: Request, kind: str, payload: NoteRelationshipRequest) -> JSONResponse:
        """Review a relationship correction now, by the Ontology page's rules, and queue what was reviewed."""
        shell.require_note_actions(request)
        file = payload.file
        lang = shell.lang(request)
        try:
            path = notes.resolve(file).resolve()
        except ServiceError as exc:
            raise _note_error(request, file, exc) from exc
        try:
            with shell.open_db(lang) as db:
                reviewed = review_note_correction(
                    db, path, settings.data_dir, kind=kind, edge_id=payload.edge_id, changes=payload.changes,
                )
        except ServiceError as exc:
            raise http_error(exc, lang) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        # The reader must have rendered the revision that was reviewed.
        if payload.expected_hash and payload.expected_hash != reviewed["expected_hash"]:
            stale = ServiceError("conflict", "Review the latest processed version of this source note.",
                                 key="service_error.stale_source_note")
            raise http_error(stale, lang)
        return _submitted(request, file, lambda: processing.submit_correction("note.ontology.correction", file, reviewed))

    @router.post("/api/notes/relationship", status_code=202)
    def correct_note_relationship(request: Request, payload: NoteRelationshipRequest) -> JSONResponse:
        return _reviewed_correction(request, "relationship", payload)

    @router.post("/api/notes/relationship/add", status_code=202)
    def add_note_relationship(request: Request, payload: NoteRelationshipRequest) -> JSONResponse:
        return _reviewed_correction(request, "relationship_add", payload)

    @router.post("/api/notes/relationship/delete", status_code=202)
    def delete_note_relationship(request: Request, payload: NoteRelationshipRequest) -> JSONResponse:
        return _reviewed_correction(request, "relationship_delete", payload)

    return router
