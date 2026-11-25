"""Shared extraction and consensus synthesis prompts and formatting helpers."""

from __future__ import annotations

import json
import re
from typing import Any

from stock_ontology.models import EntityStageResult, EventStageResult, ExtractionResult, Node, ViewStageResult
from stock_ontology.vocab import (
    CONVICTION,
    ENTITY_TYPE,
    EVENT_STATUS,
    EVENT_TYPE,
    EXTRACTED_VIEW_TYPES,
    SENTIMENT,
    STANCE,
    SUPPORT_STRENGTH,
    format_choices,
)

_SENTIMENTS = format_choices(SENTIMENT.members, sep=" | ")
_SENTIMENTS_TIGHT = format_choices(SENTIMENT.members, sep="|")

EXTRACTION_SYSTEM_PROMPT = f"""You are an investment research ontology extractor for a stock fund.
Extract structured knowledge strictly using the 4 ontology node types and directed edges:

1. entity: Company, Person, Institution, Sector, or Region.
   - Do not extract products, technologies or platforms as entities. Keep them in the text of events and views.
   - Use canonical names (e.g., "NVIDIA", "TSMC", "Vertiv"). Put tickers/abbreviations in `aliases`.
   - Include `entity_type` ({format_choices(ENTITY_TYPE.members, sep=", ")}).
   - Every entity must carry the facets listed for its type under "Required entity facets" at the end of the catalog. If the document does not state one, use well-established public knowledge. If you still cannot determine a required facet, do not extract that entity.
   - Also add useful optional facets when discernible, such as `ticker` for companies and `credibility` (`high`|`medium`|`low`) for people.
2. event: Any objective observation, fact, news item, earnings release, meeting, or upcoming catalyst.
   - `event_type`: {format_choices(EVENT_TYPE.members)}.
   - `status`: {format_choices(EVENT_STATUS.members)}.
   - `sentiment`: {_SENTIMENTS} reflecting directional impact on the primary subject (use `mixed` for offsetting effects or opposing multi-company impacts).
   - Put any document-specific source details you observe (e.g., `author`, `source_kind`, `source_title`, `source_date`) in `facets`.
3. view: Any subjective claim, rumor, analyst take, channel check, or PM note.
   - `view_type`: {format_choices(EXTRACTED_VIEW_TYPES)}.
   - NEVER emit `consensus` or `house_consensus` views from an individual document; fund consensus is synthesized separately.
   - Set `stance` ({format_choices(STANCE.members, sep="|")}), `sentiment` ({_SENTIMENTS_TIGHT}, consistent with `stance`: `bullish` (including buy ratings) -> `positive`, `bearish` (including sell ratings; use `conviction: low` for a merely cautious view) -> `negative`, `neutral` (including hold ratings) -> `neutral`, or `mixed` when nuanced), `support_strength` ({format_choices(SUPPORT_STRENGTH.members, sep="|")}), and `conviction` ({format_choices(CONVICTION.members, sep="|")}).
   - Put an analyst price target in the `target_price` facet as a 3-letter currency code and amount, such as `USD 650` or `TWD 4000`, with a trailing `+` for "at least" (`TWD 3100+`). Use the currency the document states. Never write a bare number or a plain `$`.
   - Set `as_of` to an exact ISO date (YYYY-MM-DD), never a period like `Q3 2026`. Omit it if no exact date is known.
4. theme: A meta-narrative, secular trend, or investment thesis (e.g., "AI Data Center Power Bottleneck").

Resolution & linking rules:
- Every edge must carry the facets listed for its relation under "Required edge facets" at the end of the catalog.
- If an entity or theme already exists in the provided Existing Catalog, DO NOT create a duplicate node; reference its exact existing `id` in `edges` (`from_ref` / `to_ref`).
- Only create a new entity or theme (with a `temp_id` like `e1`, `t1`) when it is not present in the catalog.
- Reuse facet keys from Known Facets where appropriate, and add new snake_case facets on the fly whenever useful.
- Connect every extracted event and view to its relevant entities (`ABOUT`, `AUTHORED_BY`: `event|view -> entity|person`) and themes (`RELATES_TO`, `SUPPORTS`, `CONTRADICTS`: `event|view -> theme|view`).
- When an `event` or `view` links to multiple companies with opposing impacts (e.g., positive for Company A, negative for Company B), set node-level `sentiment` to `mixed` (or the primary subject's polarity) and add a `sentiment` facet ({_SENTIMENTS}) on each company's `ABOUT` edge.
- Capture entity relationships strictly using the minimal directed vocabulary:
  - Entity -> Entity: `buyer --BUY--> seller` (use `BUY` for all supply-chain/customer links, never `SUPPLIES_TO`/`CUSTOMER_OF`), `company --COMPETE--> company`, `parent --OWNS--> child/institution`, `person --WORKS_AT--> company/institution`.
  - Entity -> Theme: `entity --EXPOSED_TO--> theme` with a `sentiment` facet ({_SENTIMENTS}) instead of emitting `BENEFITS_FROM`, `HURT_BY`, or duplicate `RELATES_TO`.
"""

