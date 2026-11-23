"""Shared extraction and consensus synthesis prompts and formatting helpers."""

from __future__ import annotations

import json
import re
from typing import Any

from stock_ontology.models import Node
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

1. entity: Company, Person, Product/Tech, Institution, Sector, or Region.
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
4. theme: A meta-narrative, secular trend, or investment thesis (e.g., "AI Data Center Power Bottleneck").

Resolution & linking rules:
- If an entity or theme already exists in the provided Existing Catalog, DO NOT create a duplicate node; reference its exact existing `id` in `edges` (`from_ref` / `to_ref`).
- Only create a new entity or theme (with a `temp_id` like `e1`, `t1`) when it is not present in the catalog.
- Reuse facet keys from Known Facets where appropriate, and add new snake_case facets on the fly whenever useful.
- Connect every extracted event and view to its relevant entities (`ABOUT`, `AUTHORED_BY`: `event|view -> entity|person`) and themes (`RELATES_TO`, `SUPPORTS`, `CONTRADICTS`: `event|view -> theme|view`).
- When an `event` or `view` links to multiple companies with opposing impacts (e.g., positive for Company A, negative for Company B), set node-level `sentiment` to `mixed` (or the primary subject's polarity) and add a `sentiment` facet ({_SENTIMENTS}) on each company's `ABOUT` edge.
- Capture entity relationships strictly using the minimal directed vocabulary:
  - Entity -> Entity: `buyer --BUY--> seller` (use `BUY` for all supply-chain/customer links, never `SUPPLIES_TO`/`CUSTOMER_OF`), `company --COMPETE--> company`, `parent --OWNS--> child/institution`, `person --WORKS_AT--> company/institution`.
  - Entity -> Theme: `entity --EXPOSED_TO--> theme` with a `sentiment` facet ({_SENTIMENTS}) instead of emitting `BENEFITS_FROM`, `HURT_BY`, or duplicate `RELATES_TO`.
"""

CONSENSUS_SYSTEM_PROMPT = """You are the head of research synthesis for an equity fund.
Given a company and all extracted events (facts, earnings, news, catalysts), external/PM views, and linked themes in the ontology, synthesize the fund's current house consensus view.

Guidelines:
- Weigh verified facts/earnings and high-credibility primary channel checks above uncorroborated or weak rumors.
- Explicitly note unresolved risks or dissenting views.
- Produce 2-5 concrete, falsifiable `pillars` (assumptions that, if broken by a future meeting or event, would change the stance).
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
