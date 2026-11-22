"""Offline read-only audit engine checking ontology.db against the official registry."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from stock_ontology.db import OntologyDB
from stock_ontology.models import Node, normalize_sentiment
from stock_ontology.registry import (
    CompanySpec,
    CompanySuggestion,
    NearestMatch,
    ObservedSignature,
    OntologyRegistry,
    RelationSuggestion,
    SampleEdge,
    ThemeSuggestion,
    make_suggestion_id,
    matches_type_spec,
    normalize_relation_name,
    normalize_ticker,
)
from stock_ontology.vocab import out_of_vocabulary_node_facets

ALIAS_STOP_WORDS = {
    "inc",
    "corp",
    "co",
    "ltd",
    "llc",
    "plc",
    "holdings",
    "holding",
    "group",
    "company",
    "corporation",
    "limited",
    "the",
    "of",
    "and",
}


class AuditSummary(BaseModel):
    """High-level metrics produced by an ontology audit."""

    total_edges: int = 0
    mapped_exact_edges: int = 0
    mapped_alias_edges: int = 0
    mapped_inverse_edges: int = 0
    unmapped_edges: int = 0
    distinct_unmapped_relations: int = 0
    direction_issue_edges: int = 0
    reciprocal_contradiction_pairs: int = 0
    total_companies: int = 0
    mapped_companies: int = 0
    unmapped_companies: int = 0
    total_themes: int = 0
    mapped_themes: int = 0
    unmapped_themes: int = 0
    near_duplicate_theme_pairs: int = 0
    duplicate_company_candidate_pairs: int = 0
    suspicious_alias_count: int = 0
    ticker_normalization_issue_count: int = 0
    facet_alias_hit_count: int = 0
    events_missing_sentiment: int = 0
    total_events: int = 0
    views_missing_sentiment: int = 0
    total_views: int = 0
    out_of_vocabulary_value_count: int = 0


class RelationNormalizationHit(BaseModel):
    """Edge relation in the DB that matched an official alias or inverse alias."""

    raw_relation: str
    canonical_relation: str
    match_kind: Literal["alias", "inverse"]
    flip_direction: bool
    count: int


class DirectionIssue(BaseModel):
    """Mapped edge whose endpoint node types violate the registry's domain/range."""

    relation: str
    canonical_relation: str
    issue_type: Literal["reversed_direction", "domain_range_mismatch"]
    observed_signature: str
    expected_signature: str
    count: int
    sample_edges: list[SampleEdge] = Field(default_factory=list)


class MappedCompanyRecord(BaseModel):
    """Company entity in DB resolved to an official registry company."""

    node_id: str
    db_name: str
    official_name: str
    match_kind: Literal["ticker", "exact", "alias"]
    raw_ticker: str | None = None
    normalized_ticker: str | None = None


class MappedThemeRecord(BaseModel):
    """Theme node in DB resolved to an official registry theme."""

    node_id: str
    db_name: str
    official_name: str
    match_kind: Literal["exact", "alias"]


class TickerNormalizationIssue(BaseModel):
    """Company ticker containing exchange prefix or non-canonical formatting."""

    node_id: str
    name: str
    raw_ticker: str
    normalized_ticker: str | None = None


class NearDuplicatePair(BaseModel):
    """Potential duplicate company or theme pair detected via similarity or ticker."""

    node_type: Literal["company", "theme"]
    node_a_id: str
    node_a_name: str
    node_b_id: str
    node_b_name: str
    reason: Literal["vector_similarity", "shared_ticker"]
    distance: float | None = None


class SuspiciousAlias(BaseModel):
    """Entity alias flagged as a potential vector-distance false merge."""

    node_id: str
    node_name: str
    entity_type: str | None = None
    alias: str
    reason: Literal["conflicting_numeric_identifier", "disjoint_name_and_not_ticker"]


class FacetAliasHit(BaseModel):
    """Non-canonical facet key present in DB that maps to a canonical registry facet."""

    node_type: str
    raw_key: str
    canonical_key: str
    count: int


