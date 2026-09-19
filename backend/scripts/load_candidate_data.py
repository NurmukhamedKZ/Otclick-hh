#!/usr/bin/env python3
"""Load curated candidate positioning/facts into Supabase.

This is deliberately a prepared-data loader, not a Markdown parser. To change
candidate context, edit/regen the JSON files after reviewing the source docs.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_DATA_DIR = BACKEND_ROOT / "data" / "candidate"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError(f"unsupported candidate data schema: {path}")
    return data


def load_documents(data_dir: Path) -> tuple[dict, dict]:
    profile = _read_json(data_dir / "candidate_profile.json")
    facts = _read_json(data_dir / "confirmed_facts.json")
    if not isinstance(facts.get("facts"), list):
        raise ValueError("confirmed_facts.json: facts must be an array")
    if not isinstance(facts.get("guardrails"), list):
        raise ValueError("confirmed_facts.json: guardrails must be an array")
    return profile, facts


def build_profile_row(user_id: str, profile_doc: dict, facts_doc: dict) -> dict:
    data = {k: v for k, v in profile_doc.items() if k not in {"schema_version", "source"}}
    data["claim_guardrails"] = list(facts_doc["guardrails"])
    return {
        "user_id": user_id,
        "version": 1,
        "source_name": str(profile_doc["source"]),
        "data": data,
        "updated_at": _now(),
    }


def build_fact_rows(user_id: str, facts_doc: dict) -> list[dict]:
    source = str(facts_doc["source"])
    now = _now()
    rows: list[dict] = []
    seen: set[str] = set()
    for fact in facts_doc["facts"]:
        key = str(fact.get("key") or "").strip()
        if not key or key in seen:
            raise ValueError(f"empty or duplicate fact key: {key!r}")
        seen.add(key)
        statement = str(fact.get("statement") or "").strip()
        if not statement:
            raise ValueError(f"fact {key}: statement is required")
        rows.append(
            {
                "user_id": user_id,
                "fact_key": key,
                "category": str(fact.get("category") or "other"),
                "title": str(fact.get("title") or key),
                "statement": statement,
                "metrics": fact.get("metrics") or {},
                "tags": fact.get("tags") or [],
                "source_name": source,
                "active": True,
                "updated_at": now,
            }
        )
    return rows


def apply(user_id: str, data_dir: Path) -> tuple[int, int]:
    from app.db.supabase import service_client

    profile_doc, facts_doc = load_documents(data_dir)
    profile_row = build_profile_row(user_id, profile_doc, facts_doc)
    fact_rows = build_fact_rows(user_id, facts_doc)

    profile_res = service_client.table("candidate_profiles").upsert(
        profile_row, on_conflict="user_id"
    ).execute()
    if not profile_res.data:
        raise RuntimeError("candidate profile upsert returned no data")

    # Facts removed from prepared data become inactive, rather than silently
    # surviving forever and being reused by a cover-letter prompt months later.
    service_client.table("candidate_facts").update(
        {"active": False, "updated_at": _now()}
    ).eq("user_id", user_id).execute()

    if fact_rows:
        facts_res = service_client.table("candidate_facts").upsert(
            fact_rows, on_conflict="user_id,fact_key"
        ).execute()
        if len(facts_res.data or []) != len(fact_rows):
            raise RuntimeError("candidate facts upsert returned unexpected row count")

    return 1, len(fact_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True, help="profiles.id to load data for")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"prepared JSON directory (default: {DEFAULT_DATA_DIR})",
    )
    args = parser.parse_args()
    profiles, facts = apply(args.user_id, args.data_dir)
    print(f"loaded candidate context: profiles={profiles} facts={facts}")


if __name__ == "__main__":
    main()
