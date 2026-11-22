"""Offline unit tests for the closed enum vocabularies in `stock_ontology.vocab`."""

from __future__ import annotations

import pytest

from stock_ontology import vocab
from stock_ontology.models import ConsensusSynthesis, ExtractedEvent, ExtractedView, derive_sentiment_from_stance


@pytest.mark.parametrize(
    ("coerce", "raw", "expected"),
    [
        (vocab.coerce_entity_type, "company", "company"),
        (vocab.coerce_entity_type, " COMPANY ", "company"),
        (vocab.coerce_entity_type, "Spaceship", None),
        (vocab.coerce_event_type, "News", "news"),
        (vocab.coerce_event_type, "gossip", None),
        (vocab.coerce_event_status, "Rumored", "rumored"),
        (vocab.coerce_event_status, "rumoured", "rumored"),
        (vocab.coerce_event_status, "maybe", None),
        (vocab.coerce_view_type, "Analyst Report", "analyst_report"),
        (vocab.coerce_view_type, "channel-check", "channel_check"),
        (vocab.coerce_view_type, "Rumour", "rumor"),
        (vocab.coerce_view_type, "house_consensus", "consensus"),
        (vocab.coerce_view_type, "hunch", None),
        (vocab.coerce_view_status, "Superseded", "superseded"),
        (vocab.coerce_view_status, "stale", "superseded"),
        (vocab.coerce_view_status, "archived", None),
        (vocab.coerce_stance, "Bullish", "bullish"),
        (vocab.coerce_stance, "Outperform", "bullish"),
        (vocab.coerce_stance, "overweight", "bullish"),
        (vocab.coerce_stance, "underperform", "bearish"),
        (vocab.coerce_stance, "Underweight", "bearish"),
        (vocab.coerce_stance, "Buy", "bullish"),
        (vocab.coerce_stance, "sell", "bearish"),
        (vocab.coerce_stance, "hold", "neutral"),
        (vocab.coerce_stance, "Cautious", "bearish"),
        (vocab.coerce_stance, "unknown", "neutral"),
        (vocab.coerce_stance, "moonshot", None),
        (vocab.coerce_sentiment, "Negative", "negative"),
        (vocab.coerce_sentiment, "ecstatic", None),
        (vocab.coerce_support_strength, "STRONG", "strong"),
        (vocab.coerce_support_strength, "huge", None),
        (vocab.coerce_conviction, "High", "high"),
        (vocab.coerce_conviction, "total", None),
        (vocab.coerce_stage, "Emerging", "emerging"),
        (vocab.coerce_stage, "zombie", None),
    ],
)
def test_coercers_map_case_and_aliases_and_reject_unknowns(coerce, raw, expected) -> None:
    assert coerce(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", 3, ["buy"]])
def test_coercers_return_none_for_missing_or_non_string(raw) -> None:
    for v in vocab.ALL_VOCABS:
        assert v.coerce(raw) is None


def test_every_member_coerces_to_itself_and_every_alias_targets_a_member() -> None:
    for v in vocab.ALL_VOCABS:
        for member in v.members:
            assert v.coerce(member) == member
            assert v.definitions[member].strip()
        for alias, target in v.aliases.items():
            assert v.coerce(alias) == target


def test_stance_canon_merges_ratings_into_directions() -> None:
    assert vocab.STANCE.members == ("bullish", "bearish", "neutral")


def test_ingest_fallback_and_repair_rules_differ_for_unknown_values() -> None:
    assert vocab.STANCE.coerce_or_fallback("Moonshot") == "neutral"
    assert vocab.STANCE.canonicalize_stored("Moonshot") == "moonshot"
    assert vocab.STANCE.canonicalize_stored(" Outperform ") == "bullish"
    assert vocab.SENTIMENT.coerce_or_fallback("ecstatic") is None


def test_canonicalize_node_facets_touches_only_vocab_keys_for_that_node_type() -> None:
    facets = {"stance": "Bullish", "status": "stale", "ticker": "ACME", "author": "Jane Roe"}
    assert vocab.canonicalize_node_facets("view", facets) == {
        "stance": "bullish",
        "status": "superseded",
        "ticker": "ACME",
        "author": "Jane Roe",
    }
    # `stance` is not an event vocabulary, so it is left alone on an event.
    assert vocab.canonicalize_node_facets("event", {"stance": "Bullish"}) == {"stance": "Bullish"}
    assert vocab.canonicalize_edge_facets({"sentiment": "Positive", "rationale": "X"}) == {
        "sentiment": "positive",
        "rationale": "X",
    }


def test_out_of_vocabulary_node_facets_reports_non_members() -> None:
    assert vocab.out_of_vocabulary_node_facets("view", {"stance": "moonshot", "view_type": "rumor"}) == {
        "stance": "moonshot"
    }


def test_extraction_models_coerce_through_vocab() -> None:
    view = ExtractedView(temp_id="v", name="n", summary="s", view_type="Rumour", stance="Outperform", sentiment="Ecstatic")
    assert (view.view_type, view.stance, view.sentiment) == ("rumor", "bullish", None)
    event = ExtractedEvent(temp_id="e", name="n", summary="s", event_type="Gossip", status="Maybe")
    assert (event.event_type, event.status, event.sentiment) == ("fact", "occurred", "neutral")
    schema = ExtractedView.model_json_schema()["properties"]["stance"]
    assert schema["enum"] == list(vocab.STANCE.members)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), ("", None), ("Unknown", "unclassified"), (" NONE ", "unclassified"), ("Positive", "positive")],
)
def test_parse_sentiment_filter(raw, expected) -> None:
    assert vocab.parse_sentiment_filter(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), ("Rumors", "rumor"), ("Analyst Reports", "analyst_report"), ("earnings", "earnings")],
)
def test_parse_category_filter(raw, expected) -> None:
    assert vocab.parse_category_filter(raw) == expected


