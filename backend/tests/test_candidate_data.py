from pathlib import Path

from scripts.load_candidate_data import (
    build_fact_rows,
    build_profile_row,
    load_documents,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "candidate"


def test_prepared_candidate_data_is_valid_and_curated():
    profile, facts = load_documents(DATA_DIR)

    assert profile["target_roles"][0] == {"role": "CDTO", "priority": 1}
    assert profile["business_scale"]["standalone_cio_cdto_revenue_rub_billion"] == {
        "from": 10,
        "to": 100,
    }
    assert len(facts["facts"]) == 22
    keys = [fact["key"] for fact in facts["facts"]]
    assert len(keys) == len(set(keys))
    assert facts["guardrails"]


def test_loader_adds_claim_guardrails_and_only_confirmed_fact_rows():
    profile, facts = load_documents(DATA_DIR)
    profile_row = build_profile_row("u1", profile, facts)
    rows = build_fact_rows("u1", facts)

    assert profile_row["data"]["claim_guardrails"] == facts["guardrails"]
    assert all(row["active"] is True for row in rows)
    assert all("Нужно уточнить" not in row["statement"] for row in rows)
    assert {row["fact_key"] for row in rows} == {fact["key"] for fact in facts["facts"]}
