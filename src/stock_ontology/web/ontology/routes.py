"""Ontology module routes: model structure, registry, and audit tabs."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import asdict
from ipaddress import ip_address
from threading import Lock
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from stock_ontology.i18n import translate
from stock_ontology.services import JobRef, NotesService, RegistryService, ServiceError
from stock_ontology.services.corrections import review_note_correction
from stock_ontology.web.ontology.views import (
    build_ontology_context,
    build_registry_edit_context,
    build_registry_context,
    build_schema_context,
)
from stock_ontology.web.shared import build_rail_context
from stock_ontology.web.shell import WebShell, http_error


class RegistryEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["companies", "themes"]
    record: str = Field(min_length=1, max_length=1000)
    changes: dict[str, Any]
    keep_previous_name: bool = False


class CorrectionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["person", "relationship", "relationship_add"]
    file: str = Field(min_length=1, max_length=4000)
    record: str = Field(default="", max_length=1000)
    edge_id: str = Field(default="", max_length=1000)
    changes: dict[str, Any]
    keep_previous_name: bool = False


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str = Field(min_length=1, max_length=128)


class ApplyPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _loopback(value: str) -> bool:
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


def _operator_allowed(request: Request, origin: str | None, *, confirm: bool = True) -> bool:
    if not origin or not request.client or not _loopback(request.client.host):
        return False
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "http" or not parsed.hostname or not _loopback(parsed.hostname)
        or origin != f"http://{parsed.netloc}" or parsed.username is not None
        or request.headers.getlist("host") != [parsed.netloc]
        or any(key in {"forwarded", "via", "x-real-ip"} or key.startswith("x-forwarded")
               for key in request.headers)
    ):
        return False
    return not confirm or request.headers.getlist("origin") == [origin]


class _Reviews:
    """Process-local, action-specific reviews. A server restart requires a fresh review."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.entries: dict[str, tuple[str, float, dict[str, Any]]] = {}

    def add(self, token: str, action: str, payload: dict[str, Any]) -> None:
        with self.lock:
            now = monotonic()
            self.entries = {key: entry for key, entry in self.entries.items() if entry[1] > now}
            if len(self.entries) >= 256:
                del self.entries[next(iter(self.entries))]
            self.entries[token] = (action, now + 900, payload)

    def submit(self, token: str, action: str, enqueue: Callable[[dict[str, Any]], JobRef]) -> dict[str, str]:
        with self.lock:
            entry = self.entries.get(token)
            if not entry or entry[0] != action or entry[1] <= monotonic():
                raise ServiceError("conflict", "Start a new review before confirming.")
            result = enqueue(entry[2])
            del self.entries[token]
            return asdict(result)


