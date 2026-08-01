"""Polar.sh billing: hosted checkout + webhook-driven plan state.

Flow: the frontend asks ``/api/billing/subscribe`` for a checkout URL and sends the
user there. Polar (merchant of record) collects the money and POSTs events to
``/api/webhooks/polar``. Signatures follow the Standard Webhooks spec and are
verified by the SDK's ``validate_event`` — never by hand-rolled HMAC.

The user is matched by ``external_customer_id = user_id``, set when the checkout is
created and echoed back as ``customer.external_id`` on every event.

Access window comes from the subscription's ``current_period_end`` — the provider
knows when the period ends; guessing it from the charged amount (as the
CloudPayments code did) could not even tell two same-priced plans apart.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from polar_sdk import Polar
from polar_sdk.webhooks import (
    WebhookVerificationError,
    validate_event,
)

from app.config import DEFAULT_PLAN_ID, PLANS, settings
from app.db.supabase import service_client
from app.schemas.billing import BillingStatusResponse, PaymentEntry, SubscribeResponse
from app.services import plan as plan_service

logger = logging.getLogger(__name__)

# Fallback access window for a one-off order that carries no subscription.
# Subscriptions always bring their own current_period_end.
FALLBACK_PERIOD_DAYS = 30


class BillingNotConfigured(RuntimeError):
    """POLAR_ACCESS_TOKEN / product id missing — checkout cannot be created."""


def _client() -> Polar:
    if not settings.POLAR_ACCESS_TOKEN:
        raise BillingNotConfigured("POLAR_ACCESS_TOKEN is not set")
    return Polar(access_token=settings.POLAR_ACCESS_TOKEN, server=settings.POLAR_SERVER)


def product_id_for(plan_id: str) -> str:
    """POLAR_PRODUCT_<PLAN> from env — sandbox and prod products differ."""
    return getattr(settings, f"POLAR_PRODUCT_{plan_id.upper()}", "") or ""


def _checkout_sync(user_id: str, plan_id: str) -> str:
    product_id = product_id_for(plan_id)
    if not product_id:
        raise BillingNotConfigured(f"POLAR_PRODUCT_{plan_id.upper()} is not set")
    with _client() as polar:
        checkout = polar.checkouts.create(
            request={
                "products": [product_id],
                "external_customer_id": user_id,
                "success_url": settings.POLAR_SUCCESS_URL,
                "metadata": {"user_id": user_id, "plan_id": plan_id},
            }
        )
    return checkout.url


async def polar_checkout_url(user_id: str, plan_id: str | None = None) -> SubscribeResponse:
    plan = PLANS.get(plan_id or "") or PLANS[DEFAULT_PLAN_ID]
    loop = asyncio.get_running_loop()
    url = await loop.run_in_executor(None, _checkout_sync, user_id, plan["id"])
    return SubscribeResponse(checkout_url=url)


def _portal_sync(user_id: str) -> str:
    with _client() as polar:
        session = polar.customer_sessions.create(
            request={"external_customer_id": user_id}
        )
    return session.customer_portal_url


async def customer_portal_url(user_id: str) -> str:
    """Where the user manages/cancels the subscription — Polar's own portal.

    Replaces the old local-only `cancel`, which flipped a column and left the
    real recurring charge to be stopped by hand via support.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _portal_sync, user_id)


# ─── webhooks ────────────────────────────────────────────────

def verify_polar_webhook(raw_body: bytes, headers: dict[str, str]):
    """Standard Webhooks signature check. Raises WebhookVerificationError."""
    if not settings.POLAR_WEBHOOK_SECRET:
        raise WebhookVerificationError("POLAR_WEBHOOK_SECRET is not set")
    return validate_event(
        body=raw_body, headers=headers, secret=settings.POLAR_WEBHOOK_SECRET
    )


def _parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _user_id_of(obj) -> str | None:
    """external_customer_id we set at checkout, echoed as customer.external_id."""
    customer = getattr(obj, "customer", None)
    external = getattr(customer, "external_id", None)
    if external:
        return str(external)
    metadata = getattr(obj, "metadata", None) or {}
    value = metadata.get("user_id") if isinstance(metadata, dict) else None
    return str(value) if value else None


def process_polar_event(event) -> dict:
    """Apply one verified Polar event (sync, runs in an executor).

    Idempotent on order id. Unknown event types are ignored on purpose — the
    endpoint still answers 200 so Polar stops retrying.
    """
    event_type = getattr(event, "type", None) or getattr(event, "TYPE", None)
    data = getattr(event, "data", None)
    if data is None:
        return {"status": "ignored", "reason": "no_data"}

    if event_type == "order.paid":
        return _handle_order_paid(data)
    if event_type in ("subscription.active", "subscription.uncanceled"):
        return _handle_subscription_active(data)
    if event_type == "subscription.canceled":
        return _handle_subscription_state(data, "cancelled")
    if event_type == "subscription.revoked":
        return _handle_subscription_revoked(data)

    logger.info("polar webhook ignored type=%s", event_type)
    return {"status": "ignored", "reason": "unhandled_type", "type": event_type}


