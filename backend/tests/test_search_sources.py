import pytest

from app.services.search_sources import (
    InvalidHHSearchURL,
    parse_hh_search_url,
    query_pairs_to_multidict,
)


def test_parse_search_url_preserves_repeated_parameters_and_unknowns():
    parsed = parse_hh_search_url(
        "https://tambov.hh.ru/search/vacancy?text=CIO&area=1&area=2"
        "&search_field=name&search_field=company_name&future_param=x"
    )

    assert parsed.host == "tambov.hh.ru"
    assert parsed.parameters["area"] == ("1", "2")
    assert parsed.parameters["search_field"] == ("name", "company_name")
    assert parsed.unsupported_parameters == ("future_param",)
    assert parsed.query_pairs_json() == [
        {"key": "text", "value": "CIO"},
        {"key": "area", "value": "1"},
        {"key": "area", "value": "2"},
        {"key": "search_field", "value": "name"},
        {"key": "search_field", "value": "company_name"},
        {"key": "future_param", "value": "x"},
    ]


def test_multidict_roundtrip_keeps_duplicate_values():
    grouped = query_pairs_to_multidict(
        [
            {"key": "area", "value": "1"},
            {"key": "area", "value": "2"},
            {"key": "text", "value": "CDTO"},
        ]
    )
    assert grouped == {"area": ["1", "2"], "text": ["CDTO"]}


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/search/vacancy?text=CIO",
        "https://hh.ru/vacancy/123",
        "ftp://hh.ru/search/vacancy?text=CIO",
        "",
    ],
)
def test_rejects_non_search_urls(url):
    with pytest.raises(InvalidHHSearchURL):
        parse_hh_search_url(url)


def test_outcome_counts_batches_all_vacancy_ids(monkeypatch):
    from types import SimpleNamespace

    from app.services import search_source_service

    vacancy_ids = [f"vacancy-{index}" for index in range(150)]
    batches = []

    class Query:
        def __init__(self, table):
            self.table_name = table
            self.ids = []

        def select(self, _columns):
            return self

        def eq(self, _column, _value):
            return self

        def in_(self, _column, values):
            self.ids = list(values)
            batches.append(self.ids)
            return self

        def execute(self):
            if self.table_name == "vacancy_pipeline_sources":
                return SimpleNamespace(
                    data=[{"vacancy_id": vacancy_id} for vacancy_id in vacancy_ids]
                )
            return SimpleNamespace(
                data=[
                    {
                        "id": vacancy_id,
                        "status": "score_error" if vacancy_id.endswith("7") else "scored",
                        "hard_filter_reason": "blocked"
                        if vacancy_id.endswith("3")
                        else None,
                    }
                    for vacancy_id in self.ids
                ]
            )

    class Client:
        def table(self, table):
            return Query(table)

    monkeypatch.setattr(search_source_service, "service_client", Client())

    counts = search_source_service._outcome_counts("source-1")

    assert [len(batch) for batch in batches] == [50, 50, 50]
    assert [vacancy_id for batch in batches for vacancy_id in batch] == vacancy_ids
    assert counts == {"hard_filtered": 15, "score_error": 15}


def test_outcome_counts_skips_pipeline_query_without_links(monkeypatch):
    from types import SimpleNamespace

    from app.services import search_source_service

    class Query:
        def select(self, _columns):
            return self

        def eq(self, _column, _value):
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class Client:
        def table(self, table):
            assert table == "vacancy_pipeline_sources"
            return Query()

    monkeypatch.setattr(search_source_service, "service_client", Client())

    assert search_source_service._outcome_counts("source-1") == {
        "hard_filtered": 0,
        "score_error": 0,
    }
