"""Offline unit tests for i18n catalogs, language resolution, Settings, CLI, and OntologyAgent."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from typer.testing import CliRunner

from stock_ontology.agent import OntologyAgent, build_agent_system_prompt
from stock_ontology.cli import app as cli_app
from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.i18n import (
    DEFAULT_LANGUAGE,
    LOCALES_DIR,
    SUPPORTED_LANGUAGE_CODES,
    format_via_label,
    get_clippy_i18n,
    load_catalogs,
    normalize_language,
    parse_accept_language,
    resolve_language,
    translate,
    translate_enum,
    translate_facet_label,
    translate_subtype,
)
from stock_ontology.models import ConsensusSynthesis, ExtractionResult, Node

DIM = 16
PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


def _unit_vec(idx: int) -> list[float]:
    v = [0.0] * DIM
    v[idx % DIM] = 1.0
    return v


def test_locale_files_parity_placeholders_and_no_html_entities() -> None:
    assert SUPPORTED_LANGUAGE_CODES == ("en", "zh", "ko", "ja", "es", "fr")
    load_catalogs.cache_clear()
    catalogs = load_catalogs()
    assert set(catalogs.keys()) == set(SUPPORTED_LANGUAGE_CODES)

    en_path = LOCALES_DIR / "en.json"
    en_data = json.loads(en_path.read_text(encoding="utf-8"))
    en_keys = set(en_data.keys())
    assert len(en_keys) > 200

    for code in SUPPORTED_LANGUAGE_CODES:
        loc_path = LOCALES_DIR / f"{code}.json"
        assert loc_path.exists()
        raw_data = json.loads(loc_path.read_text(encoding="utf-8"))
        assert set(raw_data.keys()) == en_keys, f"{code}.json key mismatch"

        for key, value in raw_data.items():
            assert isinstance(value, str)
            assert value.strip() != "", f"{code}.json key {key!r} is empty"
            assert "&amp;" not in value and "&lt;" not in value and "&gt;" not in value, (
                f"{code}.json key {key!r} should use plain Unicode instead of HTML entities"
            )
            en_placeholders = set(PLACEHOLDER_RE.findall(en_data[key]))
            loc_placeholders = set(PLACEHOLDER_RE.findall(value))
            assert loc_placeholders == en_placeholders, (
                f"{code}.json key {key!r} placeholders {loc_placeholders} != {en_placeholders}"
            )

        assert "Mr. User" in raw_data["clippy.welcome_intro"]
        assert "Mr. User" in raw_data["cli.chat_goodbye"]


def test_normalize_and_accept_language_and_resolution_precedence() -> None:
    assert normalize_language("en") == "en"
    assert normalize_language("EN-US") == "en"
    assert normalize_language("zh_CN") == "zh"
    assert normalize_language("zh-Hans") == "zh"
    assert normalize_language("Chinese") == "zh"
    assert normalize_language("ko-KR") == "ko"
    assert normalize_language("Japanese") == "ja"
    assert normalize_language("es-MX") == "es"
    assert normalize_language("fr-CA") == "fr"
    assert normalize_language("de") is None
    assert normalize_language("") is None
    assert normalize_language(None) is None

    assert parse_accept_language("fr-CH, fr;q=0.9, en;q=0.8") == "fr"
    assert parse_accept_language("de-DE;q=0.9, ja-JP;q=0.8, en;q=0.7") == "ja"
    assert parse_accept_language("ko;q=0, zh-CN;q=0.5") == "zh"
    assert parse_accept_language("de-DE, pt-BR") is None

    assert (
        resolve_language(
            query_lang="ja",
            cookie_lang="zh",
            accept_language="ko,fr;q=0.9",
            default="es",
        )
        == "ja"
    )
    assert (
        resolve_language(
            query_lang="invalid",
            cookie_lang="zh",
            accept_language="ko,fr;q=0.9",
            default="es",
        )
        == "zh"
    )
    assert (
        resolve_language(
            query_lang=None,
            cookie_lang="invalid",
            accept_language="ko-KR,en;q=0.8",
            default="es",
        )
        == "ko"
    )
    assert (
        resolve_language(
            query_lang=None,
            cookie_lang=None,
            accept_language="de-DE",
            default="fr",
        )
        == "fr"
    )
    assert resolve_language() == DEFAULT_LANGUAGE


def test_translate_helpers_enums_subtypes_facets_and_via() -> None:
    assert translate("home.browse_by_company", lang="zh") == "按公司浏览"
    assert translate("nonexistent.key", lang="ko") == "nonexistent.key"

    assert translate_enum("stance", "buy", lang="zh") == "买入"
    assert translate_enum("stance", "BUY", lang="ko") == "매수"
    assert translate_enum("sentiment", "negative", lang="ja") == "ネガティブ"
    assert translate_enum("relation", "SUPPLIES_TO", lang="es") == "SUMINISTRA A"
    assert translate_enum("bool", True, lang="fr") == "Oui"
    assert translate_enum("bool", False, lang="en") == "No"
    assert translate_enum("stance", "custom_rating", lang="zh") == "custom_rating"

    assert translate_subtype("company", lang="zh", node_type="entity") == "公司"
    assert translate_subtype("rumor", lang="ko", node_type="view") == "루머"
    assert translate_subtype("accelerating", lang="ja", node_type="theme") == "加速期"
    assert translate_subtype("unspecified", lang="es") == "sin especificar"
    assert translate_subtype("custom_sub", lang="fr") == "custom_sub"

    assert translate_facet_label("ticker", lang="zh") == "股票代码"
    assert translate_facet_label("custom_metric", lang="zh") == "Custom Metric"

    assert format_via_label("direct", lang="zh") == "直接"
    assert format_via_label("via event evt_1", lang="zh") == "经由 事件 evt_1"
    assert format_via_label("event: Blackwell Ramp", lang="ko") == "이벤트: Blackwell Ramp"
    assert format_via_label("custom link", lang="ja") == "custom link"

    clippy_zh = get_clippy_i18n("zh")
    assert clippy_zh["send_btn"] == "询问 Clippy"
    assert "reset_message" in clippy_zh


def test_settings_app_language_env_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_LANGUAGE", "zh-CN")
    s = Settings.from_env()
    assert s.default_language == "zh"

    monkeypatch.delenv("APP_LANGUAGE", raising=False)
    monkeypatch.setenv("STOCK_ONTOLOGY_LANG", "spanish")
    s2 = Settings.from_env()
    assert s2.default_language == "es"

    monkeypatch.setenv("APP_LANGUAGE", "klingon")
    with pytest.raises(ValueError, match="Invalid APP_LANGUAGE"):
        Settings.from_env()


class _LanguageCapturingLLM:
    def __init__(self, loop_forever: bool = False) -> None:
        self.loop_forever = loop_forever
        self.seen_system_instructions: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_unit_vec(0) for _ in texts]

    def extract_document(self, **kwargs: Any) -> ExtractionResult:
        raise NotImplementedError

    def synthesize_consensus(self, **kwargs: Any) -> ConsensusSynthesis:
        raise NotImplementedError

    @property
    def model(self) -> FunctionModel:
        return FunctionModel(self.respond)

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.seen_system_instructions.append(info.instructions or "")
        if self.loop_forever:
            return ModelResponse(parts=[ToolCallPart("list_catalog", {})])
        return ModelResponse(parts=[TextPart("OK")])


def test_ontology_agent_language_prompt_and_max_rounds(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_i18n.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        db.upsert_node(
            Node(
                id="ent_nvda",
                node_type="entity",
                name="NVIDIA",
                summary="GPU leader.",
                facets={"entity_type": "company", "ticker": "NVDA"},
            ),
            embedding=_unit_vec(0),
        )

    prompt_zh = build_agent_system_prompt("zh")
    assert "Simplified Chinese" in prompt_zh
    assert "facets.source.file_path" in prompt_zh

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        llm = _LanguageCapturingLLM()
        agent = OntologyAgent(ro, llm, model=llm.model, language="zh")
        assert agent.language == "zh"
        assert agent.ask("Check NVDA") == "OK"
        assert "Simplified Chinese" in llm.seen_system_instructions[0]

        loop_llm = _LanguageCapturingLLM(loop_forever=True)
        loop_agent = OntologyAgent(ro, loop_llm, model=loop_llm.model, language="ja")
        msg = loop_agent.ask("Loop", max_rounds=1)
        assert msg == translate("agent.max_rounds_reached", lang="ja")


def test_cli_inspect_and_invalid_lang(tmp_path: Path) -> None:
    db_path = tmp_path / "cli_i18n.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        db.upsert_node(
            Node(
                id="ent_nvda",
                node_type="entity",
                name="NVIDIA",
                summary="Original English summary.",
                aliases=["NVDA"],
                facets={"entity_type": "company", "ticker": "NVDA"},
            ),
            embedding=_unit_vec(0),
        )

    runner = CliRunner()
    res_ja = runner.invoke(cli_app, ["inspect", "--db", str(db_path), "--lang", "ja"])
    assert res_ja.exit_code == 0
    assert "エンティティ一覧" in res_ja.stdout
    assert "NVIDIA" in res_ja.stdout

    res_bad = runner.invoke(cli_app, ["inspect", "--db", str(db_path), "--lang", "xx"])
    assert res_bad.exit_code != 0
    assert "Unsupported language" in res_bad.stdout


def test_load_catalogs_reloads_when_locale_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stock_ontology.i18n as i18n_mod

    for code in SUPPORTED_LANGUAGE_CODES:
        payload = {"catalog.heading": "Research Notes"}
        (tmp_path / f"{code}.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(i18n_mod, "LOCALES_DIR", tmp_path)
    load_catalogs.cache_clear()

    assert translate("catalog.by_author", lang="en") == "catalog.by_author"

    en_file = tmp_path / "en.json"
    en_file.write_text(
        json.dumps(
            {
                "catalog.heading": "Research Notes",
                "catalog.by_author": "By Author ({count})",
            }
        ),
        encoding="utf-8",
    )
    assert translate("catalog.by_author", lang="en", count=3) == "By Author (3)"


def test_every_vocab_member_has_an_enum_key_in_every_locale() -> None:
    from stock_ontology.vocab import ALL_VOCABS

    catalogs = load_catalogs()
    missing = [
        (code, f"enum.{v.group}.{member}")
        for code in SUPPORTED_LANGUAGE_CODES
        for v in ALL_VOCABS
        for member in v.members
        if f"enum.{v.group}.{member}" not in catalogs.get(code, {})
    ]
    assert missing == []
