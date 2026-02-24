import os
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend.auth_utils import verify_token
from backend import models

router = APIRouter(prefix="/push", tags=["push"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/vapid_public_key")
def vapid_public_key():
    """
    Return the VAPID public key for the browser Push API.
    IMPORTANT: This must be the 'B...' base64url key (no padding).
    """
    public_key = os.getenv("VAPID_PUBLIC_KEY", "").strip()

    if not public_key:
        raise HTTPException(status_code=500, detail="VAPID_PUBLIC_KEY not set")

    # Safety: remove whitespace/newlines if pasted badly
    public_key = "".join(public_key.split())

    # Basic sanity check: browser key almost always starts with "B"
    # (Not strict, but helps catch the 'M...' PEM/DER mistake)
    if public_key.startswith("M") or "BEGIN" in public_key:
        raise HTTPException(
            status_code=500,
            detail="VAPID_PUBLIC_KEY is wrong format. It must be a browser 'B...' key (base64url), not PEM/DER."
        )

    return {"publicKey": public_key}


@router.post("/subscribe")
def subscribe(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    token_data = verify_token(request)
    if not token_data:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = db.query(models.User).filter(models.User.id == token_data["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.business_id:
        raise HTTPException(status_code=400, detail="User has no business_id (cannot subscribe)")

    endpoint = payload.get("endpoint")
    keys = payload.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Invalid subscription payload")

    # ✅ UPSERT by endpoint (same device updates if they re-subscribe)
    existing = db.query(models.PushSubscription).filter(
        models.PushSubscription.endpoint == endpoint
    ).first()

    if existing:
        existing.user_id = user.id
        existing.business_id = user.business_id
        existing.p256dh = p256dh
        existing.auth = auth
        db.commit()
        return {"message": "Updated subscription"}

    sub = models.PushSubscription(
        user_id=user.id,
        business_id=user.business_id,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth
    )

    db.add(sub)
    db.commit()
    return {"message": "Subscribed"}
