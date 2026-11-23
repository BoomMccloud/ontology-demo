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
    # A required subtype outside the vocabulary stays missing (the pipeline regenerates);
    # an optional enum keeps its fallback.
    event = ExtractedEvent(temp_id="e", name="n", summary="s", event_type="Gossip", status="Maybe")
    assert (event.event_type, event.status, event.sentiment) == (None, "occurred", "neutral")
    assert ExtractedEvent(temp_id="e", name="n", summary="s", event_type="fact").event_type == "fact"
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
    # Legacy rows with values outside the vocabulary, written under a registry with no facet schema.
    legacy = create_minimal_registry().model_copy(update={"facet_schema": {}})
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=4, read_only=False, registry=legacy) as db:
        for i, node in enumerate(nodes):
            db.upsert_node(node, embedding=[1.0 if j == i else 0.0 for j in range(4)])
        report = run_ontology_audit(db, create_minimal_registry())

    assert report.summary.out_of_vocabulary_value_count == 3
    assert [(v.node_type, v.facet, v.value, v.count) for v in report.out_of_vocabulary_values] == [
        ("view", "stance", "moonshot", 2),
        ("view", "view_type", "hunch", 1),
    ]


def test_cautious_stance_folds_into_bearish_with_low_conviction() -> None:
    view = ExtractedView(temp_id="v", name="n", summary="s", stance="Cautious", conviction="high", view_type="analyst_report")
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


# ---------------------------------------------------------------------------
# typed-registry-schema: facet kinds, required sets, and the registry drift check
# ---------------------------------------------------------------------------

SHIPPED_REGISTRY_PATH = __import__("pathlib").Path(__file__).resolve().parents[1] / "ontology_registry.json"


def _shipped():
    from stock_ontology.registry import load_registry

    return load_registry(SHIPPED_REGISTRY_PATH)


def test_code_facet_schema_declares_every_vocabulary_as_an_enum() -> None:
    for node_type, group in vocab.NODE_FACET_SCHEMA.items():
        enums = {k for k, spec in group.items() if spec.kind == "enum"}
        assert enums == set(vocab.NODE_FACET_VOCABS[node_type]), node_type
    assert {k for k, s in vocab.EDGE_FACET_SCHEMA.items() if s.kind == "enum"} == set(vocab.EDGE_FACET_VOCABS)
    for group in [*vocab.NODE_FACET_SCHEMA.values(), vocab.EDGE_FACET_SCHEMA]:
        assert all(spec.kind in vocab.FACET_KINDS for spec in group.values())


def test_shipped_registry_declares_the_initial_required_sets_and_kinds() -> None:
    reg = _shipped()
    # Entity-type layers: people need a role and an organization, companies a sector.
    assert {k for k in reg.facet_schema["node"] if k.startswith("entity:")} == {"entity:person", "entity:company"}
    assert reg.required_facets("entity", "person") == {"entity_type", "role", "organization"}
    assert reg.required_facets("entity", "company") == {"entity_type", "sector"}
    assert reg.required_facets("entity", "product") == {"entity_type"}
    assert all(
        spec == {"kind": "text", "required": True}
        for layer in ("entity:person", "entity:company")
        for spec in reg.facet_schema["node"][layer].values()
    )
    assert reg.metadata_max_length == {"name": 200, "summary": 1000}
    assert {nt: reg.required_facets(nt) for nt in ("entity", "event", "view", "theme")} == {
        "entity": {"entity_type"},
        "event": {"event_type"},
        "view": {"view_type"},
        "theme": {"stage"},
    }
    assert reg.required_facets(None) == {"basis"}
    node = reg.facet_schema["node"]
    assert node["event"]["event_date"]["kind"] == "date"
    assert node["view"]["as_of"]["kind"] == "date"
    assert node["view"]["target_price"]["kind"] == "number"
    assert reg.version >= 2


def _load_with_schema(tmp_path, mutate):
    import json

    from stock_ontology.registry import load_registry

    raw = json.loads(SHIPPED_REGISTRY_PATH.read_text(encoding="utf-8"))
    mutate(raw["facet_schema"])
    path = tmp_path / "ontology_registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_registry(path)


