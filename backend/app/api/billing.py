from app.api.deps import get_current_user
from app.schemas.billing import BillingStatusResponse, PortalResponse, SubscribeResponse
from app.services import billing as billing_service
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(plan: str | None = None, user_id: str = Depends(get_current_user)):
    """Create a Polar checkout session and hand the URL to the frontend to redirect to."""
    try:
        return await billing_service.polar_checkout_url(user_id, plan)
    except billing_service.BillingNotConfigured as ex:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(ex)
        ) from ex


@router.post("/portal", response_model=PortalResponse)
async def portal(user_id: str = Depends(get_current_user)):
    """Polar customer portal — where the user actually cancels the subscription."""
    try:
        return PortalResponse(portal_url=await billing_service.customer_portal_url(user_id))
    except billing_service.BillingNotConfigured as ex:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(ex)
        ) from ex


@router.get("/status", response_model=BillingStatusResponse)
async def status_(user_id: str = Depends(get_current_user)):
    return await billing_service.get_status(user_id)
