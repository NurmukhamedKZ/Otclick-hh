from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SubscribeResponse(BaseModel):
    """Hosted Polar checkout — the frontend just redirects here."""

    checkout_url: str


class PortalResponse(BaseModel):
    """Polar customer portal: payment methods, invoices, cancellation."""

    portal_url: str


class PaymentEntry(BaseModel):
    provider_payment_id: str
    amount: int | None = None
    status: str
    created_at: datetime | None = None


class BillingStatusResponse(BaseModel):
    plan: str
    trial_ends: datetime | None = None
    plan_expires_at: datetime | None = None
    next_charge_at: datetime | None = None
    has_access: bool = False  # inside a paid window right now (false = free tier)
    history: list[PaymentEntry]
