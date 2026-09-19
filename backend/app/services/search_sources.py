"""Search-source helpers for HH vacancy discovery.

A source is stored independently of the UI method used to create it. A user may
paste a normal HH search URL or later import a native HH auto-search; both end up
as the same ordered list of query pairs plus a persistent cursor in PostgreSQL.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse


class InvalidHHSearchURL(ValueError):
    """Raised when a URL cannot be used as an HH vacancy search source."""


# Parameters we explicitly understand today. Unknown parameters are NOT dropped:
# they are returned separately and persisted in query_pairs for forward
# compatibility and for previewing to the user before saving the source.
SUPPORTED_SEARCH_PARAMS = frozenset(
    {
        "text",
        "area",
        "search_field",
        "experience",
        "employment",
        "schedule",
        "professional_role",
        "industry",
        "employer_id",
        "salary",
        "currency_code",
        "only_with_salary",
        "label",
        "period",
        "date_from",
        "date_to",
        "order_by",
        "items_on_page",
        "page",
        "excluded_text",
        "enable_snippets",
        "no_magic",
        "L_save_area",
        "hhtmFrom",
        "hhtmFromLabel",
    }
)


@dataclass(frozen=True)
class ParsedSearchURL:
    raw_url: str
    host: str
    path: str
    query_pairs: tuple[tuple[str, str], ...]
    parameters: dict[str, tuple[str, ...]]
    unsupported_parameters: tuple[str, ...]

    def query_pairs_json(self) -> list[dict[str, str]]:
        """DB representation preserving duplicate keys and their order."""
        return [{"key": key, "value": value} for key, value in self.query_pairs]


def _is_hh_host(host: str) -> bool:
    host = host.lower().split(":", 1)[0]
    return (
        host == "hh.ru"
        or host.endswith(".hh.ru")
        or host == "hh.kz"
        or host.endswith(".hh.kz")
    )


def parse_hh_search_url(url: str) -> ParsedSearchURL:
    """Parse an HH search URL without losing repeated query parameters.

    Regional hosts such as tambov.hh.ru are accepted. Only vacancy search pages
    are accepted; vacancy detail/recommendation/employer URLs are different
    source types and must not silently masquerade as a search source.
    """
    raw = (url or "").strip()
    if not raw:
        raise InvalidHHSearchURL("empty URL")

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise InvalidHHSearchURL("HH search URL must use http or https")
    if not parsed.hostname or not _is_hh_host(parsed.hostname):
        raise InvalidHHSearchURL("URL host is not hh.ru/hh.kz")

    path = parsed.path.rstrip("/") or "/"
    if path != "/search/vacancy":
        raise InvalidHHSearchURL("URL is not an HH vacancy search page")

    pairs = tuple(parse_qsl(parsed.query, keep_blank_values=True))
    grouped: dict[str, list[str]] = defaultdict(list)
    for key, value in pairs:
        grouped[key].append(value)

    unsupported = tuple(
        sorted(key for key in grouped if key not in SUPPORTED_SEARCH_PARAMS)
    )
    return ParsedSearchURL(
        raw_url=raw,
        host=parsed.hostname.lower(),
        path=path,
        query_pairs=pairs,
        parameters={key: tuple(values) for key, values in grouped.items()},
        unsupported_parameters=unsupported,
    )


def query_pairs_to_multidict(
    query_pairs: list[dict[str, str]] | tuple[tuple[str, str], ...],
) -> dict[str, list[str]]:
    """Convert persisted ordered pairs to a multi-value mapping for previews."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in query_pairs:
        if isinstance(item, dict):
            key = str(item.get("key", ""))
            value = str(item.get("value", ""))
        else:
            key, value = str(item[0]), str(item[1])
        if key:
            grouped[key].append(value)
    return dict(grouped)