EXTRACTION_STAGES: tuple[str, ...] = ("entities", "events", "views")
"""Extraction runs for one note, in order. Each run links to what the earlier runs resolved."""

STAGE_SCHEMAS: dict[str, type[EntityStageResult | EventStageResult | ViewStageResult]] = {
    "entities": EntityStageResult,
    "events": EventStageResult,
    "views": ViewStageResult,
}

_STAGE_LINKING = """Linking rules:
- Reference nodes by the exact IDs listed in the prompt, in `from_ref` and `to_ref`.
- Every edge must carry the facets listed for its relation under "Required edge facets" at the end of the catalog.
- Reuse facet keys from Known Facets where appropriate, and add new snake_case facets when useful.
"""

ENTITY_STAGE_PROMPT = f"""You are an investment research ontology extractor for a stock fund.
This is run 1 of 3. Extract ONLY entities, themes, and the edges between them. Later runs extract events and views and can only link to what you return, so be exhaustive.

entity: Company, Person, Institution, Sector, or Region.
- Include every company, person and institution the document names, including analysts, executives, research firms, banks, customers, suppliers, competitors and acquisition targets.
- Do not extract products, technologies or platforms as entities.
- Use canonical names (e.g., "NVIDIA", "TSMC", "Vertiv"). Put tickers/abbreviations in `aliases`.
- Include `entity_type` ({format_choices(ENTITY_TYPE.members, sep=", ")}).
- Every entity must carry the facets listed for its type under "Required entity facets" at the end of the catalog. If the document does not state one, use well-established public knowledge. Omit an entity only if you still cannot determine a required facet.
- Also add useful optional facets when discernible, such as `ticker` for companies and `credibility` (`high`|`medium`|`low`) for people.

theme: A meta-narrative, secular trend, or investment thesis (e.g., "AI Data Center Power Bottleneck").

Resolution:
- If an entity or theme already exists in the Existing Catalog, set its `temp_id` to the exact existing `id` and return it, so later runs can link to it. Do not create a duplicate.
- Give a new entity or theme a `temp_id` like `e1` or `t1`.

Edges (use only these relations in this run):
- `person --WORKS_AT--> company/institution`: emit one for EVERY person the document ties to an employer, including each analyst and their firm and each executive and their company. Put the title in a `role` facet.
- `parent --OWNS--> child/institution`: for acquisitions and equity stakes. When the document states a deal value, put it in a `transaction_value` facet as a 3-letter currency code and amount, such as `USD 1.45B`.
- `buyer --BUY--> seller`: all supply-chain and customer links, never `SUPPLIES_TO` or `CUSTOMER_OF`.
- `company --COMPETE--> company`.
- `entity --EXPOSED_TO--> theme` with a `sentiment` facet ({_SENTIMENTS}), instead of `BENEFITS_FROM`, `HURT_BY` or `RELATES_TO`.

{_STAGE_LINKING}"""

