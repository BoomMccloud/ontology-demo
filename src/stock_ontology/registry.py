"""Official ontology registry models, normalization, resolution, and suggestion sync."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

SuggestionStatus = Literal["pending", "approved", "aliased", "rejected"]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_relation_name(raw: str) -> str:
    """Normalize an edge relation name to canonical UPPER_SNAKE_CASE."""
    cleaned = raw.strip().upper().replace(" ", "_").replace("-", "_")
    return re.sub(r"_+", "_", cleaned).strip("_")


def normalize_ticker(raw: str | None) -> str | None:
    """Normalize a stock ticker by stripping exchange prefixes like `NYSE: VRT`."""
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if ":" in cleaned:
        cleaned = cleaned.split(":")[-1].strip()
    return cleaned.upper() or None


def normalize_name_key(raw: str) -> str:
    """Return a canonical case-folded lookup key for entity/theme names."""
    return raw.strip().casefold()


def make_suggestion_id(prefix: str, label: str) -> str:
    """Generate a deterministic slugged suggestion ID from a prefix and label."""
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:48] or "item"
    return f"{prefix}_{slug}"


class RelationSpec(BaseModel):
    """Canonical relation definition in the official ontology registry."""

    name: str
    description: str = ""
    from_types: list[str] = Field(default_factory=list)
    to_types: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    inverse_aliases: list[str] = Field(default_factory=list)
    alias_facets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    symmetric: bool = False
    traversal_group: str = "other"


class CompanySpec(BaseModel):
    """Canonical company entry in the official ontology registry."""

    name: str
    ticker: str | None = None
    sector: str | None = None
    aliases: list[str] = Field(default_factory=list)


class ThemeSpec(BaseModel):
    """Canonical investment theme entry in the official ontology registry."""

    name: str
    stage: str = "accelerating"
    description: str = ""
    aliases: list[str] = Field(default_factory=list)


class NearestMatch(BaseModel):
    """Nearest existing official ontology entry by embedding cosine distance."""

    name: str
    distance: float


class ObservedSignature(BaseModel):
    """Observed endpoint type signature and frequency for an edge relation."""

    from_type: str
    to_type: str
    count: int


class SampleEdge(BaseModel):
    """Concrete edge example surfaced during an ontology audit."""

    from_name: str
    relation: str
    to_name: str


class RelationSuggestion(BaseModel):
    """Unmapped edge relation queued for admin review."""

    id: str
    name: str
    status: SuggestionStatus = "pending"
    edge_count: int = 0
    observed_signatures: list[ObservedSignature] = Field(default_factory=list)
    sample_edges: list[SampleEdge] = Field(default_factory=list)
    mapped_to: str | None = None
    reviewer_note: str | None = None
    first_seen_at: str = Field(default_factory=_utc_now_iso)
    last_seen_at: str = Field(default_factory=_utc_now_iso)


class CompanySuggestion(BaseModel):
    """Unmapped company entity queued for admin review."""

    id: str
    name: str
    node_id: str
    status: SuggestionStatus = "pending"
    ticker: str | None = None
    raw_ticker: str | None = None
    sector: str | None = None
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    signal_count: int = 0
    has_consensus: bool = False
    consensus_stance: str | None = None
    nearest_official: NearestMatch | None = None
    mapped_to: str | None = None
    reviewer_note: str | None = None
    first_seen_at: str = Field(default_factory=_utc_now_iso)
    last_seen_at: str = Field(default_factory=_utc_now_iso)


class ThemeSuggestion(BaseModel):
    """Unmapped investment theme queued for admin review."""

    id: str
    name: str
    node_id: str
    status: SuggestionStatus = "pending"
    stage: str | None = None
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    company_count: int = 0
    nearest_official: NearestMatch | None = None
    mapped_to: str | None = None
    reviewer_note: str | None = None
    first_seen_at: str = Field(default_factory=_utc_now_iso)
    last_seen_at: str = Field(default_factory=_utc_now_iso)


class RegistrySuggestions(BaseModel):
    """Pending and historical ontology extension suggestions discovered by audit."""

    relations: list[RelationSuggestion] = Field(default_factory=list)
    companies: list[CompanySuggestion] = Field(default_factory=list)
    themes: list[ThemeSuggestion] = Field(default_factory=list)


class RelationMatch(BaseModel):
    """Result of resolving a raw relation name against the official registry."""

    canonical: str
    spec: RelationSpec
    match_kind: Literal["exact", "alias", "inverse"]
    flip_direction: bool
    default_facets: dict[str, Any] = Field(default_factory=dict)


class CanonicalEdgeResult(BaseModel):
    """Canonicalized edge projection produced from `OntologyRegistry.canonicalize_edge`."""

    relation: str
    from_id: str
    to_id: str
    from_type: str
    from_entity_type: str | None = None
    to_type: str
    to_entity_type: str | None = None
    facets: dict[str, Any] = Field(default_factory=dict)
    matched: bool = False
    symmetric: bool = False
    flipped: bool = False


def matches_type_spec(
    node_type: str, entity_type: str | None, allowed: list[str]
) -> bool:
    """Return True when `(node_type, entity_type)` satisfies an allowed registry type list."""
    if not allowed:
        return True
    if node_type in allowed:
        return True
    if entity_type and f"{node_type}:{entity_type}" in allowed:
        return True
    return False


class CompanyMatch(BaseModel):
    """Result of resolving a company node against the official registry."""

    spec: CompanySpec
    match_kind: Literal["ticker", "exact", "alias"]


class ThemeMatch(BaseModel):
    """Result of resolving a theme node against the official registry."""

    spec: ThemeSpec
    match_kind: Literal["exact", "alias"]


class SuggestionSyncSummary(BaseModel):
    """Summary counts from syncing audit discoveries into `registry.suggestions`."""

    added: int = 0
    updated: int = 0
    auto_resolved: int = 0
    preserved_decided: int = 0
    pending_relations: int = 0
    pending_companies: int = 0
    pending_themes: int = 0


def _ensure_unique_id(candidate: str, used_ids: set[str]) -> str:
    if candidate not in used_ids:
        used_ids.add(candidate)
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in used_ids:
        suffix += 1
    unique = f"{candidate}_{suffix}"
    used_ids.add(unique)
    return unique


class OntologyRegistry(BaseModel):
    """Official stock ontology registry with canonical definitions and suggestion queue."""

    version: int = 1
    relations: list[RelationSpec] = Field(default_factory=list)
    companies: list[CompanySpec] = Field(default_factory=list)
    themes: list[ThemeSpec] = Field(default_factory=list)
    facet_aliases: dict[str, dict[str, str]] = Field(default_factory=dict)
    suggestions: RegistrySuggestions = Field(default_factory=RegistrySuggestions)

    @staticmethod
    def _default_facets_for_norm(spec: RelationSpec, norm_relation: str) -> dict[str, Any]:
        for alias_key, alias_facets in spec.alias_facets.items():
            if normalize_relation_name(alias_key) == norm_relation:
                return dict(alias_facets)
        return {}

    def resolve_relation(self, raw_relation: str) -> RelationMatch | None:
        """Resolve a relation name to its canonical registry entry, alias, or inverse."""
        norm = normalize_relation_name(raw_relation)
        if not norm:
            return None

        for spec in self.relations:
            if normalize_relation_name(spec.name) == norm:
                return RelationMatch(
                    canonical=spec.name,
                    spec=spec,
                    match_kind="exact",
                    flip_direction=False,
                    default_facets=self._default_facets_for_norm(spec, norm),
                )

        for spec in self.relations:
            if any(normalize_relation_name(alias) == norm for alias in spec.aliases):
                return RelationMatch(
                    canonical=spec.name,
                    spec=spec,
                    match_kind="alias",
                    flip_direction=False,
                    default_facets=self._default_facets_for_norm(spec, norm),
                )

        for spec in self.relations:
            if any(normalize_relation_name(inv) == norm for inv in spec.inverse_aliases):
                return RelationMatch(
                    canonical=spec.name,
                    spec=spec,
                    match_kind="inverse",
                    flip_direction=True,
                    default_facets=self._default_facets_for_norm(spec, norm),
                )

        return None

    def canonicalize_edge(
        self,
        raw_relation: str,
        *,
        from_id: str,
        from_type: str,
        from_entity_type: str | None = None,
        to_id: str,
        to_type: str,
        to_entity_type: str | None = None,
        facets: dict[str, Any] | None = None,
    ) -> CanonicalEdgeResult:
        """Normalize relation name, alias facets, endpoint direction, and symmetry against the registry."""
        f_type = str(from_type).strip().lower()
        t_type = str(to_type).strip().lower()
        f_et = from_entity_type.strip().lower() if from_entity_type else None
        t_et = to_entity_type.strip().lower() if to_entity_type else None
        merged_facets = dict(facets or {})

        match = self.resolve_relation(raw_relation)
        if match is None:
            norm = normalize_relation_name(raw_relation) or raw_relation.strip()
            return CanonicalEdgeResult(
                relation=norm,
                from_id=from_id,
                to_id=to_id,
                from_type=f_type,
                from_entity_type=f_et,
                to_type=t_type,
                to_entity_type=t_et,
                facets=merged_facets,
                matched=False,
                symmetric=False,
                flipped=False,
            )

        for k, v in match.default_facets.items():
            if k not in merged_facets or merged_facets[k] in (None, "", []):
                merged_facets[k] = v

        # Promote entity<->theme RELATES_TO into canonical EXPOSED_TO.
        if match.canonical == "RELATES_TO" and {f_type, t_type} == {"entity", "theme"}:
            exposed_match = self.resolve_relation("EXPOSED_TO")
            if exposed_match is not None:
                match = exposed_match
                for k, v in match.default_facets.items():
                    if k not in merged_facets or merged_facets[k] in (None, "", []):
                        merged_facets[k] = v

        cur_from = (to_id, t_type, t_et) if match.flip_direction else (from_id, f_type, f_et)
        cur_to = (from_id, f_type, f_et) if match.flip_direction else (to_id, t_type, t_et)
        flipped = match.flip_direction

        spec = match.spec
        forward_ok = matches_type_spec(cur_from[1], cur_from[2], spec.from_types) and matches_type_spec(
            cur_to[1], cur_to[2], spec.to_types
        )
        swapped_ok = matches_type_spec(cur_to[1], cur_to[2], spec.from_types) and matches_type_spec(
            cur_from[1], cur_from[2], spec.to_types
        )
        if not forward_ok and swapped_ok:
            cur_from, cur_to = cur_to, cur_from
            flipped = not flipped

        if spec.symmetric and cur_from[0] > cur_to[0]:
            cur_from, cur_to = cur_to, cur_from
            flipped = not flipped

        return CanonicalEdgeResult(
            relation=match.canonical,
            from_id=cur_from[0],
            to_id=cur_to[0],
            from_type=cur_from[1],
            from_entity_type=cur_from[2],
            to_type=cur_to[1],
            to_entity_type=cur_to[2],
            facets=merged_facets,
            matched=True,
            symmetric=spec.symmetric,
            flipped=flipped,
        )

    def resolve_company(
        self,
        name: str,
        *,
        ticker: str | None = None,
        aliases: list[str] | None = None,
    ) -> CompanyMatch | None:
        """Resolve a company by normalized ticker, canonical name, or aliases."""
        norm_ticker = normalize_ticker(ticker)
        if norm_ticker:
            for spec in self.companies:
                if normalize_ticker(spec.ticker) == norm_ticker:
                    return CompanyMatch(spec=spec, match_kind="ticker")

        name_key = normalize_name_key(name)
        if name_key:
            for spec in self.companies:
                if normalize_name_key(spec.name) == name_key:
                    return CompanyMatch(spec=spec, match_kind="exact")

        alias_list = aliases or []
        for spec in self.companies:
            spec_name_key = normalize_name_key(spec.name)
            spec_alias_keys = {normalize_name_key(a) for a in spec.aliases if a.strip()}
            spec_ticker_norm = normalize_ticker(spec.ticker)

            if name_key and name_key in spec_alias_keys:
                return CompanyMatch(spec=spec, match_kind="alias")

            for alias in alias_list:
                alias_key = normalize_name_key(alias)
                if not alias_key:
                    continue
                if alias_key == spec_name_key or alias_key in spec_alias_keys:
                    return CompanyMatch(spec=spec, match_kind="alias")
                if spec_ticker_norm and normalize_ticker(alias) == spec_ticker_norm:
                    return CompanyMatch(spec=spec, match_kind="alias")

        return None

    def resolve_theme(
        self,
        name: str,
        *,
        aliases: list[str] | None = None,
    ) -> ThemeMatch | None:
        """Resolve a theme by canonical name or aliases."""
        name_key = normalize_name_key(name)
        if name_key:
            for spec in self.themes:
                if normalize_name_key(spec.name) == name_key:
                    return ThemeMatch(spec=spec, match_kind="exact")

        alias_list = aliases or []
        for spec in self.themes:
            spec_name_key = normalize_name_key(spec.name)
            spec_alias_keys = {normalize_name_key(a) for a in spec.aliases if a.strip()}

            if name_key and name_key in spec_alias_keys:
                return ThemeMatch(spec=spec, match_kind="alias")

            for alias in alias_list:
                alias_key = normalize_name_key(alias)
                if alias_key and (alias_key == spec_name_key or alias_key in spec_alias_keys):
                    return ThemeMatch(spec=spec, match_kind="alias")

        return None

    def resolve_facet_key(self, node_type: str, key: str) -> str:
        """Return canonical facet key for `node_type` if an alias is registered."""
        return self.facet_aliases.get(node_type, {}).get(key, key)

    def get_relations_by_group(self, group: str) -> set[str]:
        """Return canonical relation names assigned to `group`."""
        return {r.name for r in self.relations if r.traversal_group == group}

    def sync_suggestions(
        self,
        unmapped_relations: list[RelationSuggestion],
        unmapped_companies: list[CompanySuggestion],
        unmapped_themes: list[ThemeSuggestion],
        *,
        now_iso: str | None = None,
    ) -> SuggestionSyncSummary:
        """Merge newly audited unmapped items into `suggestions` while preserving admin decisions."""
        ts = now_iso or _utc_now_iso()
        counts = {"added": 0, "updated": 0, "auto_resolved": 0, "preserved_decided": 0}

        # 1. Relations
        rel_by_key: dict[str, RelationSuggestion] = {
            normalize_relation_name(s.name): s for s in self.suggestions.relations
        }
        rel_ids = {s.id for s in self.suggestions.relations}
        for existing in self.suggestions.relations:
            if existing.status == "pending":
                match = self.resolve_relation(existing.name)
                if match is not None:
                    existing.status = "approved" if match.match_kind == "exact" else "aliased"
                    existing.mapped_to = match.canonical
                    existing.last_seen_at = ts
                    counts["auto_resolved"] += 1

        for incoming in unmapped_relations:
            key = normalize_relation_name(incoming.name)
            existing = rel_by_key.get(key)
            if existing is not None:
                existing.edge_count = incoming.edge_count
                existing.observed_signatures = list(incoming.observed_signatures)
                existing.sample_edges = list(incoming.sample_edges)
                existing.last_seen_at = ts
                if existing.status != "pending":
                    counts["preserved_decided"] += 1
                else:
                    counts["updated"] += 1
            else:
                new_item = incoming.model_copy(
                    update={
                        "id": _ensure_unique_id(incoming.id, rel_ids),
                        "status": "pending",
                        "first_seen_at": ts,
                        "last_seen_at": ts,
                    }
                )
                self.suggestions.relations.append(new_item)
                rel_by_key[key] = new_item
                counts["added"] += 1

        self.suggestions.relations.sort(key=lambda r: (-r.edge_count, r.name))

        # 2. Companies
        co_by_key: dict[str, CompanySuggestion] = {
            normalize_name_key(s.name): s for s in self.suggestions.companies
        }
        co_ids = {s.id for s in self.suggestions.companies}
        for existing in self.suggestions.companies:
            if existing.status == "pending":
                match = self.resolve_company(
                    existing.name,
                    ticker=existing.ticker or existing.raw_ticker,
                    aliases=existing.aliases,
                )
                if match is not None:
                    is_same_name = (
                        normalize_name_key(existing.name)
                        == normalize_name_key(match.spec.name)
                    )
                    existing.status = "approved" if is_same_name else "aliased"
                    existing.mapped_to = match.spec.name
                    existing.last_seen_at = ts
                    counts["auto_resolved"] += 1

        for incoming in unmapped_companies:
            key = normalize_name_key(incoming.name)
            existing = co_by_key.get(key)
            if existing is not None:
                existing.node_id = incoming.node_id
                existing.ticker = incoming.ticker
                existing.raw_ticker = incoming.raw_ticker
                existing.sector = incoming.sector
                existing.aliases = list(incoming.aliases)
                existing.summary = incoming.summary
                existing.signal_count = incoming.signal_count
                existing.has_consensus = incoming.has_consensus
                existing.consensus_stance = incoming.consensus_stance
                existing.nearest_official = incoming.nearest_official
                existing.last_seen_at = ts
                if existing.status != "pending":
                    counts["preserved_decided"] += 1
                else:
                    counts["updated"] += 1
            else:
                new_item = incoming.model_copy(
                    update={
                        "id": _ensure_unique_id(incoming.id, co_ids),
                        "status": "pending",
                        "first_seen_at": ts,
                        "last_seen_at": ts,
                    }
                )
                self.suggestions.companies.append(new_item)
                co_by_key[key] = new_item
                counts["added"] += 1

        self.suggestions.companies.sort(
            key=lambda c: (0 if c.has_consensus else 1, -c.signal_count, c.name.casefold())
        )

        # 3. Themes
        thm_by_key: dict[str, ThemeSuggestion] = {
            normalize_name_key(s.name): s for s in self.suggestions.themes
        }
        thm_ids = {s.id for s in self.suggestions.themes}
        for existing in self.suggestions.themes:
            if existing.status == "pending":
                match = self.resolve_theme(existing.name, aliases=existing.aliases)
                if match is not None:
                    is_same_name = (
                        normalize_name_key(existing.name)
                        == normalize_name_key(match.spec.name)
                    )
                    existing.status = "approved" if is_same_name else "aliased"
                    existing.mapped_to = match.spec.name
                    existing.last_seen_at = ts
                    counts["auto_resolved"] += 1

        for incoming in unmapped_themes:
            key = normalize_name_key(incoming.name)
            existing = thm_by_key.get(key)
            if existing is not None:
                existing.node_id = incoming.node_id
                existing.stage = incoming.stage
                existing.aliases = list(incoming.aliases)
                existing.summary = incoming.summary
                existing.company_count = incoming.company_count
                existing.nearest_official = incoming.nearest_official
                existing.last_seen_at = ts
                if existing.status != "pending":
                    counts["preserved_decided"] += 1
                else:
                    counts["updated"] += 1
            else:
                new_item = incoming.model_copy(
                    update={
                        "id": _ensure_unique_id(incoming.id, thm_ids),
                        "status": "pending",
                        "first_seen_at": ts,
                        "last_seen_at": ts,
                    }
                )
                self.suggestions.themes.append(new_item)
                thm_by_key[key] = new_item
                counts["added"] += 1

        self.suggestions.themes.sort(
            key=lambda t: (
                t.nearest_official.distance if t.nearest_official is not None else 9.9,
                t.name.casefold(),
            )
        )

        return SuggestionSyncSummary(
            added=counts["added"],
            updated=counts["updated"],
            auto_resolved=counts["auto_resolved"],
            preserved_decided=counts["preserved_decided"],
            pending_relations=sum(
                1 for s in self.suggestions.relations if s.status == "pending"
            ),
            pending_companies=sum(
                1 for s in self.suggestions.companies if s.status == "pending"
            ),
            pending_themes=sum(1 for s in self.suggestions.themes if s.status == "pending"),
        )


def create_minimal_registry() -> OntologyRegistry:
    """Create the minimal starter official ontology registry."""
    return OntologyRegistry(
        version=1,
        relations=[
            RelationSpec(
                name="ABOUT",
                description="Connects an event or view to the entity or theme it concerns.",
                from_types=["event", "view"],
                to_types=["entity", "theme"],
                traversal_group="core",
            ),
            RelationSpec(
                name="AUTHORED_BY",
                description="Connects an event or view to the authoring person or institution.",
                from_types=["event", "view"],
                to_types=["entity:person", "entity:institution"],
                traversal_group="provenance",
            ),
            RelationSpec(
                name="SUPPORTS",
                description="Indicates an event, view, or theme provides supporting evidence.",
                from_types=["event", "view", "theme"],
                to_types=["view", "theme"],
                aliases=["CORROBORATES"],
                traversal_group="evidence",
            ),
            RelationSpec(
                name="CONTRADICTS",
                description="Indicates an event, view, or theme challenges or weakens a view or theme.",
                from_types=["event", "view", "theme"],
                to_types=["view", "theme"],
                traversal_group="evidence",
            ),
            RelationSpec(
                name="SUPERSEDES",
                description="Marks a newer consensus view replacing a prior consensus view.",
                from_types=["view"],
                to_types=["view"],
                traversal_group="consensus",
            ),
            RelationSpec(
                name="RELATES_TO",
                description="Connects an event or view to a theme.",
                from_types=["event", "view"],
                to_types=["theme"],
                aliases=["RELATED_TO"],
                traversal_group="core",
            ),
            RelationSpec(
                name="BUY",
                description="Purchasing relationship from buyer company to seller company.",
                from_types=["entity:company"],
                to_types=["entity:company"],
                aliases=["CUSTOMER_OF", "BUYS_FROM"],
                inverse_aliases=["SUPPLIES_TO"],
                traversal_group="second_order_entity",
            ),
            RelationSpec(
                name="COMPETE",
                description="Competitive rivalry between peer companies.",
                from_types=["entity:company"],
                to_types=["entity:company"],
                aliases=["COMPETES_WITH"],
                symmetric=True,
                traversal_group="second_order_entity",
            ),
            RelationSpec(
                name="OWNS",
                description="Ownership stake from a parent company to a company or institution.",
                from_types=["entity:company"],
                to_types=["entity:company", "entity:institution"],
                inverse_aliases=["SUBSIDIARY_OF"],
                traversal_group="second_order_entity",
            ),
            RelationSpec(
                name="WORKS_AT",
                description="Employment or affiliation link from a person to a company or institution.",
                from_types=["entity:person"],
                to_types=["entity:company", "entity:institution"],
                inverse_aliases=["HAS_EMPLOYEE"],
                traversal_group="org",
            ),
            RelationSpec(
                name="EXPOSED_TO",
                description="Thematic exposure connecting an entity to a theme with a polarity sentiment facet.",
                from_types=["entity"],
                to_types=["theme"],
                aliases=["BENEFITS_FROM", "HURT_BY"],
                alias_facets={
                    "BENEFITS_FROM": {"sentiment": "positive"},
                    "HURT_BY": {"sentiment": "negative"},
                },
                traversal_group="theme_exposure",
            ),
        ],
        companies=[
            CompanySpec(
                name="Apple",
                ticker="AAPL",
                sector="Technology",
                aliases=["AAPL", "Apple Inc."],
            ),
            CompanySpec(
                name="Microsoft",
                ticker="MSFT",
                sector="Technology",
                aliases=["MSFT"],
            ),
            CompanySpec(
                name="NVIDIA",
                ticker="NVDA",
                sector="Semiconductors",
                aliases=["NVDA", "Nvidia Corporation"],
            ),
            CompanySpec(
                name="TSMC",
                ticker="TSM",
                sector="Semiconductors",
                aliases=["TSM", "Taiwan Semiconductor Manufacturing Company"],
            ),
            CompanySpec(
                name="Vertiv",
                ticker="VRT",
                sector="Industrials",
                aliases=["VRT", "Vertiv Holdings Co."],
            ),
        ],
        themes=[
            ThemeSpec(
                name="AI Infrastructure & Capex",
                stage="accelerating",
                description="Hyperscaler capital expenditure on AI compute clusters, networking, and data centers.",
                aliases=["AI Data Center Buildout"],
            ),
            ThemeSpec(
                name="AI Data Center Power & Cooling",
                stage="accelerating",
                description="Grid power, thermal density, and liquid cooling constraints in high-density AI racks.",
                aliases=["AI Data Center Power Bottleneck"],
            ),
            ThemeSpec(
                name="Enterprise AI Monetization",
                stage="accelerating",
                description="Monetization of enterprise AI via cloud workloads, seats, and usage-based pricing.",
                aliases=[],
            ),
            ThemeSpec(
                name="On-Device AI & Edge Computing",
                stage="accelerating",
                description="Shift toward local inference on consumer devices and edge silicon.",
                aliases=["Local AI", "Edge Intelligence"],
            ),
            ThemeSpec(
                name="Semiconductor Supply Chain Diversification",
                stage="consensus",
                description="Geographic diversification of leading-edge semiconductor fabrication and assembly.",
                aliases=["Supply Chain Resilience"],
            ),
        ],
        facet_aliases={
            "view": {
                "catalyst_to_watch": "catalysts_to_watch",
                "key_catalysts_to_watch": "catalysts_to_watch",
                "primary_risk": "key_risks",
                "risk": "key_risks",
                "primary_driver": "driver",
            }
        },
        suggestions=RegistrySuggestions(),
    )


def load_registry(path: Path | str) -> OntologyRegistry:
    """Load and validate an official ontology registry JSON file."""
    reg_path = Path(path)
    if not reg_path.exists():
        raise FileNotFoundError(  # noqa: TRY003
            f"Ontology registry not found at {reg_path}. "
            "Create it or pass `--registry` with a valid ontology_registry.json path."
        )
    raw = reg_path.read_text(encoding="utf-8")
    return OntologyRegistry.model_validate_json(raw)


def save_registry(registry: OntologyRegistry, path: Path | str) -> None:
    """Atomically serialize an OntologyRegistry to UTF-8 JSON."""
    reg_path = Path(path)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    payload = registry.model_dump_json(indent=2) + "\n"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=reg_path.parent,
            prefix=f".{reg_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, reg_path)
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