class OutOfVocabularyValue(BaseModel):
    """A stored enum facet value that is not a member of its `vocab` vocabulary."""

    node_type: str
    facet: str
    value: str
    count: int


class ReciprocalContradiction(BaseModel):
    """Asymmetric official relation observed in opposing directions between the same pair."""

    relation: str
    node_a_id: str
    node_a_name: str
    node_b_id: str
    node_b_name: str
    forward_count: int
    reverse_count: int


class AuditReport(BaseModel):
    """Full structured output of a read-only ontology audit."""

    summary: AuditSummary
    relation_normalization_hits: list[RelationNormalizationHit] = Field(default_factory=list)
    direction_issues: list[DirectionIssue] = Field(default_factory=list)
    reciprocal_contradictions: list[ReciprocalContradiction] = Field(default_factory=list)
    mapped_companies: list[MappedCompanyRecord] = Field(default_factory=list)
    mapped_themes: list[MappedThemeRecord] = Field(default_factory=list)
    unmapped_relations: list[RelationSuggestion] = Field(default_factory=list)
    unmapped_companies: list[CompanySuggestion] = Field(default_factory=list)
    unmapped_themes: list[ThemeSuggestion] = Field(default_factory=list)
    near_duplicate_themes: list[NearDuplicatePair] = Field(default_factory=list)
    duplicate_company_candidates: list[NearDuplicatePair] = Field(default_factory=list)
    suspicious_aliases: list[SuspiciousAlias] = Field(default_factory=list)
    ticker_normalization_issues: list[TickerNormalizationIssue] = Field(default_factory=list)
    facet_alias_hits: list[FacetAliasHit] = Field(default_factory=list)
    out_of_vocabulary_values: list[OutOfVocabularyValue] = Field(default_factory=list)


EdgeRegistryStatus = Literal[
    "official", "alias", "inverse", "reversed", "mismatch", "unmapped"
]


class EdgeClassification(BaseModel):
    """Classification of a single graph edge against the official ontology registry."""

    status: EdgeRegistryStatus
    canonical_relation: str | None = None
    match_kind: Literal["exact", "alias", "inverse"] | None = None
    flip_direction: bool = False
    issue_type: Literal["reversed_direction", "domain_range_mismatch"] | None = None
    expected_signature: str | None = None


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Compute cosine distance (1 - cos_sim) between two float vectors."""
    if len(a) != len(b) or not a:
        return 1.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 1.0
    return max(0.0, 1.0 - dot / (na * nb))


def _node_type_label(node_type: str, entity_type: str | None) -> str:
    if node_type == "entity" and entity_type:
        return f"entity:{entity_type}"
    return node_type


def classify_edge_against_registry(
    registry: OntologyRegistry,
    raw_relation: str,
    *,
    from_type: str,
    from_entity_type: str | None,
    to_type: str,
    to_entity_type: str | None,
) -> EdgeClassification:
    """Classify a directed edge's relation and endpoint types against `registry`."""
    match = registry.resolve_relation(raw_relation)
    if match is None:
        return EdgeClassification(status="unmapped")

    eff_from = (to_type, to_entity_type) if match.flip_direction else (from_type, from_entity_type)
    eff_to = (from_type, from_entity_type) if match.flip_direction else (to_type, to_entity_type)

    forward_ok = matches_type_spec(
        eff_from[0], eff_from[1], match.spec.from_types
    ) and matches_type_spec(eff_to[0], eff_to[1], match.spec.to_types)

    if forward_ok:
        status: EdgeRegistryStatus = (
            "official" if match.match_kind == "exact" else match.match_kind
        )
        return EdgeClassification(
            status=status,
            canonical_relation=match.canonical,
            match_kind=match.match_kind,
            flip_direction=match.flip_direction,
        )

    swapped_ok = matches_type_spec(
        eff_to[0], eff_to[1], match.spec.from_types
    ) and matches_type_spec(eff_from[0], eff_from[1], match.spec.to_types)
    issue_type: Literal["reversed_direction", "domain_range_mismatch"] = (
        "reversed_direction" if swapped_ok else "domain_range_mismatch"
    )
    status = "reversed" if swapped_ok else "mismatch"
    expected_from = "|".join(match.spec.from_types) or "*"
    expected_to = "|".join(match.spec.to_types) or "*"
    return EdgeClassification(
        status=status,
        canonical_relation=match.canonical,
        match_kind=match.match_kind,
        flip_direction=match.flip_direction,
        issue_type=issue_type,
        expected_signature=f"{expected_from} -> {expected_to}",
    )