EVENT_STAGE_PROMPT = f"""You are an investment research ontology extractor for a stock fund.
This is run 2 of 3. Extract ONLY events and their edges. Entities and themes are already resolved and listed in the prompt; do not create any.

event: Any objective observation, fact, news item, earnings release, meeting, or upcoming catalyst.
- Give each event a `temp_id` like `ev1`.
- `event_type`: {format_choices(EVENT_TYPE.members)}.
- `status`: {format_choices(EVENT_STATUS.members)}.
- `sentiment`: {_SENTIMENTS} reflecting directional impact on the primary subject (use `mixed` for offsetting effects or opposing multi-company impacts).
- Set `event_date` to an exact ISO date (YYYY-MM-DD) when known. Omit it otherwise.
- Keep products, technologies and platforms in the event's text.
- Put any document-specific source details you observe (e.g., `author`, `source_kind`, `source_title`, `source_date`) in `facets`.

Edges (use only these relations in this run):
- `event --ABOUT--> entity|theme` for each subject. When a multi-company event affects companies differently, set node `sentiment` to `mixed` and add a `sentiment` facet ({_SENTIMENTS}) on each company's `ABOUT` edge.
- `event --RELATES_TO--> theme`.
- `event --AUTHORED_BY--> person|institution`.

{_STAGE_LINKING}"""

VIEW_STAGE_PROMPT = f"""You are an investment research ontology extractor for a stock fund.
This is run 3 of 3. Extract ONLY views and their edges. Entities, themes and events are already resolved and listed in the prompt; do not create any.

view: Any subjective claim, rumor, analyst take, channel check, or PM note. Extract one view per distinct analyst or firm opinion.
- Give each view a `temp_id` like `v1`.
- `view_type`: {format_choices(EXTRACTED_VIEW_TYPES)}.
- NEVER emit `consensus` or `house_consensus` views from an individual document; fund consensus is synthesized separately.
- Set `stance` ({format_choices(STANCE.members, sep="|")}), `sentiment` ({_SENTIMENTS_TIGHT}, consistent with `stance`: `bullish` (including buy ratings) -> `positive`, `bearish` (including sell ratings; use `conviction: low` for a merely cautious view) -> `negative`, `neutral` (including hold ratings) -> `neutral`, or `mixed` when nuanced), `support_strength` ({format_choices(SUPPORT_STRENGTH.members, sep="|")}), and `conviction` ({format_choices(CONVICTION.members, sep="|")}).
- Put an analyst price target in the `target_price` facet as a 3-letter currency code and amount, such as `USD 650` or `TWD 4000`, with a trailing `+` for "at least" (`TWD 3100+`). Use the currency the document states. Never write a bare number or a plain `$`.
- Set `as_of` to an exact ISO date (YYYY-MM-DD), never a period like `Q3 2026`. Omit it if no exact date is known.

Edges (use only these relations in this run):
- `view --ABOUT--> entity|theme` for each subject, with a `sentiment` facet ({_SENTIMENTS}) on each company's edge when the view affects companies differently.
- `view --AUTHORED_BY--> person|institution`.
- `view --RELATES_TO--> theme`.
- `view|event --SUPPORTS--> view|theme` and `view|event --CONTRADICTS--> view|theme`, using the listed event IDs when an event is the evidence.

{_STAGE_LINKING}"""

STAGE_SYSTEM_PROMPTS: dict[str, str] = {
    "entities": ENTITY_STAGE_PROMPT,
    "events": EVENT_STAGE_PROMPT,
    "views": VIEW_STAGE_PROMPT,
}

