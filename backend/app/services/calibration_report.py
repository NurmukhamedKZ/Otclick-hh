"""Calibration report: compare persisted scores with explicit user decisions.

No threshold is treated as truth here. We expose score bands and raw decisions
so 20–30 reviewed vacancies can be used to tune the scorer without teaching it
from implicit employer outcomes or stale AI output.
"""

from __future__ import annotations

from statistics import mean

from app.services import vacancy_review_service

POSITIVE_STATUSES = (
    "selected",
    "letter_draft",
    "approved",
    "queued_to_send",
    "sending",
    "sent",
)
NEGATIVE_STATUS = "rejected_by_user"
DECISION_STATUSES = (*POSITIVE_STATUSES, NEGATIVE_STATUS)

_BANDS = (
    ("0–39", 0, 39),
    ("40–59", 40, 59),
    ("60–79", 60, 79),
    ("80–100", 80, 100),
)


def _band_for(score: int) -> tuple[str, int, int]:
    for item in _BANDS:
        if item[1] <= score <= item[2]:
            return item
    return _BANDS[0] if score < 0 else _BANDS[-1]


async def build_report(user_id: str, limit: int = 300) -> dict:
    rows = await vacancy_review_service.list_vacancies(
        user_id,
        statuses=list(DECISION_STATUSES),
        limit=limit,
        offset=0,
        include_stale=True,
    )

    bands = {
        label: {
            "label": label,
            "min_score": low,
            "max_score": high,
            "positive": 0,
            "rejected": 0,
            "total": 0,
        }
        for label, low, high in _BANDS
    }
    positive_scores: list[int] = []
    rejected_scores: list[int] = []
    stale_scores = 0
    decisions: list[dict] = []

    for row in rows:
        decision = "rejected" if row.get("status") == NEGATIVE_STATUS else "positive"
        score_raw = row.get("score")
        score = int(score_raw) if score_raw is not None else None
        stale = row.get("score_stale") is True
        if stale and score is not None:
            stale_scores += 1

        # Only fresh scores enter calibration aggregates. Stale values remain in
        # the raw decision list for diagnosis but cannot skew tuning statistics.
        if score is not None and not stale:
            label, _, _ = _band_for(score)
            bands[label][decision] += 1
            bands[label]["total"] += 1
            if decision == "positive":
                positive_scores.append(score)
            else:
                rejected_scores.append(score)

        decisions.append(
            {
                "pipeline_id": str(row["id"]),
                "hh_vacancy_id": str(row["hh_vacancy_id"]),
                "title": str(row.get("title") or ""),
                "employer_name": row.get("employer_name"),
                "lifecycle_status": str(row.get("status") or ""),
                "decision": decision,
                "score": score,
                "score_stale": row.get("score_stale"),
                "user_decision_reason": row.get("user_decision_reason"),
                "discovered_at": str(row.get("discovered_at") or ""),
            }
        )

    positive = sum(1 for item in decisions if item["decision"] == "positive")
    rejected = len(decisions) - positive
    with_score = sum(1 for item in decisions if item["score"] is not None)
    fresh_scored = len(positive_scores) + len(rejected_scores)

    return {
        "reviewed": len(decisions),
        "positive": positive,
        "rejected": rejected,
        "with_score": with_score,
        "stale_scores": stale_scores,
        "fresh_scored_decisions": fresh_scored,
        "average_positive_score": round(mean(positive_scores), 1) if positive_scores else None,
        "average_rejected_score": round(mean(rejected_scores), 1) if rejected_scores else None,
        "bands": list(bands.values()),
        "decisions": decisions,
    }