def _word_tokens(text: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-z0-9]+", text.lower())
        if w not in ALIAS_STOP_WORDS
    ]


def _initials_variants(text: str) -> set[str]:
    raw_words = re.findall(r"[a-z0-9]+", text.lower())
    sig_words = _word_tokens(text)
    variants: set[str] = set()
    for words in (raw_words, sig_words):
        if len(words) >= 2:
            variants.add("".join(w[0] for w in words))
    return variants


def _find_suspicious_aliases(
    node: Node,
    *,
    official_aliases: set[str] | None = None,
    official_ticker: str | None = None,
) -> list[SuspiciousAlias]:
    """Flag entity aliases that likely came from vector false-merges."""
    if not node.aliases:
        return []

    entity_type = str(node.facets.get("entity_type") or "") or None
    raw_ticker = node.facets.get("ticker")
    node_norm_ticker = normalize_ticker(str(raw_ticker)) if raw_ticker is not None else None
    name_clean = node.name.strip()
    name_cf = name_clean.casefold()
    name_alnum = re.sub(r"[^a-z0-9]", "", name_clean.lower())
    name_words = _word_tokens(name_clean)
    name_word_set = set(name_words)
    name_non_num = {w for w in name_word_set if not w.isdigit()}
    name_nums = set(re.findall(r"\d+", name_clean))
    name_initials = _initials_variants(name_clean)

    flagged: list[SuspiciousAlias] = []
    for raw_alias in node.aliases:
        alias = raw_alias.strip()
        if not alias:
            continue
        alias_cf = alias.casefold()
        if alias_cf == name_cf:
            continue
        if official_aliases and alias_cf in official_aliases:
            continue
        alias_norm_ticker = normalize_ticker(alias)
        if node_norm_ticker and alias_norm_ticker == node_norm_ticker:
            continue
        if official_ticker and alias_norm_ticker == official_ticker:
            continue

        alias_words = _word_tokens(alias)
        alias_word_set = set(alias_words)
        alias_non_num = {w for w in alias_word_set if not w.isdigit()}
        alias_nums = set(re.findall(r"\d+", alias))

        # Check conflicting numeric identifiers (e.g. Fab 20 vs Fab 22) BEFORE shared-word check.
        if (
            name_non_num & alias_non_num
            and name_nums
            and alias_nums
            and name_nums.isdisjoint(alias_nums)
        ):
            flagged.append(
                SuspiciousAlias(
                    node_id=node.id,
                    node_name=node.name,
                    entity_type=entity_type,
                    alias=alias,
                    reason="conflicting_numeric_identifier",
                )
            )
            continue

        # Safe if sharing at least one significant word token.
        if name_word_set & alias_word_set:
            continue

        # Safe if substring match (length >= 3, e.g. Citi <-> Citigroup).
        alias_alnum = re.sub(r"[^a-z0-9]", "", alias.lower())
        if (
            len(name_alnum) >= 3
            and len(alias_alnum) >= 3
            and (name_alnum in alias_alnum or alias_alnum in name_alnum)
        ):
            continue

        # Safe if initials match in either direction (e.g. PCC <-> Private Cloud Compute).
        alias_initials = _initials_variants(alias)
        if (alias_alnum and alias_alnum in name_initials) or (
            name_alnum and name_alnum in alias_initials
        ):
            continue

        flagged.append(
            SuspiciousAlias(
                node_id=node.id,
                node_name=node.name,
                entity_type=entity_type,
                alias=alias,
                reason="disjoint_name_and_not_ticker",
            )
        )

    return flagged