def build_router(shell: WebShell) -> APIRouter:
    router = APIRouter()
    settings = shell.settings
    processing = shell.processing
    registry = RegistryService(settings)
    notes = NotesService(settings, processing)
    reviews = _Reviews()

    def require_operator(request: Request) -> None:
        if not _operator_allowed(request, shell.registry_origin):
            raise HTTPException(403, translate("ontology_edit.authority_required", lang=shell.lang(request)))

    def rejected(exc: Exception) -> HTTPException:
        return http_error(exc) if isinstance(exc, ServiceError) else HTTPException(422, str(exc))

    @router.post("/api/ontology/registry/publish/preview")
    def publish_preview(request: Request, edit: RegistryEdit) -> dict[str, Any]:
        require_operator(request)
        try:
            with shell.open_db(shell.lang(request)) as db:
                review = registry.review_record_edit(db, **edit.model_dump())
        except (ServiceError, ValueError) as exc:
            raise rejected(exc) from exc
        token = secrets.token_urlsafe(32)
        reviews.add(token, "publish", review["payload"])
        return {"confirmation": token, "diff": review["diff"]}

    @router.post("/api/ontology/registry/publish/confirm", status_code=202)
    def publish_confirm(request: Request, review: Confirmation) -> dict[str, str]:
        require_operator(request)
        try:
            return reviews.submit(review.confirmation, "publish",
                                  lambda payload: processing.submit_operator("registry.publish", payload))
        except ServiceError as exc:
            raise rejected(exc) from exc

    @router.post("/api/ontology/registry/apply/preview", status_code=202)
    def apply_preview(request: Request, _payload: ApplyPreview) -> dict[str, str]:
        require_operator(request)
        with shell.open_db(shell.lang(request)) as db:
            if not registry.browser_publication(db, registry.get_published(), db.applied_registry()):
                raise HTTPException(409, translate("ontology_edit.no_browser_revision", lang=shell.lang(request)))
        token = secrets.token_urlsafe(32)
        job = processing.submit_operator("registry.apply.preview", {"confirmation": token})
        reviews.add(token, "apply", {"job_id": job.job_id})
        return asdict(job)

    @router.post("/api/ontology/registry/apply/confirm", status_code=202)
    def apply_confirm(request: Request, review: Confirmation) -> dict[str, str]:
        require_operator(request)
        try:
            return reviews.submit(review.confirmation, "apply",
                                  lambda payload: processing.submit_reviewed_rollout(payload["job_id"], review.confirmation))
        except ServiceError as exc:
            raise rejected(exc) from exc

    @router.post("/api/ontology/corrections/preview")
    def correction_preview(request: Request, edit: CorrectionEdit) -> dict[str, Any]:
        shell.require_note_actions(request)
        try:
            path = notes.resolve(edit.file)
            with shell.open_db(shell.lang(request)) as db:
                review = review_note_correction(db, path, settings.data_dir, **edit.model_dump(exclude={"file"}))
        except (ServiceError, ValueError) as exc:
            raise rejected(exc) from exc
        token = secrets.token_urlsafe(32)
        reviews.add(token, "correction", review)
        return {"confirmation": token, "diff": review["diff"]}

    @router.post("/api/ontology/corrections/confirm", status_code=202)
    def correction_confirm(request: Request, review: Confirmation) -> dict[str, str]:
        shell.require_note_actions(request)
        try:
            return reviews.submit(
                review.confirmation, "correction",
                lambda payload: processing.submit_correction("note.ontology.correction", payload["file"], payload),
            )
        except ServiceError as exc:
            raise rejected(exc) from exc

    @router.get("/ontology", response_class=HTMLResponse)
    def ontology_page(
        request: Request,
        tab: str = "registry",
        subtype: str = "",
        reg_status: str = "",
        kind: str = "companies",
        record: str = "",
        q: str = "",
        node: str = "",
        relation: str = "",
    ) -> HTMLResponse:
        lang = shell.lang(request)
        reg, reg_err = shell.load_registry()
        active = tab.strip().lower()
        try:
            with shell.open_db(lang) as db:
                if active == "registry":
                    applied = db.applied_registry()
                    ctx = build_registry_context(
                        db, applied or reg, kind=kind, key=record, query=q, data_dir=settings.data_dir, lang=lang,
                    )
                    if ctx["registry_record"]:
                        ctx.update(build_registry_edit_context(
                            db, ctx, applied=applied, published=reg, data_dir=settings.data_dir,
                            operator_allowed=_operator_allowed(request, shell.registry_origin, confirm=False),
                            corrections_allowed=shell.note_actions,
                        ))
                elif active == "schema":
                    ctx = build_schema_context(db, reg, node_key=node, relation_key=relation, lang=lang)
                else:
                    ctx = build_ontology_context(
                        db,
                        tab=tab,
                        subtype=subtype,
                        reg_status=reg_status,
                        data_dir=settings.data_dir,
                        registry=reg,
                        registry_path=settings.registry_path,
                        registry_error=reg_err,
                        lang=lang,
                    )
                ctx["rail"] = build_rail_context(db)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=translate("ontology.item_not_found", lang=lang)) from exc
        return shell.render(request, "ontology.html", ctx, lang)

    return router
