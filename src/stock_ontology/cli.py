"""Typer CLI for the Stock Ontology ingestion pipeline, inspection, and read-only PM agent."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from difflib import unified_diff
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from stock_ontology.agent import OntologyAgent
from stock_ontology.audit import AuditReport, run_ontology_audit
from stock_ontology.config import VALID_PROVIDERS, Settings
from stock_ontology.db import OntologyDB
from stock_ontology.i18n import (
    SUPPORTED_LANGUAGE_CODES,
    format_relation_label,
    get_language_spec,
    normalize_language,
    translate,
    translate_enum,
)
from stock_ontology.llm import create_llm_client
from stock_ontology.pipeline import IngestionPipeline, reembed_all_nodes, reembed_nodes
from stock_ontology.registry import (
    OntologyRegistry,
    RegistryPublication,
    RegistrySuggestions,
    SuggestionSyncSummary,
    create_minimal_registry,
    load_registry,
    save_registry_json,
)
from stock_ontology.repair import RepairReport, repair_ontology, validate_rollout

app = typer.Typer(
    name="stock-ontology",
    help="4-node stock ontology extraction pipeline and strictly read-only PM query agent.",
    no_args_is_help=True,
)
console = Console()

# Keep Pydantic AI's startup banner out of `ask`, `chat` and `serve` output.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


def _load_settings(
    db: Path | None = None,
    data_dir: Path | None = None,
    registry: Path | None = None,
) -> Settings:
    return Settings.from_env(db_path=db, data_dir=data_dir, registry_path=registry)


def _resolve_cli_lang(settings: Settings, lang: str | None) -> str:
    if lang is not None and lang.strip():
        resolved = normalize_language(lang)
        if resolved is None:
            msg = translate(
                "api.unsupported_language",
                lang=settings.default_language,
                requested=lang,
                supported=", ".join(SUPPORTED_LANGUAGE_CODES),
            )
            console.print(f"[red]{msg}[/red]")
            raise typer.Exit(code=1)
        return resolved
    return settings.default_language


def _load_ingest_registry(settings: Settings) -> OntologyRegistry:
    """Load the official registry for relation canonicalization; fall back to the built-in one."""
    if not Path(settings.registry_path).exists():
        console.print(
            f"[yellow]Registry not found at {settings.registry_path}; using the built-in minimal registry.[/yellow]"
        )
        return create_minimal_registry()
    return load_registry(settings.registry_path)


def _open_readonly_db(settings: Settings) -> OntologyDB:
    reg: OntologyRegistry | None = None
    if Path(settings.registry_path).exists():
        try:
            reg = load_registry(settings.registry_path)
        except Exception:  # noqa: BLE001
            reg = None
    try:
        return OntologyDB(
            settings.db_path, embedding_dim=settings.embedding_dim, read_only=True, registry=reg
        )
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command()
def ingest(
    data_dir: Annotated[
        Path | None, typer.Option("--data-dir", help="Root folder containing research notes (any folder layout).")
    ] = None,
    db: Annotated[
        Path | None, typer.Option("--db", help="Path to SQLite ontology database.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-ingest all files even if unchanged.")
    ] = False,
    rebuild_consensus: Annotated[
        bool,
        typer.Option("--rebuild-consensus", help="Re-synthesize consensus for all companies."),
    ] = False,
    lang: Annotated[
        str | None,
        typer.Option("--lang", "-l", help="Output language (en, zh, ko, ja, es, fr)."),
    ] = None,
) -> None:
    """Scan research notes, extract ontology graphs with the configured LLM router, and update DB consensus."""
    settings = _load_settings(db=db, data_dir=data_dir)
    resolved_lang = _resolve_cli_lang(settings, lang)
    llm = create_llm_client(settings)
    console.print(f"[cyan]{translate('cli.llm_chain', lang=resolved_lang)}[/cyan] {llm.format_chain_summary()}")
    try:
        with OntologyDB(settings.db_path, embedding_dim=settings.embedding_dim, read_only=False) as store:
            pipeline = IngestionPipeline(
                store, llm, settings.data_dir, registry=_load_ingest_registry(settings)
            )
            report = pipeline.run(force=force, rebuild_consensus=rebuild_consensus)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{translate('cli.ingest_failed', lang=resolved_lang)}[/red] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title=translate("cli.ingest_title", lang=resolved_lang))
    table.add_column(translate("cli.col_metric", lang=resolved_lang), style="cyan")
    table.add_column(translate("cli.col_value", lang=resolved_lang), style="bold")
    table.add_row(translate("cli.metric_scanned", lang=resolved_lang), str(report.files_scanned))
    table.add_row(translate("cli.metric_processed", lang=resolved_lang), str(report.files_processed))
    table.add_row(translate("cli.metric_skipped", lang=resolved_lang), str(report.files_skipped))
    table.add_row(translate("cli.metric_deleted", lang=resolved_lang), str(report.files_deleted))
    table.add_row(translate("cli.metric_nodes", lang=resolved_lang), str(report.nodes_created_or_updated))
    table.add_row(translate("cli.metric_edges", lang=resolved_lang), str(report.edges_created_or_updated))
    table.add_row(
        translate("cli.metric_consensus", lang=resolved_lang),
        ", ".join(report.consensus_updated_for)
        if report.consensus_updated_for
        else translate("cli.none_value", lang=resolved_lang),
    )
    table.add_row(
        translate("cli.metric_pending_relations", lang=resolved_lang),
        ", ".join(f"{name} ({count})" for name, count in sorted(report.unmapped_relations_pending.items()))
        or translate("cli.none_value", lang=resolved_lang),
    )
    table.add_row(
        translate("cli.metric_facets_dropped", lang=resolved_lang),
        ", ".join(f"{key} ({count})" for key, count in sorted(report.invalid_facets_dropped.items()))
        or translate("cli.none_value", lang=resolved_lang),
    )
    table.add_row(translate("cli.metric_errors", lang=resolved_lang), str(len(report.errors)))
    console.print(table)
    if report.errors:
        console.print(f"[yellow]{translate('cli.per_item_errors', lang=resolved_lang)}[/yellow]")
        for item, err in report.errors:
            console.print(f"  [yellow]- {item}:[/yellow] {err}")


@app.command()
def reembed(
    db: Annotated[
        Path | None, typer.Option("--db", help="Path to SQLite ontology database.")
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            help="Explicit embedding provider (e.g. gemini, dashscope, openai, openai_compatible).",
        ),
    ] = None,
    allow_fallback: Annotated[
        bool,
        typer.Option(
            "--allow-fallback",
            help="Allow falling back to a secondary embedding provider if the primary fails.",
        ),
    ] = False,
) -> None:
    """Recompute and atomically replace vector embeddings for all nodes in the database."""
    settings = _load_settings(db=db)
    if not settings.db_path.exists():
        console.print(
            f"[red]Database not found at {settings.db_path}. Run `ingest` first.[/red]"
        )
        raise typer.Exit(code=1)

    updates: dict[str, Any] = {"llm_fallback_enabled": allow_fallback}
    if provider is not None and provider.strip():
        prov = provider.strip().lower()
        if prov not in VALID_PROVIDERS:
            console.print(
                f"[red]Invalid provider {provider!r}. Expected one of {', '.join(VALID_PROVIDERS)}.[/red]"
            )
            raise typer.Exit(code=1)
        if not settings.supports_embeddings(prov):  # type: ignore[arg-type]
            console.print(
                f"[red]Provider {prov!r} does not support embeddings.[/red]"
            )
            raise typer.Exit(code=1)
        updates["embedding_providers"] = [prov]

    effective_settings = settings.model_copy(update=updates)
    llm = create_llm_client(effective_settings)
    try:
        with OntologyDB(
            effective_settings.db_path,
            embedding_dim=effective_settings.embedding_dim,
            read_only=False,
        ) as store:
            report = reembed_all_nodes(store, llm)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Re-embed failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        llm.close()

    table = Table(title="Vector Re-embed Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    table.add_row("Database", str(effective_settings.db_path))
    table.add_row("Provider", str(report.provider or "-"))
    table.add_row("Model", str(report.model or "-"))
    table.add_row("Embedding Dim", str(report.embedding_dim))
    table.add_row("Total Nodes", str(report.total_nodes))
    table.add_row("Re-embedded", str(report.reembedded))
    console.print(table)


@app.command()
def watch(
    interval: Annotated[
        int, typer.Option("--interval", min=5, help="Polling interval in seconds.")
    ] = 60,
    data_dir: Annotated[
        Path | None, typer.Option("--data-dir", help="Root folder containing research notes (any folder layout).")
    ] = None,
    db: Annotated[
        Path | None, typer.Option("--db", help="Path to SQLite ontology database.")
    ] = None,
    lang: Annotated[
        str | None,
        typer.Option("--lang", "-l", help="Output language (en, zh, ko, ja, es, fr)."),
    ] = None,
) -> None:
    """Periodically run incremental ingestion on `data_dir`."""
    settings = _load_settings(db=db, data_dir=data_dir)
    resolved_lang = _resolve_cli_lang(settings, lang)
    llm = create_llm_client(settings)
    console.print(
        f"[cyan]{translate('cli.watching_msg', lang=resolved_lang, data_dir=settings.data_dir, interval=interval, db_path=settings.db_path, llm=llm.format_chain_summary())}[/cyan]"
    )

    def _on_tick(report: object) -> None:
        from stock_ontology.pipeline import IngestReport

        if isinstance(report, IngestReport) and (
            report.files_processed or report.files_deleted or report.consensus_updated_for
        ):
            console.print(
                f"[green]Tick:[/green] processed={report.files_processed}, "
                f"deleted={report.files_deleted}, "
                f"consensus={report.consensus_updated_for}"
            )

    try:
        with OntologyDB(settings.db_path, embedding_dim=settings.embedding_dim, read_only=False) as store:
            pipeline = IngestionPipeline(
                store, llm, settings.data_dir, registry=_load_ingest_registry(settings)
            )
            pipeline.watch(interval_seconds=interval, on_tick=_on_tick)
    except KeyboardInterrupt:
        console.print(f"\n[yellow]{translate('cli.watch_stopped', lang=resolved_lang)}[/yellow]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{translate('cli.watch_failed', lang=resolved_lang)}[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def inspect(
    query: Annotated[
        str | None, typer.Argument(help="Optional entity name/ticker, theme name, or node ID.")
    ] = None,
    db: Annotated[
        Path | None, typer.Option("--db", help="Path to SQLite ontology database.")
    ] = None,
    lang: Annotated[
        str | None,
        typer.Option("--lang", "-l", help="Output language (en, zh, ko, ja, es, fr)."),
    ] = None,
) -> None:
    """Inspect database summary or drill into a specific entity, theme, or node."""
    settings = _load_settings(db=db)
    resolved_lang = _resolve_cli_lang(settings, lang)
    with _open_readonly_db(settings) as store:
        if not query:
            stats = store.get_stats()
            console.print(
                Panel(
                    translate(
                        "cli.db_stats_summary",
                        lang=resolved_lang,
                        total_nodes=stats["total_nodes"],
                        entity=stats["nodes"]["entity"],
                        event=stats["nodes"]["event"],
                        view=stats["nodes"]["view"],
                        theme=stats["nodes"]["theme"],
                        total_edges=stats["total_edges"],
                        active_consensus=stats["active_consensus_views"],
                        ingested_files=stats["ingested_files"],
                    ),
                    title=translate("cli.db_panel_title", lang=resolved_lang, db_path=settings.db_path),
                )
            )

            ent_table = Table(title=translate("cli.table_entities", lang=resolved_lang))
            ent_table.add_column(translate("cli.col_id", lang=resolved_lang), style="dim")
            ent_table.add_column(translate("cli.col_name", lang=resolved_lang), style="bold")
            ent_table.add_column(translate("cli.col_type", lang=resolved_lang))
            ent_table.add_column(translate("cli.col_aliases", lang=resolved_lang))
            ent_table.add_column(translate("cli.col_consensus", lang=resolved_lang), style="cyan")
            for ent in store.list_nodes(node_type="entity", limit=200):
                cons = store.get_entity_consensus(ent.id)
                stance = (
                    f"{translate_enum('stance', cons.facets.get('stance', '?'), lang=resolved_lang)} "
                    f"({translate_enum('conviction', cons.facets.get('conviction', '?'), lang=resolved_lang)})"
                    if cons is not None
                    else "-"
                )
                ent_table.add_row(
                    ent.id,
                    ent.name,
                    translate_enum("entity_type", str(ent.facets.get("entity_type", "")), lang=resolved_lang),
                    ", ".join(ent.aliases),
                    stance,
                )
            console.print(ent_table)

            thm_table = Table(title=translate("cli.table_themes", lang=resolved_lang))
            thm_table.add_column(translate("cli.col_id", lang=resolved_lang), style="dim")
            thm_table.add_column(translate("cli.col_name", lang=resolved_lang), style="bold")
            thm_table.add_column(translate("cli.col_stage", lang=resolved_lang))
            thm_table.add_column(translate("cli.col_summary", lang=resolved_lang))
            for thm in store.list_nodes(node_type="theme", limit=200):
                thm_table.add_row(
                    thm.id,
                    thm.name,
                    translate_enum("stage", str(thm.facets.get("stage", "")), lang=resolved_lang),
                    thm.summary,
                )
            console.print(thm_table)
            return

        node = store.get_node(query)
        if node is None:
            node = store.find_by_name_or_alias(query, node_type="entity")
        if node is None:
            node = store.find_by_name_or_alias(query, node_type="theme")
        if node is None:
            matches = store.keyword_search(query, limit=1)
            node = matches[0] if matches else None

        if node is None:
            console.print(
                f"[yellow]{translate('cli.no_node_found', lang=resolved_lang, query=query)}[/yellow]"
            )
            raise typer.Exit(code=1)

        if node.node_type == "entity":
            ov = store.get_entity_overview(node.id)
            cons = ov["consensus"]
            cons_text = (
                f"{translate('cli.stance_line', lang=resolved_lang, stance=translate_enum('stance', cons['facets'].get('stance'), lang=resolved_lang), strength=translate_enum('support_strength', cons['facets'].get('support_strength'), lang=resolved_lang), conviction=translate_enum('conviction', cons['facets'].get('conviction'), lang=resolved_lang))}\n"
                f"{translate('cli.summary_label', lang=resolved_lang)} {cons['summary']}\n"
                f"{translate('cli.pillars_label', lang=resolved_lang)} {cons['facets'].get('pillars', [])}"
                if cons
                else translate("cli.no_consensus_yet", lang=resolved_lang)
            )
            sent_summary = ov.get("sentiment_summary") or {}
            sent_counts = sent_summary.get("counts_by_sentiment") or {}
            classified_total = sum(
                int(sent_counts.get(k, 0)) for k in ("positive", "negative", "neutral", "mixed")
            )
            sent_line = ""
            if classified_total or sent_counts.get("unclassified"):
                sent_line = (
                    translate(
                        "cli.sentiment_line",
                        lang=resolved_lang,
                        pos=sent_counts.get("positive", 0),
                        neg=sent_counts.get("negative", 0),
                        neu=sent_counts.get("neutral", 0),
                        mix=sent_counts.get("mixed", 0),
                        unc=sent_counts.get("unclassified", 0),
                    )
                    + "\n"
                )
            console.print(
                Panel(
                    f"[bold]{node.name}[/bold] ({node.id})\n"
                    f"{translate('cli.aliases_label', lang=resolved_lang)} {node.aliases}\n"
                    f"{translate('cli.facets_label', lang=resolved_lang)} {node.facets}\n"
                    f"{sent_line}\n"
                    f"[cyan]{translate('cli.house_consensus_label', lang=resolved_lang)}[/cyan]\n{cons_text}",
                    title=translate("cli.entity_overview_title", lang=resolved_lang),
                )
            )
            for section, items, show_sentiment, use_rel_dir in (
                (translate("cli.section_events", lang=resolved_lang), ov["events"], True, False),
                (translate("cli.section_views", lang=resolved_lang), ov["views"], True, False),
                (translate("cli.section_themes", lang=resolved_lang), ov["themes"], False, True),
                (translate("cli.section_related", lang=resolved_lang), ov["related_entities"], False, True),
            ):
                if not items:
                    continue
                t = Table(title=section)
                t.add_column(translate("cli.col_id", lang=resolved_lang), style="dim")
                t.add_column(translate("cli.col_relation", lang=resolved_lang), style="cyan")
                if show_sentiment:
                    t.add_column(translate("cli.col_sentiment", lang=resolved_lang))
                t.add_column(translate("cli.col_name", lang=resolved_lang), style="bold")
                t.add_column(translate("cli.col_summary", lang=resolved_lang))
                for item in items:
                    if use_rel_dir:
                        rels = item.get("relationships")
                        if rels:
                            rel_label = ", ".join(
                                format_relation_label(
                                    r["relation"], r.get("direction"), lang=resolved_lang
                                )
                                for r in rels
                            )
                        else:
                            rel_label = format_relation_label(
                                item["relation"], item.get("direction"), lang=resolved_lang
                            )
                            exp_sent = item.get("exposure_sentiment")
                            if exp_sent:
                                rel_label = (
                                    f"{rel_label} [{translate_enum('sentiment', exp_sent, lang=resolved_lang)}]"
                                )
                    else:
                        rel_label = translate_enum("relation", item["relation"], lang=resolved_lang)
                    if show_sentiment:
                        eff_s = item.get("effective_sentiment")
                        s_label = translate_enum("sentiment", eff_s, lang=resolved_lang) if eff_s else "-"
                        t.add_row(item["id"], rel_label, s_label, item["name"], item["summary"])
                    else:
                        t.add_row(item["id"], rel_label, item["name"], item["summary"])
                console.print(t)
        elif node.node_type == "theme":
            res = store.find_theme_companies(node.id)
            console.print(
                Panel(
                    f"[bold]{node.name}[/bold] ({node.id})\n{node.summary}\n"
                    f"{translate('cli.facets_label', lang=resolved_lang)} {node.facets}",
                    title=translate("cli.theme_overview_title", lang=resolved_lang),
                )
            )
            t = Table(title=translate("theme.affected_companies", lang=resolved_lang))
            t.add_column(translate("cli.col_company", lang=resolved_lang), style="bold")
            t.add_column(translate("cli.col_consensus", lang=resolved_lang))
            t.add_column(translate("ontology.col_links", lang=resolved_lang))
            for row in res["companies"]:
                stance_raw = row.get("consensus_stance")
                stance_label = (
                    translate_enum("stance", stance_raw, lang=resolved_lang) if stance_raw else "-"
                )
                t.add_row(row["company"]["name"], stance_label, str(row.get("links")))
            console.print(t)
        else:
            console.print(
                Panel(
                    f"[bold]{node.name}[/bold] ({translate_enum('node_type', node.node_type, lang=resolved_lang)} / {node.id})\n"
                    f"{node.summary}\n{translate('cli.facets_label', lang=resolved_lang)} {node.facets}",
                    title=translate("cli.node_details_title", lang=resolved_lang),
                )
            )
            t = Table(title=translate("cli.incident_edges_title", lang=resolved_lang))
            t.add_column(translate("cli.col_direction", lang=resolved_lang))
            t.add_column(translate("cli.col_relation", lang=resolved_lang), style="cyan")
            t.add_column(translate("cli.col_neighbor", lang=resolved_lang))
            for edge in store.get_incident_edges(node.id):
                nb = edge["neighbor"]
                t.add_row(
                    translate_enum("direction", edge["direction"], lang=resolved_lang),
                    translate_enum("relation", edge["relation"], lang=resolved_lang),
                    f"{nb['name']} ({nb['id']})",
                )
            console.print(t)


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Question for the read-only PM query agent.")],
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Optional meeting note or article file to attach."),
    ] = None,
    db: Annotated[
        Path | None, typer.Option("--db", help="Path to SQLite ontology database.")
    ] = None,
    lang: Annotated[
        str | None,
        typer.Option("--lang", "-l", help="Response language (en, zh, ko, ja, es, fr)."),
    ] = None,
) -> None:
    """Ask a single question (optionally attaching a meeting note) against the ontology DB."""
    settings = _load_settings(db=db)
    resolved_lang = _resolve_cli_lang(settings, lang)
    prompt = question
    if file is not None:
        if not file.exists():
            console.print(f"[red]{translate('cli.attachment_not_found', lang=resolved_lang)}[/red] {file}")
            raise typer.Exit(code=1)
        note_text = file.read_text(encoding="utf-8")
        prompt = f"{question}\n\n--- ATTACHED NOTE ({file.name}) ---\n{note_text}"

    llm = create_llm_client(settings)
    with _open_readonly_db(settings) as store:
        agent = OntologyAgent(store, llm, language=resolved_lang)
        try:
            answer = agent.ask(prompt)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]{translate('cli.agent_error', lang=resolved_lang)}[/red] {exc}")
            raise typer.Exit(code=1) from exc
    console.print(Markdown(answer))


@app.command()
def chat(
    db: Annotated[
        Path | None, typer.Option("--db", help="Path to SQLite ontology database.")
    ] = None,
    lang: Annotated[
        str | None,
        typer.Option("--lang", "-l", help="Chat UI and response language (en, zh, ko, ja, es, fr)."),
    ] = None,
) -> None:
    """Start an interactive multi-turn read-only PM chat session."""
    settings = _load_settings(db=db)
    resolved_lang = _resolve_cli_lang(settings, lang)
    lang_spec = get_language_spec(resolved_lang)
    llm = create_llm_client(settings)
    with _open_readonly_db(settings) as store:
        agent = OntologyAgent(store, llm, language=resolved_lang)
        console.print(
            Panel(
                translate(
                    "cli.chat_banner",
                    lang=resolved_lang,
                    db_path=settings.db_path,
                    llm=llm.format_chain_summary(),
                    language=f"{lang_spec['native_name']} ({resolved_lang})",
                ),
                title=translate("cli.chat_title", lang=resolved_lang),
            )
        )
        prompt_label = translate("cli.chat_prompt", lang=resolved_lang)
        goodbye_msg = translate("cli.chat_goodbye", lang=resolved_lang)
        cleared_msg = translate("cli.chat_cleared", lang=resolved_lang)
        err_prefix = translate("cli.error_prefix", lang=resolved_lang)
        while True:
            try:
                user_input = console.input(f"[bold cyan]{prompt_label}[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print(f"\n{goodbye_msg}")
                break
            if not user_input:
                continue
            if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
                console.print(goodbye_msg)
                break
            if user_input.lower() == "/reset":
                agent.reset()
                console.print(f"[dim]{cleared_msg}[/dim]")
                continue
            try:
                reply = agent.ask(user_input)
                console.print(Markdown(reply))
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]{err_prefix}[/red] {exc}")


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Bind host address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8000,
    db: Annotated[
        Path | None, typer.Option("--db", help="Path to SQLite ontology database.")
    ] = None,
    data_dir: Annotated[
        Path | None, typer.Option("--data-dir", help="Root folder containing raw research notes.")
    ] = None,
    lang: Annotated[
        str | None,
        typer.Option("--lang", "-l", help="Default web UI language (en, zh, ko, ja, es, fr)."),
    ] = None,
) -> None:
    """Start the 1990s Library UI and Office-Clippy PM chat (read-only DB, can add pasted notes)."""
    import uvicorn

    from stock_ontology.web import create_app

    settings = _load_settings(db=db, data_dir=data_dir)
    resolved_lang = _resolve_cli_lang(settings, lang)
    settings = settings.model_copy(update={"default_language": resolved_lang})
    if not settings.db_path.exists():
        console.print(
            f"[red]{translate('api.db_not_initialized', lang=resolved_lang, db_path=settings.db_path)}[/red]"
        )
        raise typer.Exit(code=1)

    llm = create_llm_client(settings)
    console.print(
        f"[cyan]{translate('cli.serve_starting', lang=resolved_lang, host=host, port=port, db_path=settings.db_path, language=resolved_lang)}[/cyan]\n"
        f"[cyan]{translate('cli.llm_chain', lang=resolved_lang)}[/cyan] {llm.format_chain_summary()}"
    )
    uvicorn.run(create_app(settings, llm=llm), host=host, port=port)


def _render_audit_report(
    report: AuditReport,
    *,
    db_path: Path,
    registry_path: Path,
    sync_summary: SuggestionSyncSummary | None,
    suggestion_path: Path,
) -> None:
    s = report.summary
    sync_line = (
        f"\nSuggestions synced -> {suggestion_path}: "
        f"added={sync_summary.added}, updated={sync_summary.updated}, "
        f"auto_resolved={sync_summary.auto_resolved}, preserved_decided={sync_summary.preserved_decided} "
        f"(pending: rel={sync_summary.pending_relations}, co={sync_summary.pending_companies}, "
        f"thm={sync_summary.pending_themes}, merge={sync_summary.pending_merges})"
        if sync_summary is not None
        else "\nSuggestions sync skipped (--no-sync-suggestions)."
    )
    console.print(
        Panel(
            f"Edges: {s.total_edges} (exact={s.mapped_exact_edges}, alias={s.mapped_alias_edges}, "
            f"inverse={s.mapped_inverse_edges}, unmapped={s.unmapped_edges} across "
            f"{s.distinct_unmapped_relations} relations, direction_issues={s.direction_issue_edges}, "
            f"contradictions={s.reciprocal_contradiction_pairs}, pending_unmapped={s.pending_edges}, "
            f"pending_endpoints={s.pending_endpoint_edges})\n"
            f"Companies: {s.total_companies} (mapped={s.mapped_companies}, unmapped={s.unmapped_companies}, "
            f"dup_candidates={s.duplicate_company_candidate_pairs}, ticker_issues={s.ticker_normalization_issue_count})\n"
            f"Themes: {s.total_themes} (mapped={s.mapped_themes}, unmapped={s.unmapped_themes}, "
            f"near_dups={s.near_duplicate_theme_pairs})\n"
            f"Suspicious aliases: {s.suspicious_alias_count} | Facet alias hits: {s.facet_alias_hit_count} | "
            f"Missing sentiment: events={s.events_missing_sentiment}/{s.total_events}, "
            f"views={s.views_missing_sentiment}/{s.total_views}"
            f"{sync_line}",
            title=f"Ontology Audit: {db_path} vs {registry_path}",
        )
    )

    if report.relation_normalization_hits or report.direction_issues or report.reciprocal_contradictions:
        t = Table(title="Relation Alias / Inverse & Direction Issues")
        t.add_column("Kind", style="cyan")
        t.add_column("Relation", style="bold")
        t.add_column("Canonical")
        t.add_column("Count", justify="right")
        t.add_column("Detail")
        for hit in report.relation_normalization_hits:
            detail = "flip_direction=True" if hit.flip_direction else "alias -> canonical"
            t.add_row(hit.match_kind, hit.raw_relation, hit.canonical_relation, str(hit.count), detail)
        for iss in report.direction_issues:
            sample = (
                f" | e.g. {iss.sample_edges[0].from_name} -> {iss.sample_edges[0].to_name}"
                if iss.sample_edges
                else ""
            )
            t.add_row(
                iss.issue_type,
                iss.relation,
                iss.canonical_relation,
                str(iss.count),
                f"observed={iss.observed_signature}; expected={iss.expected_signature}{sample}",
            )
        for rc in report.reciprocal_contradictions:
            t.add_row(
                "reciprocal_contradiction",
                rc.relation,
                rc.relation,
                f"{rc.forward_count}/{rc.reverse_count}",
                f"{rc.node_a_name} <-> {rc.node_b_name}",
            )
        console.print(t)

    if report.unmapped_relations:
        t = Table(title="Unmapped Relations -> Suggested New Ontology")
        t.add_column("Relation", style="bold")
        t.add_column("Count", justify="right")
        t.add_column("Top Signatures")
        t.add_column("Sample Edge")
        for rel in report.unmapped_relations:
            sigs = ", ".join(
                f"{sig.from_type}->{sig.to_type} ({sig.count})"
                for sig in rel.observed_signatures[:2]
            )
            sample = (
                f"{rel.sample_edges[0].from_name} -[{rel.sample_edges[0].relation}]-> {rel.sample_edges[0].to_name}"
                if rel.sample_edges
                else "-"
            )
            t.add_row(rel.name, str(rel.edge_count), sigs, sample)
        console.print(t)

    if report.unmapped_companies:
        t = Table(title="Unmapped Companies -> Suggested New Ontology")
        t.add_column("Company", style="bold")
        t.add_column("Ticker")
        t.add_column("Signals", justify="right")
        t.add_column("Consensus")
        t.add_column("Nearest Official")
        for co in report.unmapped_companies:
            nearest = (
                f"{co.nearest_official.name} (d={co.nearest_official.distance:.3f})"
                if co.nearest_official is not None
                else "-"
            )
            t.add_row(
                co.name,
                co.ticker or "-",
                str(co.signal_count),
                co.consensus_stance or ("yes" if co.has_consensus else "-"),
                nearest,
            )
        console.print(t)

    if report.unmapped_themes:
        t = Table(title="Unmapped Themes -> Suggested New Ontology")
        t.add_column("Theme", style="bold")
        t.add_column("Stage")
        t.add_column("Companies", justify="right")
        t.add_column("Nearest Official (cosine dist)")
        for thm in report.unmapped_themes:
            nearest = (
                f"{thm.nearest_official.name} (d={thm.nearest_official.distance:.3f})"
                if thm.nearest_official is not None
                else "-"
            )
            t.add_row(thm.name, thm.stage or "-", str(thm.company_count), nearest)
        console.print(t)

    if report.near_duplicate_themes:
        t = Table(title="Near-Duplicate Themes")
        t.add_column("Theme A", style="bold")
        t.add_column("Theme B", style="bold")
        t.add_column("Distance", justify="right")
        for pair in report.near_duplicate_themes:
            dist_str = f"{pair.distance:.4f}" if pair.distance is not None else "-"
            t.add_row(pair.node_a_name, pair.node_b_name, dist_str)
        console.print(t)

    if report.suspicious_aliases or report.duplicate_company_candidates:
        t = Table(title="Suspicious Aliases & Duplicate Company Candidates")
        t.add_column("Kind", style="yellow")
        t.add_column("Node / Pair", style="bold")
        t.add_column("Detail")
        t.add_column("Reason")
        for sa in report.suspicious_aliases:
            et = sa.entity_type or "entity"
            t.add_row("suspicious_alias", f"{sa.node_name} ({et})", f"alias={sa.alias!r}", sa.reason)
        for dup in report.duplicate_company_candidates:
            dist_str = f"d={dup.distance:.4f}" if dup.distance is not None else "same_ticker"
            t.add_row("duplicate_company", f"{dup.node_a_name} <-> {dup.node_b_name}", dist_str, dup.reason)
        console.print(t)

    if report.ticker_normalization_issues or report.facet_alias_hits:
        t = Table(title="Ticker Normalization & Facet Drift")
        t.add_column("Category", style="cyan")
        t.add_column("Target", style="bold")
        t.add_column("Current -> Normalized")
        for ti in report.ticker_normalization_issues:
            t.add_row("ticker", ti.name, f"{ti.raw_ticker!r} -> {ti.normalized_ticker!r}")
        for fh in report.facet_alias_hits:
            t.add_row(f"facet:{fh.node_type}", f"{fh.count} node(s)", f"{fh.raw_key} -> {fh.canonical_key}")
        console.print(t)


@app.command()
def audit(
    db: Annotated[
        Path | None, typer.Option("--db", help="Path to SQLite ontology database.")
    ] = None,
    registry: Annotated[
        Path | None, typer.Option("--registry", help="Path to official ontology_registry.json.")
    ] = None,
    sync_suggestions: Annotated[
        bool,
        typer.Option(
            "--sync-suggestions/--no-sync-suggestions",
            help="Write pending proposals to a separate suggestions file.",
        ),
    ] = True,
    json_out: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON audit report.")
    ] = False,
) -> None:
    """Audit ontology.db strictly read-only against ontology_registry.json and sync suggestions."""
    settings = _load_settings(db=db, registry=registry)
    try:
        reg = load_registry(settings.registry_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Registry error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    with _open_readonly_db(settings) as store:
        report = run_ontology_audit(store, reg)
        applied = store.applied_registry()
        stamp = store.get_metadata("registry_version")

    status = {
        "published_version": reg.version,
        "published_revision": reg.revision(),
        "applied_version": applied.version if applied else None,
        "applied_revision": applied.revision() if applied else None,
        "schema_stamp_matches": stamp == reg.schema_stamp(),
    }

    sync_summary: SuggestionSyncSummary | None = None
    suggestion_path = settings.registry_path.with_suffix(".suggestions.json")
    if sync_suggestions:
        reg.suggestions = _load_suggestions(suggestion_path, reg.suggestions)
        sync_summary = reg.sync_suggestions(
            report.unmapped_relations,
            report.unmapped_companies,
            report.unmapped_themes,
            merge_candidates=[*report.duplicate_company_candidates, *report.near_duplicate_themes],
        )
        save_registry_json({"suggestions": reg.suggestions.model_dump(mode="json")}, suggestion_path)

    if json_out:
        payload = {
            "report": report.model_dump(),
            "sync": sync_summary.model_dump() if sync_summary is not None else None,
            "registry": status,
        }
        print(json.dumps(payload, indent=2))
        return

    typer.echo(f"Registry version published: {reg.version}. Applied: {applied.version if applied else 'unrecorded'}.")
    _render_audit_report(
        report,
        db_path=settings.db_path,
        registry_path=settings.registry_path,
        sync_summary=sync_summary,
        suggestion_path=suggestion_path,
    )


def _load_suggestions(path: Path, fallback: RegistrySuggestions) -> RegistrySuggestions:
    if not path.exists():
        return fallback
    return RegistrySuggestions.model_validate(json.loads(path.read_text(encoding="utf-8"))["suggestions"])


def _echo_diff(before: list[str], after: list[str], from_label: str, to_label: str, *, err: bool = False) -> None:
    for line in unified_diff(before, after, fromfile=from_label, tofile=to_label, lineterm=""):
        typer.echo(line, err=err)


def _confirm_review(prompt: str, *, json_out: bool = False) -> bool:
    if not json_out:
        return typer.confirm(prompt)
    typer.echo(f"{prompt} [y/N]: ", nl=False, err=True)
    return sys.stdin.readline().strip().casefold() in {"y", "yes"}


@app.command()
def registry_publish(
    proposal: Annotated[Path, typer.Argument(help="Proposed full registry JSON.")],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    registry: Annotated[Path | None, typer.Option("--registry")] = None,
) -> None:
    """Review a proposal and confirm publication of its registry version."""
    settings = _load_settings(db=db, registry=registry)
    try:
        current = load_registry(settings.registry_path)
        proposed = load_registry(proposal)
        if proposed.version <= current.version:
            raise ValueError("The proposal must have a version higher than the published version.")  # noqa: TRY003, TRY301
        with _open_readonly_db(settings) as store:
            if store.applied_registry() is None:
                raise ValueError("Record the current applied registry with registry-apply before publishing.")  # noqa: TRY003, TRY301
        before = json.dumps(current.official_definitions(), indent=2, sort_keys=True, ensure_ascii=False)
        after = json.dumps(proposed.official_definitions(), indent=2, sort_keys=True, ensure_ascii=False)
        _echo_diff(before.splitlines(), after.splitlines(), f"published v{current.version}", f"proposal v{proposed.version}")
        if not typer.confirm(f"Publish registry version {proposed.version} to {settings.registry_path}?"):
            return
        with OntologyDB(settings.db_path, embedding_dim=settings.embedding_dim) as store, store.transaction(
            immediate=True
        ):
            if load_registry(settings.registry_path).revision() != current.revision():
                raise ValueError("The published registry changed during review. Preview the proposal again.")  # noqa: TRY003, TRY301
            suggestion_path = settings.registry_path.with_suffix(".suggestions.json")
            if not suggestion_path.exists():
                save_registry_json({"suggestions": current.suggestions.model_dump(mode="json")}, suggestion_path)
            official = proposed.official_definitions()
            publication = RegistryPublication(
                version=proposed.version,
                revision=proposed.revision(),
                previous_revision=current.revision(),
                confirmed_at=datetime.now(UTC).isoformat(),
            )
            official["publications"] = [
                item.model_dump(mode="json") for item in [*current.publications, publication]
            ]
            save_registry_json(official, settings.registry_path)
        typer.echo(f"Published registry version {proposed.version}. Use registry-apply to review database adoption.")
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _review_registry_rollout(
    settings: Settings, target: OntologyRegistry, *, adoption: bool, err: bool = False
) -> RepairReport | None:
    """Preview a repair on a copy, then apply exactly the reviewed result under a write lock."""
    published_revision = load_registry(settings.registry_path).revision()
    if adoption and published_revision != target.revision():
        raise ValueError("The published registry changed. Run a new preview.")  # noqa: TRY003
    with tempfile.TemporaryDirectory(prefix="ontology-rollout-") as temp_dir:
        copy_path = Path(temp_dir) / "preview.db"
        with _open_readonly_db(settings) as source:
            source.copy_to(copy_path)
        with OntologyDB(copy_path, embedding_dim=settings.embedding_dim) as preview:
            applied = preview.applied_registry()
            old_revision = applied.revision() if applied else None
            old_stamp = preview.get_metadata("registry_version")
            if adoption and applied and old_revision != target.revision() and (
                not target.publications or target.publications[-1].revision != target.revision()
            ):
                raise ValueError("Publish this registry proposal using registry-publish before applying it.")  # noqa: TRY003
            if not adoption and (old_revision or old_stamp) and (
                old_revision != target.revision() if applied else old_stamp != target.schema_stamp()
            ):
                raise ValueError("Use registry-apply to review and adopt a different registry version.")  # noqa: TRY003
            before = preview.registry_rollout_rows()
            planned = repair_ontology(preview, target, data_dir=settings.data_dir)
            validate_rollout(preview, target)
            after = preview.registry_rollout_rows()

    starting_version = f"v{applied.version}" if applied else "unrecorded"
    typer.echo(f"Database {settings.db_path}. Applied {starting_version}. Target v{target.version}.", err=err)
    _echo_diff(before, after, "current database", "reviewed database", err=err)
    if before == after:
        typer.echo("No graph rows will change.", err=err)
    prompt = "Apply this registry rollout?" if adoption else "Apply this repair?"
    if not _confirm_review(prompt, json_out=err):
        return None

    with OntologyDB(settings.db_path, embedding_dim=settings.embedding_dim) as store, store.transaction(immediate=True):
        current = store.applied_registry()
        current_revision = current.revision() if current else None
        if (
            load_registry(settings.registry_path).revision() != published_revision
            or current_revision != old_revision
            or store.get_metadata("registry_version") != old_stamp
            or store.registry_rollout_rows() != before
        ):
            raise ValueError("Registry or database changed during review. Run a new preview.")  # noqa: TRY003
        result = repair_ontology(store, target, data_dir=settings.data_dir)
        validate_rollout(store, target)
        if store.registry_rollout_rows() != after or result != planned:
            raise ValueError("The migration result changed during review. Run a new preview.")  # noqa: TRY003
        if adoption:
            plan = sha256(json.dumps([before, after]).encode("utf-8")).hexdigest()
            store.record_registry_adoption(target, old_revision, plan)
    return result


@app.command()
def registry_apply(
    db: Annotated[Path | None, typer.Option("--db")] = None,
    registry: Annotated[Path | None, typer.Option("--registry")] = None,
) -> None:
    """Review and separately confirm adoption of the published registry."""
    settings = _load_settings(db=db, registry=registry)
    try:
        published = load_registry(settings.registry_path)
        if _review_registry_rollout(settings, published, adoption=True) is not None:
            typer.echo(f"Applied registry version {published.version}.")
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def repair(
    db: Annotated[
        Path | None, typer.Option("--db", help="Path to SQLite ontology database.")
    ] = None,
    registry: Annotated[
        Path | None, typer.Option("--registry", help="Path to official ontology_registry.json.")
    ] = None,
    json_out: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON repair report.")
    ] = False,
    reembed: Annotated[
        bool,
        typer.Option(
            "--reembed",
            help="Recompute embeddings of merged survivors with the configured LLM (needs API keys).",
        ),
    ] = False,
) -> None:
    """Apply deterministic fixes to ontology.db: orphaned rows, alias/inverse relations, exact duplicates."""
    settings = _load_settings(db=db, registry=registry)
    try:
        reg = load_registry(settings.registry_path)
        reg.suggestions = _load_suggestions(settings.registry_path.with_suffix(".suggestions.json"), reg.suggestions)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Registry error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if not Path(settings.db_path).exists():
        console.print(f"[red]Ontology database does not exist at {settings.db_path}.[/red]")
        raise typer.Exit(code=1)

    try:
        if reembed:
            typer.echo("Merged survivors will be reembedded after the confirmed repair.", err=json_out)
        report = _review_registry_rollout(settings, reg, adoption=False, err=json_out)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if report is None:
        return

    reembedded = 0
    if reembed and report.merged_survivor_ids:
        llm = create_llm_client(settings)
        with OntologyDB(settings.db_path, embedding_dim=settings.embedding_dim) as store:
            reembedded = reembed_nodes(store, llm, report.merged_survivor_ids)

    payload = {**asdict(report), "total_changes": report.total_changes, "reembedded": reembedded}
    if json_out:
        print(json.dumps(payload, indent=2))
        return
    table = Table(title=f"Ontology Repair: {settings.db_path}")
    table.add_column("Fix", style="cyan")
    table.add_column("Rows", style="bold")
    for key, value in payload.items():
        table.add_row(key, str(value))
    console.print(table)


if __name__ == "__main__":
    app()