@pytest.mark.parametrize(
    ("mutate", "named"),
    [
        (lambda fs: fs["edge"].pop("basis"), "edge.basis"),
        (lambda fs: fs["node"].pop("theme"), "node.theme.stage"),
        (lambda fs: fs["node"]["entity"]["entity_type"].update({"required": False}), "entity.entity_type"),
        (lambda fs: fs["node"]["event"]["event_type"].update({"kind": "text"}), "event.event_type"),
        (lambda fs: fs["node"]["view"].pop("view_type"), "view.view_type"),
        (lambda fs: fs["node"]["view"]["as_of"].update({"kind": "money"}), "as_of"),
        (lambda fs: fs["node"]["view"]["as_of"].pop("required"), "as_of"),
        (lambda fs: fs["node"].update({"widget": {}}), "node.widget"),
        (lambda fs: fs["node"].update({"entity:spaceship": {}}), "entity:spaceship"),
        (lambda fs: fs["node"].update({"view:rumor": {}}), "view:rumor"),
        (
            lambda fs: fs["node"].update({"entity:person": {"entity_type": {"kind": "enum", "required": True}}}),
            "entity:person.entity_type",
        ),
    ],
    ids=[
        "missing-edge-basis",
        "missing-theme",
        "optional-subtype",
        "subtype-kind",
        "missing-subtype",
        "unknown-kind",
        "malformed-spec",
        "unknown-node-type",
        "unknown-entity-type",
        "non-entity-subtype-layer",
        "layer-redeclares-subtype",
    ],
)
def test_load_registry_refuses_schema_missing_code_minimum_or_malformed(tmp_path, mutate, named) -> None:
    with pytest.raises(ValueError) as excinfo:
        _load_with_schema(tmp_path, mutate)
    assert "facet_schema" in str(excinfo.value) and named in str(excinfo.value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda fs: fs["node"]["view"]["target_price"].update({"kind": "text"}),
        lambda fs: fs["node"]["view"]["stance"].update({"required": True}),
        lambda fs: fs["node"]["event"].update({"headline": {"kind": "text", "required": False}}),
        lambda fs: fs["node"].update({"entity:company": {"ticker": {"kind": "text", "required": True}}}),
    ],
    ids=["kind-change", "required-change", "extra-facet", "entity-type-layer"],
)
def test_per_type_specs_beyond_the_code_minimum_are_the_registrys_call(tmp_path, mutate) -> None:
    reg = _load_with_schema(tmp_path, mutate)
    assert reg.facet_schema != vocab.facet_schema_spec()


def test_load_registry_refuses_enum_facet_without_a_vocabulary(tmp_path) -> None:
    with pytest.raises(ValueError) as excinfo:
        _load_with_schema(tmp_path, lambda fs: fs["node"]["view"].update({"horizon": {"kind": "enum", "required": False}}))
    assert "view.horizon" in str(excinfo.value)


def _layered_registry(tmp_path):
    def mutate(fs):
        fs["node"]["entity"]["region"] = {"kind": "text", "required": False}
        fs["node"]["entity:person"] = {
            "organization": {"kind": "text", "required": True},
            "region": {"kind": "text", "required": True},
        }

    return _load_with_schema(tmp_path, mutate)


def test_entity_subtype_layer_merges_over_entity_and_overrides_a_base_key(tmp_path) -> None:
    from stock_ontology.registry import FacetSchemaError

    reg = _layered_registry(tmp_path)
    assert reg.required_facets("entity", "person") == {"entity_type", "organization", "region"}
    # Without the person layer, `region` keeps the base spec: optional.
    assert reg.required_facets("entity", "product") == {"entity_type"}
    assert reg.required_facets("entity") == {"entity_type"}
    # The layer is chosen by the stored subtype, after the vocabulary rule (`Person` is `person`).
    with pytest.raises(FacetSchemaError, match="region"):
        reg.check_facets("entity", {"entity_type": "Person", "organization": "Omega"})
    assert reg.check_facets("entity", {"entity_type": "product"}) == {"entity_type": "product"}


def test_entity_subtype_layer_does_not_leak_to_other_node_types(tmp_path) -> None:
    reg = _layered_registry(tmp_path)
    facets = {"view_type": "rumor", "entity_type": "person"}
    assert reg.required_facets("view", "person") == {"view_type"}
    assert reg.check_facets("view", facets) == facets
    assert reg.drop_uncoercible_optional("view", facets) == facets


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("number", 630, 630),
        ("number", 12.5, 12.5),
        ("number", "630", 630),
        ("number", " -12.50 ", -12.5),
        ("date", "2026-10-15", "2026-10-15"),
        ("date", "2026-10-15T09:30:00+00:00", "2026-10-15T09:30:00+00:00"),
        ("text", "Morgan", "Morgan"),
        ("text", 42, "42"),
        ("list", ["a", 1], ["a", 1]),
    ],
)
def test_coerce_facet_value_accepts_or_converts_losslessly(kind, raw, expected) -> None:
    out = vocab.coerce_facet_value(kind, raw)
    assert out == expected and type(out) is type(expected)


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        ("number", "about six hundred"),
        ("number", True),
        ("number", "007"),
        ("number", "1,200"),
        ("number", [630]),
        ("date", "Q3 2026"),
        ("date", "2026-13-01"),
        ("date", 20261015),
        ("text", True),
        ("text", {"a": 1}),
        ("list", "a, b"),
        ("enum", 3),
        ("enum", "Moonshot"),
        ("widget", "x"),
    ],
)
def test_coerce_facet_value_refuses_lossy_or_wrong_kind(kind, raw) -> None:
    with pytest.raises(ValueError):
        vocab.coerce_facet_value(kind, raw)