CONSENSUS_SYSTEM_PROMPT = """You are the head of research synthesis for an equity fund.
Given a company and all extracted events (facts, earnings, news, catalysts), external/PM views, and linked themes in the ontology, synthesize the fund's current house consensus view.

Guidelines:
- Weigh verified facts/earnings and high-credibility primary channel checks above uncorroborated or weak rumors.
- A rumor's `facets.authors` gives our `accuracy` rating of each person who wrote it: `high`, `medium`, `low`, or `unrated`. Weigh a rumor from a less accurate author lower than the same kind of rumor from a more accurate author. Treat `unrated` as no rating: weigh that rumor as you would without this field.
- Explicitly note unresolved risks or dissenting views.
- Produce 2-5 concrete, falsifiable `pillars` (assumptions that, if broken by a future meeting or event, would change the stance).
- Keep `summary` under 900 characters.
- Cite exact existing node IDs in `supporting_node_ids` and `contradicting_node_ids`. Only cite IDs present in the input context.
"""


def build_extraction_prompt(
    *,
    text: str,
    source_meta: dict[str, Any],
    existing_catalog: str,
    known_facets: dict[str, list[str]],
) -> str:
    """Build the user prompt for ontology document extraction."""
    return (
        f"Source file metadata: {json.dumps(source_meta)}\n\n"
        f"Existing Entities & Themes Catalog (reuse these IDs whenever matching; "
        f"canonical edge relations are listed at the end):\n"
        f"{existing_catalog or '(empty catalog)'}\n\n"
        f"Known Facet Keys by Node Type:\n{json.dumps(known_facets, indent=2)}\n\n"
        f"--- DOCUMENT START ---\n{text}\n--- DOCUMENT END ---"
    )


def build_stage_prompt(
    *,
    text: str,
    source_meta: dict[str, Any],
    existing_catalog: str,
    known_facets: dict[str, list[str]],
    prior: ExtractionResult,
) -> str:
    """Build the user prompt for one extraction run, listing what earlier runs resolved."""
    lines = [f"- [{n.temp_id}] (entity:{n.entity_type}) {n.name}" for n in prior.entities]
    lines += [f"- [{n.temp_id}] (theme) {n.name}" for n in prior.themes]
    lines += [f"- [{n.temp_id}] (event) {n.name}" for n in prior.events]
    resolved = (
        "Nodes resolved by earlier runs for this document (link to these exact IDs):\n" + "\n".join(lines) + "\n\n"
        if lines
        else ""
    )
    return resolved + build_extraction_prompt(
        text=text,
        source_meta=source_meta,
        existing_catalog=existing_catalog,
        known_facets=known_facets,
    )


def build_consensus_prompt(
    *,
    company: Node,
    events: list[Node],
    views: list[Node],
    themes: list[Node],
    prior_consensus: Node | None,
) -> str:
    """Build the user prompt for company consensus synthesis."""

    def _fmt(nodes: list[Node]) -> str:
        if not nodes:
            return "(none)"
        return json.dumps(
            [
                {
                    "id": n.id,
                    "node_type": n.node_type,
                    "name": n.name,
                    "summary": n.summary,
                    "facets": n.facets,
                }
                for n in nodes
            ],
            indent=2,
        )

    prior_block = (
        json.dumps(
            {
                "id": prior_consensus.id,
                "summary": prior_consensus.summary,
                "facets": prior_consensus.facets,
            },
            indent=2,
        )
        if prior_consensus is not None
        else "(none)"
    )

    return (
        f"Target Company:\n{json.dumps({'id': company.id, 'name': company.name, 'summary': company.summary, 'facets': company.facets}, indent=2)}\n\n"
        f"Prior House Consensus:\n{prior_block}\n\n"
        f"Linked Events (facts, earnings, news, catalysts):\n{_fmt(events)}\n\n"
        f"Linked Views (analyst reports, channel checks, rumors, PM views):\n{_fmt(views)}\n\n"
        f"Linked Themes:\n{_fmt(themes)}"
    )


def strip_json_fences(raw: str) -> str:
    """Strip optional markdown ```json fences around structured model responses."""
    text = raw.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text