def test_matches_signal_filter_rumor_rule_and_unclassified() -> None:
    rumored_event = {"event_type": "news", "status": "rumored"}
    assert vocab.matches_signal_filter("event", rumored_event, None, categories={"rumor"})
    assert vocab.matches_signal_filter("event", rumored_event, None, categories={"news"})
    assert vocab.matches_signal_filter("view", {"view_type": "rumor"}, None, categories={"rumor"})
    assert not vocab.matches_signal_filter("view", {"view_type": "pm_view"}, None, categories={"rumor"})
    assert vocab.matches_signal_filter("view", {}, None, sentiments={"unclassified"})
    assert not vocab.matches_signal_filter("view", {}, "positive", sentiments={"negative"})


def test_audit_counts_and_lists_out_of_vocabulary_stored_values(tmp_path) -> None:
    from stock_ontology.audit import run_ontology_audit
    from stock_ontology.db import OntologyDB
    from stock_ontology.models import Node
    from stock_ontology.registry import create_minimal_registry

    nodes = [
        Node(id="vw_a", node_type="view", name="A", summary=".", facets={"view_type": "rumor", "stance": "moonshot"}),
        Node(id="vw_b", node_type="view", name="B", summary=".", facets={"view_type": "hunch", "stance": "moonshot"}),
        Node(id="thm_c", node_type="theme", name="C", summary=".", facets={"stage": "emerging"}),
        # `stance` is not an event vocabulary, so it is not reported on an event.
        Node(id="evt_d", node_type="event", name="D", summary=".", facets={"event_type": "news", "stance": "odd"}),
    ]
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=4, read_only=False) as db:
        for i, node in enumerate(nodes):
            db.upsert_node(node, embedding=[1.0 if j == i else 0.0 for j in range(4)])
        report = run_ontology_audit(db, create_minimal_registry())

    assert report.summary.out_of_vocabulary_value_count == 3
    assert [(v.node_type, v.facet, v.value, v.count) for v in report.out_of_vocabulary_values] == [
        ("view", "stance", "moonshot", 2),
        ("view", "view_type", "hunch", 1),
    ]


def test_cautious_stance_folds_into_bearish_with_low_conviction() -> None:
    view = ExtractedView(temp_id="v", name="n", summary="s", stance="Cautious", conviction="high")
    assert (view.stance, view.conviction) == ("bearish", "low")
    syn = ConsensusSynthesis(stance="cautious", support_strength="weak", conviction="medium", summary="s")
    assert (syn.stance, syn.conviction) == ("bearish", "low")
    assert derive_sentiment_from_stance("cautious") == "negative"
    repaired = vocab.canonicalize_node_facets("view", {"stance": "cautious", "conviction": "medium"})
    assert repaired == {"stance": "bearish", "conviction": "low"}
    untouched = vocab.canonicalize_node_facets("view", {"stance": "bearish", "conviction": "high"})
    assert untouched == {"stance": "bearish", "conviction": "high"}


