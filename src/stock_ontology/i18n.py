"""Internationalization (i18n) helpers and locale catalog loader for Stock Ontology."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_LANGUAGE = "en"
LANG_COOKIE_NAME = "stock_ontology_lang"
LOCALES_DIR = Path(__file__).resolve().parent / "locales"

SUPPORTED_LANGUAGES: tuple[dict[str, str], ...] = (
    {
        "code": "en",
        "html_lang": "en",
        "native_name": "English",
        "english_name": "English",
        "llm_name": "English",
    },
    {
        "code": "zh",
        "html_lang": "zh-CN",
        "native_name": "中文",
        "english_name": "Chinese",
        "llm_name": "Simplified Chinese (中文)",
    },
    {
        "code": "ko",
        "html_lang": "ko",
        "native_name": "한국어",
        "english_name": "Korean",
        "llm_name": "Korean (한국어)",
    },
    {
        "code": "ja",
        "html_lang": "ja",
        "native_name": "日本語",
        "english_name": "Japanese",
        "llm_name": "Japanese (日本語)",
    },
    {
        "code": "es",
        "html_lang": "es",
        "native_name": "Español",
        "english_name": "Spanish",
        "llm_name": "Spanish (Español)",
    },
    {
        "code": "fr",
        "html_lang": "fr",
        "native_name": "Français",
        "english_name": "French",
        "llm_name": "French (Français)",
    },
)

SUPPORTED_LANGUAGE_CODES: tuple[str, ...] = tuple(spec["code"] for spec in SUPPORTED_LANGUAGES)
_SPEC_BY_CODE: dict[str, dict[str, str]] = {spec["code"]: spec for spec in SUPPORTED_LANGUAGES}

_LANGUAGE_ALIASES: dict[str, str] = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "en-us": "en",
    "en-gb": "en",
    "en-au": "en",
    "zh": "zh",
    "zho": "zh",
    "chi": "zh",
    "cn": "zh",
    "chinese": "zh",
    "simplified-chinese": "zh",
    "simplified chinese": "zh",
    "traditional-chinese": "zh",
    "traditional chinese": "zh",
    "mandarin": "zh",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "zh-hk": "zh",
    "zh-sg": "zh",
    "zh-hans": "zh",
    "zh-hant": "zh",
    "中文": "zh",
    "简体中文": "zh",
    "繁體中文": "zh",
    "ko": "ko",
    "kor": "ko",
    "kr": "ko",
    "korean": "ko",
    "ko-kr": "ko",
    "한국어": "ko",
    "ja": "ja",
    "jpn": "ja",
    "jp": "ja",
    "japanese": "ja",
    "ja-jp": "ja",
    "日本語": "ja",
    "es": "es",
    "spa": "es",
    "spanish": "es",
    "es-es": "es",
    "es-mx": "es",
    "es-419": "es",
    "español": "es",
    "espanol": "es",
    "fr": "fr",
    "fra": "fr",
    "fre": "fr",
    "french": "fr",
    "fr-fr": "fr",
    "fr-ca": "fr",
    "français": "fr",
    "francais": "fr",
}

_VIA_NODE_RE = re.compile(r"^via\s+(entity|event|view|theme)\s+(\S+)$")
_VIA_COLON_RE = re.compile(r"^(entity|event|view|theme):\s*(.+)$")


def normalize_language(raw: str | None) -> str | None:
    """Normalize a language code, alias, or BCP-47 tag to a supported code or None."""
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned:
        return None
    normalized = cleaned.replace("_", "-")
    if normalized in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[normalized]
    if cleaned in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[cleaned]
    base = normalized.split("-", 1)[0]
    if base in _SPEC_BY_CODE:
        return base
    return _LANGUAGE_ALIASES.get(base)


def parse_accept_language(header: str | None) -> str | None:
    """Parse an HTTP Accept-Language header and return the highest-priority supported code."""
    if not header:
        return None
    candidates: list[tuple[float, int, str]] = []
    for idx, item in enumerate(header.split(",")):
        parts = [p.strip() for p in item.split(";") if p.strip()]
        if not parts:
            continue
        tag = parts[0]
        if tag == "*":
            continue
        q = 1.0
        invalid_q = False
        for param in parts[1:]:
            if param.lower().startswith("q="):
                try:
                    q = float(param[2:].strip())
                except ValueError:
                    invalid_q = True
                break
        if invalid_q or q <= 0.0:
            continue
        q = min(q, 1.0)
        candidates.append((q, -idx, tag))

    candidates.sort(reverse=True)
    for _, _, tag in candidates:
        matched = normalize_language(tag)
        if matched is not None:
            return matched
    return None


def resolve_language(
    *,
    query_lang: str | None = None,
    cookie_lang: str | None = None,
    accept_language: str | None = None,
    default: str = DEFAULT_LANGUAGE,
) -> str:
    """Resolve effective UI/agent language with precedence: query > cookie > Accept-Language > default."""
    for candidate in (query_lang, cookie_lang):
        norm = normalize_language(candidate)
        if norm is not None:
            return norm
    accepted = parse_accept_language(accept_language)
    if accepted is not None:
        return accepted
    return normalize_language(default) or DEFAULT_LANGUAGE


def get_language_spec(lang: str) -> dict[str, str]:
    """Return metadata specification dict for a language code (falling back to default)."""
    code = normalize_language(lang) or DEFAULT_LANGUAGE
    return _SPEC_BY_CODE[code]


def _locales_signature() -> tuple[str, tuple[tuple[str, int, int], ...]]:
    """Return `(locales_dir, ((code, mtime_ns, size), ...))` to auto-invalidate stale caches."""
    sig: list[tuple[str, int, int]] = []
    for code in SUPPORTED_LANGUAGE_CODES:
        st = (LOCALES_DIR / f"{code}.json").stat()
        sig.append((code, st.st_mtime_ns, st.st_size))
    return (str(LOCALES_DIR), tuple(sig))


@lru_cache(maxsize=4)
def _load_catalogs_cached(
    signature: tuple[str, tuple[tuple[str, int, int], ...]],
) -> dict[str, dict[str, str]]:
    locales_dir = Path(signature[0])
    catalogs: dict[str, dict[str, str]] = {}
    for code, _mtime_ns, _size in signature[1]:
        path = locales_dir / f"{code}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        catalogs[code] = {str(k): str(v) for k, v in data.items()}
    return catalogs


def load_catalogs() -> dict[str, dict[str, str]]:
    """Load all flat JSON locale catalogs keyed by supported language code."""
    return _load_catalogs_cached(_locales_signature())


load_catalogs.cache_clear = _load_catalogs_cached.cache_clear  # type: ignore[attr-defined]


def translate(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs: Any) -> str:
    """Look up translation string by key with fallback chain `lang -> en -> key`."""
    resolved = normalize_language(lang) or DEFAULT_LANGUAGE
    catalogs = load_catalogs()
    template = catalogs.get(resolved, {}).get(key)
    if template is None:
        template = catalogs.get(DEFAULT_LANGUAGE, {}).get(key)
    if template is None:
        return key
    if kwargs:
        return template.format(**kwargs)
    return template


t = translate


def translate_enum(group: str, value: Any, lang: str = DEFAULT_LANGUAGE) -> str:
    """Translate a controlled ontology enum value, falling back to `str(value)` when unknown."""
    if value is None:
        return ""
    if isinstance(value, bool):
        norm = "true" if value else "false"
    else:
        raw_str = str(value).strip()
        if not raw_str:
            return ""
        norm = raw_str.upper() if group == "relation" else raw_str.lower()

    resolved = normalize_language(lang) or DEFAULT_LANGUAGE
    catalogs = load_catalogs()
    key = f"enum.{group}.{norm}"
    translated = catalogs.get(resolved, {}).get(key)
    if translated is None:
        translated = catalogs.get(DEFAULT_LANGUAGE, {}).get(key)
    if translated is None:
        return str(value)
    return translated


def translate_facet_label(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """Translate a known facet key label, falling back to Title Case for dynamic custom keys."""
    resolved = normalize_language(lang) or DEFAULT_LANGUAGE
    catalogs = load_catalogs()
    lookup = f"facet.{key.strip().lower()}"
    translated = catalogs.get(resolved, {}).get(lookup)
    if translated is None:
        translated = catalogs.get(DEFAULT_LANGUAGE, {}).get(lookup)
    if translated is not None:
        return translated
    return key.replace("_", " ").title()


_SUBTYPE_GROUP_BY_NODE_TYPE: dict[str, str] = {
    "entity": "entity_type",
    "event": "event_type",
    "view": "view_type",
    "theme": "stage",
}


def translate_subtype(
    value: Any,
    lang: str = DEFAULT_LANGUAGE,
    node_type: str | None = None,
) -> str:
    """Translate a node subtype (`entity_type`, `event_type`, `view_type`, `stage`, or `unspecified`)."""
    if value is None:
        return ""
    raw_str = str(value).strip()
    if not raw_str:
        return ""
    norm = raw_str.lower()
    if norm == "unspecified":
        return translate_enum("subtype", "unspecified", lang=lang)

    if node_type:
        nt_norm = node_type.strip().lower()
        group = _SUBTYPE_GROUP_BY_NODE_TYPE.get(nt_norm)
        if group is not None:
            return translate_enum(group, norm, lang=lang)

    resolved = normalize_language(lang) or DEFAULT_LANGUAGE
    catalogs = load_catalogs()
    for group in ("entity_type", "event_type", "view_type", "stage"):
        lookup = f"enum.{group}.{norm}"
        if lookup in catalogs.get(resolved, {}) or lookup in catalogs.get(DEFAULT_LANGUAGE, {}):
            return translate_enum(group, norm, lang=lang)
    return str(value)


def format_via_label(via: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """Format theme exposure `via` metadata (`direct`, `via <type> <id>`, or `<type>: <name>`)."""
    if not via:
        return ""
    if via == "direct":
        return translate("theme.via_direct", lang=lang)
    match = _VIA_NODE_RE.match(via.strip())
    if match:
        node_type, node_id = match.group(1), match.group(2)
        return translate(
            "theme.via_node",
            lang=lang,
            node_type=translate_enum("node_type", node_type, lang=lang),
            node_id=node_id,
        )
    colon_match = _VIA_COLON_RE.match(via.strip())
    if colon_match:
        node_type, node_name = colon_match.group(1), colon_match.group(2)
        return f"{translate_enum('node_type', node_type, lang=lang)}: {node_name}"
    return via


def get_clippy_i18n(lang: str = DEFAULT_LANGUAGE) -> dict[str, str]:
    """Return localized strings needed by the client-side Clippy JS widget."""
    keys = (
        "role_user",
        "role_bot",
        "tools_queried",
        "llm_label",
        "fallback_tag",
        "thinking",
        "send_btn",
        "no_response",
        "network_error",
        "reset_message",
    )
    return {k: translate(f"clippy.{k}", lang=lang) for k in keys}