def run_ontology_audit(
    db: OntologyDB,
    registry: OntologyRegistry,
    *,
    theme_similarity_threshold: float = 0.35,
    entity_similarity_threshold: float = 0.20,
    company_nearest_threshold: float = 0.35,
) -> AuditReport:
    """Audit an OntologyDB against `registry` without modifying the database."""
    # ------------------------------------------------------------------
    # 1. Edge relations audit
    # ------------------------------------------------------------------
    edges = db.list_edges_with_endpoints()
    mapped_exact_edges = 0
    mapped_alias_edges = 0
    mapped_inverse_edges = 0
    unmapped_edges = 0
    direction_issue_edges = 0

    norm_hit_counts: dict[tuple[str, str, Literal["alias", "inverse"], bool], int] = defaultdict(int)
    dir_issue_counts: dict[
        tuple[str, str, Literal["reversed_direction", "domain_range_mismatch"], str, str], int
    ] = defaultdict(int)
    dir_issue_samples: dict[
        tuple[str, str, Literal["reversed_direction", "domain_range_mismatch"], str, str],
        list[SampleEdge],
    ] = defaultdict(list)

    unmapped_rel_counts: dict[str, int] = defaultdict(int)
    unmapped_rel_sigs: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    unmapped_rel_samples: dict[str, list[SampleEdge]] = defaultdict(list)
    asym_pair_dirs: dict[tuple[str, str, str], dict[str, Any]] = {}

    for edge in edges:
        raw_rel = edge["relation"]
        from_type = edge["from_type"]
        from_et = edge["from_entity_type"]
        to_type = edge["to_type"]
        to_et = edge["to_entity_type"]
        sample = SampleEdge(
            from_name=edge["from_name"],
            relation=raw_rel,
            to_name=edge["to_name"],
        )

        cls = classify_edge_against_registry(
            registry,
            raw_rel,
            from_type=from_type,
            from_entity_type=from_et,
            to_type=to_type,
            to_entity_type=to_et,
        )
        if cls.status == "unmapped":
            unmapped_edges += 1
            norm_rel = normalize_relation_name(raw_rel)
            unmapped_rel_counts[norm_rel] += 1
            unmapped_rel_sigs[norm_rel][
                (_node_type_label(from_type, from_et), _node_type_label(to_type, to_et))
            ] += 1
            if len(unmapped_rel_samples[norm_rel]) < 3:
                unmapped_rel_samples[norm_rel].append(sample)
            continue

        assert cls.canonical_relation is not None
        if cls.match_kind == "exact":
            mapped_exact_edges += 1
        elif cls.match_kind == "alias":
            mapped_alias_edges += 1
            norm_hit_counts[(raw_rel, cls.canonical_relation, "alias", False)] += 1
        elif cls.match_kind == "inverse":
            mapped_inverse_edges += 1
            norm_hit_counts[(raw_rel, cls.canonical_relation, "inverse", True)] += 1

        if cls.issue_type is not None:
            observed_sig = (
                f"{_node_type_label(from_type, from_et)} -> {_node_type_label(to_type, to_et)}"
            )
            expected_sig = cls.expected_signature or "* -> *"
            key = (
                raw_rel,
                cls.canonical_relation,
                cls.issue_type,
                observed_sig,
                expected_sig,
            )
            dir_issue_counts[key] += 1
            if len(dir_issue_samples[key]) < 3:
                dir_issue_samples[key].append(sample)
            direction_issue_edges += 1

        canon = registry.canonicalize_edge(
            raw_rel,
            from_id=edge["from_id"],
            from_type=from_type,
            from_entity_type=from_et,
            to_id=edge["to_id"],
            to_type=to_type,
            to_entity_type=to_et,
            facets=edge["facets"],
        )
        if canon.matched and not canon.symmetric and canon.from_id != canon.to_id:
            if canon.from_id < canon.to_id:
                pair_key = (canon.relation, canon.from_id, canon.to_id)
                a_name = edge["from_name"] if canon.from_id == edge["from_id"] else edge["to_name"]
                b_name = edge["to_name"] if canon.to_id == edge["to_id"] else edge["from_name"]
                is_fwd = True
            else:
                pair_key = (canon.relation, canon.to_id, canon.from_id)
                a_name = edge["to_name"] if canon.to_id == edge["to_id"] else edge["from_name"]
                b_name = edge["from_name"] if canon.from_id == edge["from_id"] else edge["to_name"]
                is_fwd = False
            bucket = asym_pair_dirs.setdefault(
                pair_key,
                {"a_name": a_name, "b_name": b_name, "fwd": 0, "rev": 0},
            )
            if is_fwd:
                bucket["fwd"] += 1
            else:
                bucket["rev"] += 1

    reciprocal_contradictions = [
        ReciprocalContradiction(
            relation=rel,
            node_a_id=a_id,
            node_a_name=info["a_name"],
            node_b_id=b_id,
            node_b_name=info["b_name"],
            forward_count=info["fwd"],
            reverse_count=info["rev"],
        )
        for (rel, a_id, b_id), info in sorted(
            asym_pair_dirs.items(),
            key=lambda kv: (kv[0][0], kv[1]["a_name"].casefold(), kv[1]["b_name"].casefold()),
        )
        if info["fwd"] > 0 and info["rev"] > 0
    ]

    relation_normalization_hits = [
        RelationNormalizationHit(
            raw_relation=raw_rel,
            canonical_relation=canon,
            match_kind=kind,
            flip_direction=flip,
            count=cnt,
        )
        for (raw_rel, canon, kind, flip), cnt in sorted(
            norm_hit_counts.items(), key=lambda kv: (-kv[1], kv[0][0])
        )
    ]

    direction_issues = [
        DirectionIssue(
            relation=rel,
            canonical_relation=canon,
            issue_type=itype,
            observed_signature=obs_sig,
            expected_signature=exp_sig,
            count=cnt,
            sample_edges=dir_issue_samples[(rel, canon, itype, obs_sig, exp_sig)],
        )
        for (rel, canon, itype, obs_sig, exp_sig), cnt in sorted(
            dir_issue_counts.items(), key=lambda kv: (-kv[1], kv[0][0])
        )
    ]

    unmapped_relations = [
        RelationSuggestion(
            id=make_suggestion_id("sug_rel", rel_name),
            name=rel_name,
            edge_count=cnt,
            observed_signatures=[
                ObservedSignature(from_type=ft, to_type=tt, count=sc)
                for (ft, tt), sc in sorted(
                    unmapped_rel_sigs[rel_name].items(), key=lambda kv: (-kv[1], kv[0])
                )
            ],
            sample_edges=unmapped_rel_samples[rel_name],
        )
        for rel_name, cnt in sorted(
            unmapped_rel_counts.items(), key=lambda kv: (-kv[1], kv[0])
        )
    ]

    # ------------------------------------------------------------------
    # 2. Companies, entities, and embeddings audit
    # ------------------------------------------------------------------
    all_entities = db.list_nodes(node_type="entity", limit=5000)
    embeddings = db.get_node_embeddings()

    companies = sorted(
        (
            n
            for n in all_entities
            if n.facets.get("entity_type") == "company"
        ),
        key=lambda n: n.name.casefold(),
    )

    mapped_companies: list[MappedCompanyRecord] = []
    official_company_specs: dict[str, CompanySpec] = {}
    official_company_vecs: list[tuple[str, list[float]]] = []
    unmapped_company_nodes: list[Node] = []
    ticker_normalization_issues: list[TickerNormalizationIssue] = []

    for node in companies:
        raw_ticker_val = node.facets.get("ticker")
        raw_ticker = str(raw_ticker_val).strip() if raw_ticker_val not in (None, "") else None
        norm_ticker = normalize_ticker(raw_ticker)
        if raw_ticker is not None and raw_ticker != norm_ticker:
            ticker_normalization_issues.append(
                TickerNormalizationIssue(
                    node_id=node.id,
                    name=node.name,
                    raw_ticker=raw_ticker,
                    normalized_ticker=norm_ticker,
                )
            )

        co_match = registry.resolve_company(
            node.name, ticker=raw_ticker, aliases=node.aliases
        )
        if co_match is not None:
            mapped_companies.append(
                MappedCompanyRecord(
                    node_id=node.id,
                    db_name=node.name,
                    official_name=co_match.spec.name,
                    match_kind=co_match.match_kind,
                    raw_ticker=raw_ticker,
                    normalized_ticker=norm_ticker,
                )
            )
            official_company_specs[node.id] = co_match.spec
            if node.id in embeddings:
                official_company_vecs.append((co_match.spec.name, embeddings[node.id]))
        else:
            unmapped_company_nodes.append(node)

    unmapped_companies: list[CompanySuggestion] = []
    for node in unmapped_company_nodes:
        raw_ticker_val = node.facets.get("ticker")
        raw_ticker = str(raw_ticker_val).strip() if raw_ticker_val not in (None, "") else None
        norm_ticker = normalize_ticker(raw_ticker)
        sector_val = node.facets.get("sector")
        sector = str(sector_val).strip() if sector_val not in (None, "") else None
        signal_count = int(
            db.query_entity_signals(
                node.id, include_consensus=False, include_authored=False
            )["total_matched"]
        )
        cons = db.get_entity_consensus(node.id)

        nearest_official: NearestMatch | None = None
        if node.id in embeddings and official_company_vecs:
            vec = embeddings[node.id]
            best_name, best_dist = min(
                ((name, _cosine_distance(vec, ovec)) for name, ovec in official_company_vecs),
                key=lambda item: item[1],
            )
            if best_dist <= company_nearest_threshold:
                nearest_official = NearestMatch(name=best_name, distance=round(best_dist, 4))

        unmapped_companies.append(
            CompanySuggestion(
                id=make_suggestion_id("sug_co", node.name),
                name=node.name,
                node_id=node.id,
                ticker=norm_ticker,
                raw_ticker=raw_ticker,
                sector=sector,
                aliases=list(node.aliases),
                summary=node.summary,
                signal_count=signal_count,
                has_consensus=cons is not None,
                consensus_stance=str(cons.facets.get("stance")) if cons is not None else None,
                nearest_official=nearest_official,
            )
        )

    unmapped_companies.sort(
        key=lambda c: (0 if c.has_consensus else 1, -c.signal_count, c.name.casefold())
    )

    duplicate_company_candidates: list[NearDuplicatePair] = []
    for i in range(len(companies)):
        a = companies[i]
        ta = normalize_ticker(
            str(a.facets.get("ticker")) if a.facets.get("ticker") is not None else None
        )
        for j in range(i + 1, len(companies)):
            b = companies[j]
            tb = normalize_ticker(
                str(b.facets.get("ticker")) if b.facets.get("ticker") is not None else None
            )
            if ta and tb and ta == tb:
                duplicate_company_candidates.append(
                    NearDuplicatePair(
                        node_type="company",
                        node_a_id=a.id,
                        node_a_name=a.name,
                        node_b_id=b.id,
                        node_b_name=b.name,
                        reason="shared_ticker",
                        distance=None,
                    )
                )
                continue
            if a.id in embeddings and b.id in embeddings:
                dist = _cosine_distance(embeddings[a.id], embeddings[b.id])
                if dist < entity_similarity_threshold:
                    duplicate_company_candidates.append(
                        NearDuplicatePair(
                            node_type="company",
                            node_a_id=a.id,
                            node_a_name=a.name,
                            node_b_id=b.id,
                            node_b_name=b.name,
                            reason="vector_similarity",
                            distance=round(dist, 4),
                        )
                    )

    duplicate_company_candidates.sort(
        key=lambda p: (
            0 if p.reason == "shared_ticker" else 1,
            p.distance if p.distance is not None else 0.0,
            p.node_a_name.casefold(),
        )
    )

    # ------------------------------------------------------------------
    # 3. Themes audit
    # ------------------------------------------------------------------
    themes = sorted(db.list_nodes(node_type="theme", limit=5000), key=lambda t: t.name.casefold())
    mapped_themes: list[MappedThemeRecord] = []
    official_theme_vecs: list[tuple[str, list[float]]] = []
    unmapped_theme_nodes: list[Node] = []

    for theme in themes:
        thm_match = registry.resolve_theme(theme.name, aliases=theme.aliases)
        if thm_match is not None:
            mapped_themes.append(
                MappedThemeRecord(
                    node_id=theme.id,
                    db_name=theme.name,
                    official_name=thm_match.spec.name,
                    match_kind=thm_match.match_kind,
                )
            )
            if theme.id in embeddings:
                official_theme_vecs.append((thm_match.spec.name, embeddings[theme.id]))
        else:
            unmapped_theme_nodes.append(theme)

    unmapped_themes: list[ThemeSuggestion] = []
    for theme in unmapped_theme_nodes:
        company_count = len(
            db.find_theme_companies(theme.id, include_second_order=False)["first_order"]
        )
        nearest_official = None
        if theme.id in embeddings and official_theme_vecs:
            vec = embeddings[theme.id]
            best_name, best_dist = min(
                ((name, _cosine_distance(vec, ovec)) for name, ovec in official_theme_vecs),
                key=lambda item: item[1],
            )
            nearest_official = NearestMatch(name=best_name, distance=round(best_dist, 4))

        stage_val = theme.facets.get("stage")
        unmapped_themes.append(
            ThemeSuggestion(
                id=make_suggestion_id("sug_thm", theme.name),
                name=theme.name,
                node_id=theme.id,
                stage=str(stage_val).strip() if stage_val not in (None, "") else None,
                aliases=list(theme.aliases),
                summary=theme.summary,
                company_count=company_count,
                nearest_official=nearest_official,
            )
        )

    unmapped_themes.sort(
        key=lambda t: (
            t.nearest_official.distance if t.nearest_official is not None else 9.9,
            t.name.casefold(),
        )
    )

    near_duplicate_themes: list[NearDuplicatePair] = []
    for i in range(len(themes)):
        a = themes[i]
        if a.id not in embeddings:
            continue
        for j in range(i + 1, len(themes)):
            b = themes[j]
            if b.id not in embeddings:
                continue
            dist = _cosine_distance(embeddings[a.id], embeddings[b.id])
            if dist < theme_similarity_threshold:
                near_duplicate_themes.append(
                    NearDuplicatePair(
                        node_type="theme",
                        node_a_id=a.id,
                        node_a_name=a.name,
                        node_b_id=b.id,
                        node_b_name=b.name,
                        reason="vector_similarity",
                        distance=round(dist, 4),
                    )
                )

    near_duplicate_themes.sort(
        key=lambda p: (
            p.distance if p.distance is not None else 9.9,
            p.node_a_name.casefold(),
        )
    )

    # ------------------------------------------------------------------
    # 4. Suspicious aliases across all entities
    # ------------------------------------------------------------------
    suspicious_aliases: list[SuspiciousAlias] = []
    for node in sorted(all_entities, key=lambda n: n.name.casefold()):
        spec = official_company_specs.get(node.id)
        official_aliases: set[str] | None = None
        official_ticker: str | None = None
        if spec is not None:
            official_aliases = {a.strip().casefold() for a in spec.aliases if a.strip()}
            official_aliases.add(spec.name.strip().casefold())
            official_ticker = normalize_ticker(spec.ticker)
        suspicious_aliases.extend(
            _find_suspicious_aliases(
                node,
                official_aliases=official_aliases,
                official_ticker=official_ticker,
            )
        )

    # ------------------------------------------------------------------
    # 5. Facet drift & sentiment coverage
    # ------------------------------------------------------------------
    facet_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    total_events = 0
    events_missing_sentiment = 0
    total_views = 0
    views_missing_sentiment = 0
    oov_counts: dict[tuple[str, str, str], int] = defaultdict(int)

    for node in db.list_nodes(limit=10000):
        for facet, value in out_of_vocabulary_node_facets(node.node_type, node.facets).items():
            oov_counts[(node.node_type, facet, value)] += 1
        for key in node.facets:
            canonical_key = registry.resolve_facet_key(node.node_type, key)
            if canonical_key != key:
                facet_counts[(node.node_type, key, canonical_key)] += 1
        if node.node_type == "event":
            total_events += 1
            if normalize_sentiment(node.facets.get("sentiment")) is None:
                events_missing_sentiment += 1
        elif node.node_type == "view":
            total_views += 1
            if normalize_sentiment(node.facets.get("sentiment")) is None:
                views_missing_sentiment += 1

    facet_alias_hits = [
        FacetAliasHit(
            node_type=nt,
            raw_key=raw_k,
            canonical_key=canon_k,
            count=cnt,
        )
        for (nt, raw_k, canon_k), cnt in sorted(
            facet_counts.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1])
        )
    ]

    out_of_vocabulary_values = [
        OutOfVocabularyValue(node_type=nt, facet=facet, value=value, count=cnt)
        for (nt, facet, value), cnt in sorted(oov_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    summary = AuditSummary(
        total_edges=len(edges),
        mapped_exact_edges=mapped_exact_edges,
        mapped_alias_edges=mapped_alias_edges,
        mapped_inverse_edges=mapped_inverse_edges,
        unmapped_edges=unmapped_edges,
        distinct_unmapped_relations=len(unmapped_relations),
        direction_issue_edges=direction_issue_edges,
        reciprocal_contradiction_pairs=len(reciprocal_contradictions),
        total_companies=len(companies),
        mapped_companies=len(mapped_companies),
        unmapped_companies=len(unmapped_companies),
        total_themes=len(themes),
        mapped_themes=len(mapped_themes),
        unmapped_themes=len(unmapped_themes),
        near_duplicate_theme_pairs=len(near_duplicate_themes),
        duplicate_company_candidate_pairs=len(duplicate_company_candidates),
        suspicious_alias_count=len(suspicious_aliases),
        ticker_normalization_issue_count=len(ticker_normalization_issues),
        facet_alias_hit_count=sum(h.count for h in facet_alias_hits),
        events_missing_sentiment=events_missing_sentiment,
        total_events=total_events,
        views_missing_sentiment=views_missing_sentiment,
        total_views=total_views,
        out_of_vocabulary_value_count=sum(v.count for v in out_of_vocabulary_values),
    )

    return AuditReport(
        summary=summary,
        relation_normalization_hits=relation_normalization_hits,
        direction_issues=direction_issues,
        reciprocal_contradictions=reciprocal_contradictions,
        mapped_companies=mapped_companies,
        mapped_themes=mapped_themes,
        unmapped_relations=unmapped_relations,
        unmapped_companies=unmapped_companies,
        unmapped_themes=unmapped_themes,
        near_duplicate_themes=near_duplicate_themes,
        duplicate_company_candidates=duplicate_company_candidates,
        suspicious_aliases=suspicious_aliases,
        ticker_normalization_issues=ticker_normalization_issues,
        facet_alias_hits=facet_alias_hits,
        out_of_vocabulary_values=out_of_vocabulary_values,
    )