# ---------------------------------------------------------------------------
# Proof witnesses: official-edge-facets (registry declares the official facet vocabularies)
# ---------------------------------------------------------------------------

_IDENTIFIER_KEYS = ("name", "value", "member", "id", "key")


def _walk(tree):
    yield tree
    children = tree.values() if isinstance(tree, dict) else tree if isinstance(tree, list) else ()
    for child in children:
        yield from _walk(child)


def _member_names(container) -> set[str] | None:
    """Member names a dict (by key) or list (strings, or dicts by identifier key) lists."""
    if isinstance(container, dict):
        return set(container)
    if isinstance(container, list):
        names: set[str] = set()
        for item in container:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict):
                ident = next((item[k] for k in _IDENTIFIER_KEYS if isinstance(item.get(k), str)), None)
                if ident is None:
                    return None
                names.add(ident)
            else:
                return None
        return names
    return None


def _strings(tree) -> set[str]:
    out: set[str] = set()
    for node in _walk(tree):
        if isinstance(node, str):
            out.add(node)
        elif isinstance(node, dict):
            out.update(k for k in node if isinstance(k, str))
    return out


def _assert_declares_code_vocabularies(tree, label: str) -> None:
    expected: list[tuple[str, vocab.Vocabulary]] = [
        (f"{node_type}.{key}", v) for node_type, group in vocab.NODE_FACET_VOCABS.items() for key, v in group.items()
    ] + [(f"edge.{key}", v) for key, v in vocab.EDGE_FACET_VOCABS.items()]
    member_sets = [names for node in _walk(tree) if (names := _member_names(node))]
    strings = _strings(tree)
    alias_pairs = {
        (k, v) for node in _walk(tree) if isinstance(node, dict) for k, v in node.items() if isinstance(v, str)
    }
    fallbacks = {
        v
        for node in _walk(tree)
        if isinstance(node, dict)
        for k, v in node.items()
        if isinstance(k, str) and "fallback" in k and isinstance(v, str)
    }
    for where, v in expected:
        assert set(v.members) in member_sets, f"{label}: no vocabulary lists exactly the {where} members {v.members}"
        missing_defs = [d for d in v.definitions.values() if d not in strings]
        assert not missing_defs, f"{label}: {where} definitions missing: {missing_defs}"
        missing_aliases = [(a, t) for a, t in v.aliases.items() if (a, t) not in alias_pairs]
        assert not missing_aliases, f"{label}: {where} aliases missing: {missing_aliases}"
        if v.fallback is not None:
            assert v.fallback in fallbacks, f"{label}: {where} fallback {v.fallback!r} not declared"


def test_registry_and_code_declare_the_same_official_facet_vocabularies(tmp_path) -> None:
    import json
    from pathlib import Path

    from stock_ontology.registry import create_minimal_registry, load_registry, save_registry

    # The shipped registry declares every code vocabulary, member for member, and loads.
    shipped_path = Path(__file__).resolve().parents[1] / "ontology_registry.json"
    _assert_declares_code_vocabularies(json.loads(shipped_path.read_text(encoding="utf-8")), "ontology_registry.json")
    load_registry(shipped_path)

    # The starter registry declares the same, and survives a save/load round trip.
    minimal = create_minimal_registry()
    _assert_declares_code_vocabularies(minimal.model_dump(mode="json"), "create_minimal_registry()")
    save_registry(minimal, tmp_path / "ontology_registry.json")
    reloaded = load_registry(tmp_path / "ontology_registry.json")
    assert reloaded.model_dump(mode="json") == minimal.model_dump(mode="json")

    # Code: `basis` is an official edge vocabulary with no ingest fallback, beside `sentiment`.
    assert "basis" in vocab.EDGE_FACET_VOCABS, "edge facet `basis` is not an official vocabulary in code"
    basis = vocab.EDGE_FACET_VOCABS["basis"]
    assert basis.members == ("extracted", "synthesized")
    assert basis.fallback is None
    assert vocab.EDGE_FACET_VOCABS["sentiment"] is vocab.SENTIMENT