def test_enum_must_be_a_member_and_is_stored_canonical() -> None:
    members, aliases = vocab.VIEW_TYPE.members, dict(vocab.VIEW_TYPE.aliases)
    assert vocab.coerce_facet_value("enum", "Rumour", members=members, aliases=aliases) == "rumor"
    with pytest.raises(ValueError):
        vocab.coerce_facet_value("enum", "hunch", members=members, aliases=aliases)


def test_optional_enum_is_stored_as_its_member_or_refused() -> None:
    from stock_ontology.registry import FacetSchemaError

    reg = _shipped()
    assert reg.check_facets("view", {"view_type": "rumor", "stance": "Buy"})["stance"] == "bullish"
    with pytest.raises(FacetSchemaError, match="stance"):
        reg.check_facets("view", {"view_type": "rumor", "stance": "maybe"})
    with pytest.raises(FacetSchemaError, match="sentiment"):
        reg.check_facets(None, {"basis": "extracted", "sentiment": "giddy"})
    assert reg.drop_uncoercible_optional("view", {"view_type": "rumor", "stance": "maybe"}) == {"view_type": "rumor"}


@pytest.mark.parametrize(
    ("node_type", "facets"),
    [
        ("entity", {"ticker": "NVDA"}),
        ("event", {"status": "occurred"}),
        ("theme", {"stage": None}),
        ("view", {"view_type": "hunch"}),
        ("event", {"event_type": "news", "event_date": "soon"}),
    ],
    ids=["entity-no-entity_type", "event-no-event_type", "theme-null-stage", "view-oov-view_type", "bad-date"],
)
def test_check_facets_refuses_each_required_set_and_kind(node_type, facets) -> None:
    from stock_ontology.registry import FacetSchemaError

    with pytest.raises(FacetSchemaError):
        _shipped().check_facets(node_type, facets)


def test_check_facets_coerces_official_and_passes_undeclared_facets() -> None:
    reg = _shipped()
    facets = {"view_type": "Rumour", "target_price": "630", "author": 7, "notes": ["x"]}
    assert reg.check_facets("view", facets) == {
        "view_type": "rumor",
        "target_price": 630,
        "author": 7,
        "notes": ["x"],
    }
    assert facets["target_price"] == "630"  # the input is not mutated


def test_default_registry_enforces_its_built_in_base_schema() -> None:
    from stock_ontology.registry import FacetSchemaError, create_minimal_registry

    minimal = create_minimal_registry()
    assert minimal.facet_schema == vocab.facet_schema_spec()
    assert minimal.facet_vocabularies == _shipped().facet_vocabularies
    assert minimal.metadata_max_length == vocab.METADATA_MAX_LENGTH
    assert {nt: minimal.required_facets(nt) for nt in ("entity", "event", "view", "theme")} == {
        "entity": {"entity_type"},
        "event": {"event_type"},
        "view": {"view_type"},
        "theme": {"stage"},
    }
    with pytest.raises(FacetSchemaError):
        minimal.check_facets("view", {"view_type": "rumor", "target_price": "lots"})
    with pytest.raises(FacetSchemaError):
        minimal.check_facets("view", {"target_price": 1})


@pytest.mark.parametrize("field", ["facet_schema", "metadata_max_length"])
def test_registry_without_facet_schema_or_metadata_limits_fails_to_load(tmp_path, field) -> None:
    import json

    from stock_ontology.registry import load_registry

    raw = json.loads(SHIPPED_REGISTRY_PATH.read_text(encoding="utf-8"))
    raw.pop(field)
    path = tmp_path / "ontology_registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_registry(path)
    assert field in str(excinfo.value)


@pytest.mark.parametrize(
    ("value", "named"),
    [({"name": 200}, "summary"), ({"name": 200, "summary": 0}, "summary"), ({"name": 200, "summary": 1000, "aliases": 5}, "aliases")],
    ids=["missing", "non-positive", "unknown-field"],
)
def test_registry_refuses_malformed_metadata_limits(tmp_path, value, named) -> None:
    import json

    from stock_ontology.registry import load_registry

    raw = json.loads(SHIPPED_REGISTRY_PATH.read_text(encoding="utf-8"))
    raw["metadata_max_length"] = value
    path = tmp_path / "ontology_registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_registry(path)
    assert "metadata_max_length" in str(excinfo.value) and named in str(excinfo.value)


def test_drop_uncoercible_optional_keeps_required_and_undeclared_facets() -> None:
    facets = {"view_type": "hunch", "target_price": "$650", "as_of": "Q3", "stance": "bullish", "desk": [1]}
    assert _shipped().drop_uncoercible_optional("view", facets) == {
        "view_type": "hunch",
        "stance": "bullish",
        "desk": [1],
    }
    assert _shipped().drop_uncoercible_optional(None, {"sentiment": 3, "basis": "extracted"}) == {"basis": "extracted"}
