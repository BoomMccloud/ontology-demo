"""Clippy module routes: the on-page chat dock and its `/ask` entry point."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from stock_ontology.agent import OntologyAgent
from stock_ontology.i18n import normalize_language, translate
from stock_ontology.web.shell import WebShell

MAX_CHAT_SESSIONS = 50


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    page_context: str | None = None
    lang: str | None = None


class ChatResetRequest(BaseModel):
    session_id: str


def build_router(shell: WebShell) -> APIRouter:
    router = APIRouter()
    settings = shell.settings
    # Opaque per-session history from `ChatTurn.history`, passed back unchanged.
    sessions: dict[str, tuple[Any, ...]] = {}

    @router.get("/ask")
    def ask_redirect(request: Request, context: str = "") -> RedirectResponse:
        """The Ask desk is the on-page Clippy dock: open it on Overview, carrying the context."""
        params = {"ask": "1"}
        if context.strip():
            params["context"] = context.strip()
        explicit_lang = normalize_language(request.query_params.get("lang"))
        if explicit_lang is not None:
            params["lang"] = explicit_lang
        return RedirectResponse(url=f"/?{urlencode(params)}", status_code=303)
    @router.post("/api/chat")
    def chat_endpoint(request: Request, payload: ChatRequest) -> JSONResponse:
        lang = shell.lang(request, explicit_lang=payload.lang)
        msg = payload.message.strip()
        if not msg:
            raise HTTPException(
                status_code=400,
                detail=translate("api.chat_empty_error", lang=lang),
            )

        sid = payload.session_id or f"sess_{uuid.uuid4().hex[:12]}"
        if sid not in sessions and len(sessions) >= MAX_CHAT_SESSIONS:
            oldest = next(iter(sessions))
            sessions.pop(oldest, None)

        history = sessions.get(sid, ())
        prompt = (
            f"[Current library page: {payload.page_context}]\n{msg}"
            if payload.page_context
            else msg
        )

        with shell.open_db(lang) as db:
            try:
                agent = OntologyAgent(
                    db, shell.llm, model=shell.agent_models.for_turn(), language=lang, data_dir=settings.data_dir
                )
                turn = agent.chat(prompt, history)
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(
                    {
                        "session_id": sid,
                        "lang": lang,
                        "error": str(exc),
                        "reply": translate("api.chat_error", lang=lang, error=exc),
                        "tools_used": [],
                    },
                    status_code=500,
                )
            sessions[sid] = turn.history

        return JSONResponse(
            {
                "session_id": sid,
                "lang": lang,
                "reply": turn.reply,
                "tools_used": list(turn.tools_used),
                "provider": turn.provider,
                "model": turn.model,
                "fallback_used": turn.fallback_used,
            }
        )

    @router.post("/api/chat/reset")
    def chat_reset(payload: ChatResetRequest) -> JSONResponse:
        sessions.pop(payload.session_id, None)
        return JSONResponse({"status": "reset", "session_id": payload.session_id})

    return router