def _handle_order_paid(order) -> dict:
    user_id = _user_id_of(order)
    order_id = str(getattr(order, "id", "") or "")
    if not user_id or not order_id:
        logger.warning("polar order.paid without user/order id: %s", order_id)
        return {"status": "ignored", "reason": "missing_ids"}

    subscription = getattr(order, "subscription", None)
    expires_at = _parse_ts(getattr(subscription, "current_period_end", None)) or (
        datetime.now(UTC) + timedelta(days=FALLBACK_PERIOD_DAYS)
    )
    subscription_id = str(getattr(order, "subscription_id", "") or "") or None

    row = {
        "user_id": user_id,
        "provider_payment_id": order_id,
        "amount": getattr(order, "total_amount", None),
        "provider": "polar",
        "status": "completed",
        "subscription_id": subscription_id,
        "expires_at": expires_at.isoformat(),
    }
    # ignore_duplicates → data is non-empty only for a genuinely new row, so a
    # redelivered webhook never activates a plan twice.
    res = (
        service_client.table("payments")
        .upsert(row, on_conflict="provider_payment_id", ignore_duplicates=True)
        .execute()
    )
    if not res.data:
        logger.info("polar webhook duplicate, skipping activation: order=%s", order_id)
        return {"status": "duplicate", "order_id": order_id}

    _activate_plan(user_id, expires_at, subscription_id)
    logger.info("polar order.paid activated plan user=%s order=%s", user_id, order_id)
    return {"status": "activated", "user_id": user_id, "order_id": order_id}


def _handle_subscription_active(subscription) -> dict:
    user_id = _user_id_of(subscription)
    if not user_id:
        return {"status": "ignored", "reason": "missing_user"}
    expires_at = _parse_ts(getattr(subscription, "current_period_end", None))
    if expires_at is None:
        return {"status": "ignored", "reason": "no_period_end"}
    _activate_plan(user_id, expires_at, str(getattr(subscription, "id", "") or "") or None)
    return {"status": "activated", "user_id": user_id}


def _handle_subscription_state(subscription, new_plan: str) -> dict:
    """Cancelled: no more charges, but the paid period is already bought."""
    user_id = _user_id_of(subscription)
    if not user_id:
        return {"status": "ignored", "reason": "missing_user"}
    service_client.table("profiles").update({"plan": new_plan}).eq(
        "id", user_id
    ).execute()
    logger.info("polar subscription → %s for user=%s", new_plan, user_id)
    return {"status": new_plan, "user_id": user_id}


def _handle_subscription_revoked(subscription) -> dict:
    """Access is over — back to the free tier, not to a locked account."""
    user_id = _user_id_of(subscription)
    if not user_id:
        return {"status": "ignored", "reason": "missing_user"}
    service_client.table("profiles").update(
        {"plan": "free", "plan_expires_at": None}
    ).eq("id", user_id).execute()
    logger.info("polar subscription revoked → free for user=%s", user_id)
    return {"status": "free", "user_id": user_id}


def _activate_plan(user_id: str, expires_at: datetime, subscription_id: str | None) -> None:
    update = {"plan": "active", "plan_expires_at": expires_at.isoformat()}
    if subscription_id:
        update["polar_subscription_id"] = subscription_id
    service_client.table("profiles").update(update).eq("id", user_id).execute()


# ─── status ──────────────────────────────────────────────────

async def get_status(user_id: str) -> BillingStatusResponse:
    loop = asyncio.get_running_loop()

    def _profile():
        return (
            service_client.table("profiles")
            .select("plan,trial_ends,plan_expires_at")
            .eq("id", user_id)
            .single()
            .execute()
        )

    def _payments():
        return (
            service_client.table("payments")
            .select("provider_payment_id,amount,status,created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )

    prof_res, pay_res = await asyncio.gather(
        loop.run_in_executor(None, _profile),
        loop.run_in_executor(None, _payments),
    )
    prof = prof_res.data or {}
    plan_expires = prof.get("plan_expires_at")
    return BillingStatusResponse(
        plan=prof.get("plan") or "free",
        trial_ends=prof.get("trial_ends"),
        plan_expires_at=plan_expires,
        next_charge_at=plan_expires if (prof.get("plan") == "active") else None,
        has_access=plan_service.has_access(prof),
        history=[PaymentEntry(**p) for p in (pay_res.data or [])],
    )
