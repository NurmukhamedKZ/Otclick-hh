import base64
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

SECRET = "polar-webhook-secret"


def _fluent(final_data):
    chain = MagicMock()
    for m in ("select", "insert", "update", "upsert", "delete", "eq", "order", "limit", "single"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = SimpleNamespace(data=final_data)
    return chain


def _table_router(payments_chain, profiles_chain):
    def _route(name):
        return payments_chain if name == "payments" else profiles_chain

    return _route


def _sign(payload: dict, secret: str = SECRET) -> tuple[bytes, dict]:
    """Standard Webhooks signature, the way Polar sends it.

    The SDK base64-encodes the raw secret before handing it to standardwebhooks,
    so a test that signs with the raw secret would never verify.
    """
    from standardwebhooks.webhooks import Webhook

    body = json.dumps(payload).encode()
    msg_id = "msg_test"
    now = datetime.now(timezone.utc)
    wh = Webhook(base64.b64encode(secret.encode()).decode())
    signature = wh.sign(msg_id, now, body.decode())
    return body, {
        "webhook-id": msg_id,
        "webhook-timestamp": str(int(now.timestamp())),
        "webhook-signature": signature,
        "content-type": "application/json",
    }


def _order_paid_payload(order_id="ord_1", user_id="u1", period_end="2026-08-27T00:00:00Z"):
    return {
        "type": "order.paid",
        "timestamp": "2026-07-27T00:00:00Z",
        "data": {
            "id": order_id,
            "created_at": "2026-07-27T00:00:00Z",
            "modified_at": None,
            "status": "paid",
            "paid": True,
            "subtotal_amount": 22000,
            "discount_amount": 0,
            "net_amount": 22000,
            "tax_amount": 0,
            "total_amount": 22000,
            "refunded_amount": 0,
            "refunded_tax_amount": 0,
            "currency": "usd",
            "billing_reason": "subscription_create",
            "billing_address": None,
            "billing_name": None,
            "description": "Otclick Месяц",
            "discount": None,
            "applied_balance_amount": 0,
            "due_amount": 0,
            "refundable_amount": 22000,
            "refundable_tax_amount": 0,
            "invoice_number": "INV-1",
            "is_invoice_generated": False,
            "receipt_number": None,
            "platform_fee_amount": 0,
            "platform_fee_currency": "usd",
            "next_payment_attempt_at": None,
            "seats": None,
            "customer_id": "cus_1",
            "product_id": "prod_1",
            "discount_id": None,
            "subscription_id": "sub_1",
            "checkout_id": None,
            "metadata": {},
            "custom_field_data": {},
            "customer": {
                "id": "cus_1",
                "created_at": "2026-07-27T00:00:00Z",
                "modified_at": None,
                "metadata": {},
                "external_id": user_id,
                "type": "individual",
                "billing_name": None,
                "email": "a@b.c",
                "email_verified": True,
                "name": None,
                "billing_address": None,
                "tax_id": None,
                "organization_id": "org_1",
                "deleted_at": None,
                "avatar_url": "https://x/y.png",
            },
            "product": {
                "id": "prod_1",
                "created_at": "2026-07-27T00:00:00Z",
                "modified_at": None,
                "name": "Otclick Месяц",
                "description": None,
                "recurring_interval": "month",
                "recurring_interval_count": 1,
                "trial_interval": None,
                "trial_interval_count": None,
                "meter_interval": None,
                "meter_interval_count": None,
                "visibility": "public",
                "is_recurring": True,
                "is_archived": False,
                "organization_id": "org_1",
                "metadata": {},
                "prices": [],
                "benefits": [],
                "medias": [],
            },
            "subscription": {
                "id": "sub_1",
                "created_at": "2026-07-27T00:00:00Z",
                "modified_at": None,
                "amount": 22000,
                "currency": "usd",
                "recurring_interval": "month",
                "recurring_interval_count": 1,
                "status": "active",
                "trial_start": None,
                "trial_end": None,
                "paused_at": None,
                "pause_at_period_end": False,
                "resumes_at": None,
                "current_meter_period_start": None,
                "current_meter_period_end": None,
                "current_period_start": "2026-07-27T00:00:00Z",
                "current_period_end": period_end,
                "cancel_at_period_end": False,
                "canceled_at": None,
                "started_at": "2026-07-27T00:00:00Z",
                "ends_at": None,
                "ended_at": None,
                "customer_id": "cus_1",
                "product_id": "prod_1",
                "discount_id": None,
                "checkout_id": None,
                "customer_cancellation_reason": None,
                "customer_cancellation_comment": None,
                "metadata": {},
                "custom_field_data": {},
            },
            "items": [],
        },
    }


def _verified(payload: dict):
    """Run a payload through real signature verification → SDK model."""
    from app.services import billing

    body, headers = _sign(payload)
    with patch.object(billing.settings, "POLAR_WEBHOOK_SECRET", SECRET):
        return billing.verify_polar_webhook(body, headers)


# ─── signature verification ──────────────────────────────────

def test_valid_signature_parses_event():
    event = _verified(_order_paid_payload())
    # В моделях SDK поле называется TYPE (alias "type") — billing читает оба,
    # иначе каждое событие уходило бы в "unhandled".
    assert event.TYPE == "order.paid"
    assert event.data.customer.external_id == "u1"


def test_bad_signature_rejected():
    from polar_sdk.webhooks import WebhookVerificationError

    from app.services import billing

    body, headers = _sign(_order_paid_payload(), secret="someone-elses-secret")
    with patch.object(billing.settings, "POLAR_WEBHOOK_SECRET", SECRET):
        with pytest.raises(WebhookVerificationError):
            billing.verify_polar_webhook(body, headers)


def test_missing_secret_rejected():
    from polar_sdk.webhooks import WebhookVerificationError

    from app.services import billing

    body, headers = _sign(_order_paid_payload())
    with patch.object(billing.settings, "POLAR_WEBHOOK_SECRET", ""):
        with pytest.raises(WebhookVerificationError):
            billing.verify_polar_webhook(body, headers)


# ─── order.paid ──────────────────────────────────────────────

def test_order_paid_activates_plan():
    from app.services import billing

    event = _verified(_order_paid_payload())
    payments = _fluent([{"id": "p1"}])  # newly inserted
    profiles = _fluent([{"id": "u1"}])
    with patch.object(
        billing.service_client, "table", side_effect=_table_router(payments, profiles)
    ):
        out = billing.process_polar_event(event)

    assert out["status"] == "activated"
    update = profiles.update.call_args[0][0]
    assert update["plan"] == "active"
    assert update["polar_subscription_id"] == "sub_1"
    # Срок берём у провайдера, а не гадаем по сумме платежа.
    assert update["plan_expires_at"].startswith("2026-08-27")
    row = payments.upsert.call_args[0][0]
    assert row["provider"] == "polar"
    assert row["provider_payment_id"] == "ord_1"
    assert row["amount"] == 22000


def test_order_paid_duplicate_does_not_reactivate():
    from app.services import billing

    event = _verified(_order_paid_payload())
    payments = _fluent([])  # ignore_duplicates → conflict, no rows back
    profiles = _fluent([{"id": "u1"}])
    with patch.object(
        billing.service_client, "table", side_effect=_table_router(payments, profiles)
    ):
        out = billing.process_polar_event(event)

    assert out["status"] == "duplicate"
    profiles.update.assert_not_called()


# ─── subscription lifecycle ──────────────────────────────────

def _subscription_payload(event_type, user_id="u1", period_end="2026-08-27T00:00:00Z"):
    order = _order_paid_payload(user_id=user_id, period_end=period_end)
    subscription = dict(order["data"]["subscription"])
    subscription["customer"] = order["data"]["customer"]
    subscription["prices"] = []
    subscription["discount"] = None
    subscription["meters"] = []
    subscription["pending_update"] = None
    product = dict(order["data"]["product"])
    product["attached_custom_fields"] = []
    subscription["product"] = product
    return {"type": event_type, "timestamp": "2026-07-27T00:00:00Z", "data": subscription}


def test_subscription_active_activates():
    from app.services import billing

    event = _verified(_subscription_payload("subscription.active"))
    profiles = _fluent([{"id": "u1"}])
    with patch.object(billing.service_client, "table", return_value=profiles):
        out = billing.process_polar_event(event)

    assert out["status"] == "activated"
    assert profiles.update.call_args[0][0]["plan"] == "active"


def test_subscription_canceled_keeps_paid_period():
    from app.services import billing

    event = _verified(_subscription_payload("subscription.canceled"))
    profiles = _fluent([{"id": "u1"}])
    with patch.object(billing.service_client, "table", return_value=profiles):
        out = billing.process_polar_event(event)

    assert out["status"] == "cancelled"
    update = profiles.update.call_args[0][0]
    assert update == {"plan": "cancelled"}  # срок не трогаем — период оплачен


def test_subscription_revoked_falls_back_to_free():
    from app.services import billing

    event = _verified(_subscription_payload("subscription.revoked"))
    profiles = _fluent([{"id": "u1"}])
    with patch.object(billing.service_client, "table", return_value=profiles):
        out = billing.process_polar_event(event)

    assert out["status"] == "free"
    # Не блокировка, а возврат в бесплатный тир.
    assert profiles.update.call_args[0][0] == {"plan": "free", "plan_expires_at": None}


def test_unhandled_event_type_ignored():
    from app.services import billing

    event = _verified(_subscription_payload("subscription.updated"))
    with patch.object(billing.service_client, "table") as t:
        out = billing.process_polar_event(event)
    assert out["status"] == "ignored"
    t.assert_not_called()


# ─── checkout / portal ───────────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_url_passes_external_customer_id():
    from app.services import billing

    polar = MagicMock()
    polar.__enter__.return_value = polar
    polar.checkouts.create.return_value = SimpleNamespace(url="https://polar.sh/checkout/xyz")

    with (
        patch.object(billing.settings, "POLAR_ACCESS_TOKEN", "tok"),
        patch.object(billing.settings, "POLAR_PRODUCT_MONTH", "prod_1"),
        patch.object(billing, "Polar", return_value=polar),
    ):
        out = await billing.polar_checkout_url("u1", "month")

    assert out.checkout_url == "https://polar.sh/checkout/xyz"
    request = polar.checkouts.create.call_args.kwargs["request"]
    # Связка плательщика с аккаунтом — вместо костыля AccountId у CloudPayments.
    assert request["external_customer_id"] == "u1"
    assert request["products"] == ["prod_1"]


@pytest.mark.asyncio
async def test_checkout_without_product_id_raises():
    from app.services import billing

    with (
        patch.object(billing.settings, "POLAR_ACCESS_TOKEN", "tok"),
        patch.object(billing.settings, "POLAR_PRODUCT_MONTH", ""),
        pytest.raises(billing.BillingNotConfigured),
    ):
        await billing.polar_checkout_url("u1", "month")


@pytest.mark.asyncio
async def test_portal_url_from_customer_session():
    from app.services import billing

    polar = MagicMock()
    polar.__enter__.return_value = polar
    polar.customer_sessions.create.return_value = SimpleNamespace(
        customer_portal_url="https://polar.sh/portal/abc"
    )
    with (
        patch.object(billing.settings, "POLAR_ACCESS_TOKEN", "tok"),
        patch.object(billing, "Polar", return_value=polar),
    ):
        url = await billing.customer_portal_url("u1")

    assert url == "https://polar.sh/portal/abc"
    assert polar.customer_sessions.create.call_args.kwargs["request"] == {
        "external_customer_id": "u1"
    }


# ─── status ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_status_returns_plan_and_history():
    from app.services import billing

    profiles = _fluent(
        {"plan": "active", "trial_ends": None, "plan_expires_at": "2026-08-27T00:00:00+00:00"}
    )
    payments = _fluent(
        [
            {
                "provider_payment_id": "ord_1",
                "amount": 22000,
                "status": "completed",
                "created_at": "2026-07-27T00:00:00+00:00",
            }
        ]
    )
    with patch.object(
        billing.service_client, "table", side_effect=_table_router(payments, profiles)
    ):
        out = await billing.get_status("u1")

    assert out.plan == "active"
    assert out.next_charge_at is not None
    assert out.history[0].provider_payment_id == "ord_1"


# ─── webhook endpoint ────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import webhooks

    app = FastAPI()
    app.include_router(webhooks.router)
    return TestClient(app)


def test_webhook_bad_signature_403(client):
    from app.services import billing

    body, headers = _sign(_order_paid_payload(), secret="wrong")
    with patch.object(billing.settings, "POLAR_WEBHOOK_SECRET", SECRET):
        res = client.post("/api/webhooks/polar", content=body, headers=headers)
    assert res.status_code == 403


def test_webhook_valid_signature_processes(client):
    from app.services import billing

    body, headers = _sign(_order_paid_payload())
    with (
        patch.object(billing.settings, "POLAR_WEBHOOK_SECRET", SECRET),
        patch.object(billing, "process_polar_event", return_value={"status": "activated"}) as proc,
    ):
        res = client.post("/api/webhooks/polar", content=body, headers=headers)

    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert proc.call_args[0][0].data.customer.external_id == "u1"


def test_webhook_answers_200_even_if_processing_explodes(client):
    """Polar ретраит на не-2xx — упавшая обработка не должна множить попытки."""
    from app.services import billing

    body, headers = _sign(_order_paid_payload())
    with (
        patch.object(billing.settings, "POLAR_WEBHOOK_SECRET", SECRET),
        patch.object(billing, "process_polar_event", side_effect=RuntimeError("db down")),
    ):
        res = client.post("/api/webhooks/polar", content=body, headers=headers)
    assert res.status_code == 200
