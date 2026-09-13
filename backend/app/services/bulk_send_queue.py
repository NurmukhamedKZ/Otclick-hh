"""Bulk queue helper for already individually approved vacancies.

This service never approves letters and never talks to HH. It only calls the
same exact-text `queue_approved` invariant used by the single-vacancy endpoint.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.services import send_queue_service


async def queue_many(user_id: str, pipeline_ids: list[str]) -> dict:
    # Preserve user order and de-duplicate repeated mobile checkbox payloads.
    ordered_ids = list(dict.fromkeys(str(value) for value in pipeline_ids if value))
    results: list[dict] = []

    for pipeline_id in ordered_ids:
        try:
            job = await send_queue_service.queue_approved(user_id, pipeline_id)
        except HTTPException as ex:
            results.append(
                {
                    "pipeline_id": pipeline_id,
                    "status": "error",
                    "job_id": None,
                    "error": str(ex.detail),
                }
            )
        except Exception as ex:
            # Keep the rest of the explicit batch usable, but do not hide the
            # individual failure from the user.
            results.append(
                {
                    "pipeline_id": pipeline_id,
                    "status": "error",
                    "job_id": None,
                    "error": str(ex)[:500],
                }
            )
        else:
            results.append(
                {
                    "pipeline_id": pipeline_id,
                    "status": "queued",
                    "job_id": str(job["id"]),
                    "error": None,
                }
            )

    queued = sum(1 for item in results if item["status"] == "queued")
    return {"results": results, "queued": queued, "errors": len(results) - queued}
