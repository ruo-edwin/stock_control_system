from fastapi import APIRouter, Depends, HTTPException, Form, Request, Body
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, case   # ✅ ADDED: case
from datetime import datetime, timedelta
from passlib.context import CryptContext
import pytz
from pathlib import Path
from backend.db import SessionLocal
from backend.auth_utils import verify_token
from backend import models
from backend.config import templates
from pywebpush import webpush, WebPushException
import os, json


router = APIRouter(prefix="/superadmin", tags=["superadmin"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

NAIROBI_TZ = pytz.timezone("Africa/Nairobi")


# ----------------------------------------------------
# DB Session
# ----------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------------------------------
# SUPERADMIN AUTH CHECK
# ----------------------------------------------------
def require_superadmin(request: Request, db: Session):
    token_data = verify_token(request)
    if not token_data:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = db.query(models.User).filter(
        models.User.id == token_data["user_id"]
    ).first()

    if not user or user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin allowed")

    return user


# ----------------------------------------------------
# SUPERADMIN PANEL PAGE
# ----------------------------------------------------
@router.get("/admin_panel", response_class=HTMLResponse)
def admin_panel_page(request: Request, db: Session = Depends(get_db)):
    require_superadmin(request, db)
    return templates.TemplateResponse(
        "super_admin.html",
        {"request": request}
    )


# ----------------------------------------------------
# CREATE SUPERADMIN (RUN ONCE)
# ----------------------------------------------------
@router.post("/create_superadmin")
def create_superadmin(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    existing = db.query(models.User).filter(
        models.User.role == "superadmin"
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Superadmin already exists!"
        )

    new_superadmin = models.User(
        business_id=None,
        username=username,
        password_hash=pwd_context.hash(password),
        role="superadmin",
        is_active=1,
        last_login=datetime.utcnow()
    )

    db.add(new_superadmin)
    db.commit()

    return {"message": "🔥 Superadmin created successfully!"}


# ----------------------------------------------------
# 1️⃣ GET ALL CLIENTS + SUBSCRIPTIONS + LAST LOGIN + ✅ NEW METRICS
#    ✅ Adds:
#      - products_count
#      - last_sale_date (from orders)
#      - total_revenue (sum of orders.total_amount)
#    ✅ NEW ADDITION:
#      - is_installed (from onboarding events: event == "install_app")
#    ✅ Also avoids N+1 queries by using one aggregated query
# ----------------------------------------------------
@router.get("/get_all_clients")
def get_all_clients(request: Request, db: Session = Depends(get_db)):
    require_superadmin(request, db)

    # ✅ ADDED: aggregated install flag per business (no N+1)
    install_subq = (
        db.query(
            models.OnboardingEvent.business_id.label("business_id"),
            func.max(
                case(
                    (models.OnboardingEvent.event == "install_app", 1),
                    else_=0
                )
            ).label("is_installed")
        )
        .group_by(models.OnboardingEvent.business_id)
        .subquery()
    )

    rows = (
        db.query(
            models.Business.id.label("business_id"),
            models.Business.business_name,
            models.Business.phone,

            # owner
            models.User.username.label("username"),
            models.User.last_login.label("last_login_utc"),

            # subscription
            models.Subscription.status.label("subscription_status"),
            models.Subscription.is_active.label("is_active"),
            models.Subscription.end_date.label("end_date"),

            # ✅ NEW metrics
            func.count(func.distinct(models.Product.id)).label("products_count"),
            func.max(models.Order.created_at).label("last_sale_date_utc"),
            func.coalesce(func.sum(models.Order.total_amount), 0).label("total_revenue"),

            # ✅ ADDED: install status (1/0)
            func.coalesce(install_subq.c.is_installed, 0).label("is_installed"),
        )
        .outerjoin(models.Subscription, models.Subscription.business_id == models.Business.id)
        .outerjoin(
            models.User,
            (models.User.business_id == models.Business.id) & (models.User.role != "superadmin")
        )
        .outerjoin(models.Product, models.Product.business_id == models.Business.id)
        .outerjoin(models.Order, models.Order.business_id == models.Business.id)

        # ✅ ADDED: join install subquery
        .outerjoin(install_subq, install_subq.c.business_id == models.Business.id)

        .group_by(
            models.Business.id,
            models.Business.business_name,
            models.Business.phone,
            models.User.username,
            models.User.last_login,
            models.Subscription.status,
            models.Subscription.is_active,
            models.Subscription.end_date,
            install_subq.c.is_installed,  # ✅ ADDED: needed due to select
        )
        .all()
    )

    output = []
    now_utc = datetime.utcnow()

    for r in rows:
        # Days left
        days_left = None
        if r.end_date:
            days_left = (r.end_date - now_utc).days

        # last login UTC -> Nairobi time
        last_login_local = None
        if r.last_login_utc:
            last_login_local = r.last_login_utc.replace(tzinfo=pytz.utc).astimezone(NAIROBI_TZ)

        # ✅ last sale UTC -> Nairobi time
        last_sale_local = None
        if r.last_sale_date_utc:
            last_sale_local = r.last_sale_date_utc.replace(tzinfo=pytz.utc).astimezone(NAIROBI_TZ)

        output.append({
            "business_id": r.business_id,
            "business_name": r.business_name,
            "username": r.username,
            "phone": r.phone,

            "last_login": last_login_local.isoformat() if last_login_local else None,
            "subscription_status": r.subscription_status if r.subscription_status else "none",
            "days_left": days_left,
            "is_active": bool(r.is_active) if r.is_active is not None else False,

            # ✅ NEW fields (for your super admin table)
            "products_count": int(r.products_count or 0),
            "last_sale_date": last_sale_local.isoformat() if last_sale_local else None,
            "total_revenue": float(r.total_revenue or 0),

            # ✅ ADDED: installation flag
            "is_installed": bool(r.is_installed),
        })

    return output


# ----------------------------------------------------
# 2️⃣ ACTIVATE SUBSCRIPTION
# ----------------------------------------------------
@router.post("/activate/{business_id}")
def activate_subscription(
    business_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    require_superadmin(request, db)

    subscription = db.query(models.Subscription).filter(
        models.Subscription.business_id == business_id
    ).first()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    subscription.status = "active"
    subscription.is_active = True
    subscription.start_date = datetime.utcnow()
    subscription.end_date = datetime.utcnow() + timedelta(days=30)
    subscription.updated_at = datetime.utcnow()

    db.commit()
    return {"message": "Subscription activated for 30 days"}


# ----------------------------------------------------
# 3️⃣ RENEW +30 DAYS
# ----------------------------------------------------
@router.post("/renew/{business_id}")
def renew_subscription(
    business_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    require_superadmin(request, db)

    subscription = db.query(models.Subscription).filter(
        models.Subscription.business_id == business_id
    ).first()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    subscription.status = "active"
    subscription.is_active = True
    subscription.end_date += timedelta(days=30)
    subscription.updated_at = datetime.utcnow()

    db.commit()
    return {"message": "Subscription renewed +30 days"}


# ----------------------------------------------------
# 4️⃣ SUSPEND BUSINESS
# ----------------------------------------------------
@router.post("/suspend/{business_id}")
def suspend_account(
    business_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    require_superadmin(request, db)

    subscription = db.query(models.Subscription).filter(
        models.Subscription.business_id == business_id
    ).first()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    subscription.status = "suspended"
    subscription.is_active = False
    subscription.updated_at = datetime.utcnow()

    db.commit()
    return {"message": "Business suspended"}


# ----------------------------------------------------
# 5️⃣ REACTIVATE BUSINESS
# ----------------------------------------------------
@router.post("/reactivate/{business_id}")
def reactivate_account(
    business_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    require_superadmin(request, db)

    subscription = db.query(models.Subscription).filter(
        models.Subscription.business_id == business_id
    ).first()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    subscription.status = "active"
    subscription.is_active = True
    subscription.updated_at = datetime.utcnow()

    db.commit()
    return {"message": "Business reactivated"}


# ----------------------------------------------------
# 6️⃣ SEND MANUAL PUSH REMINDER
# ----------------------------------------------------
@router.post("/push_reminder/{business_id}")
def push_reminder(
    business_id: int,
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db)
):
    require_superadmin(request, db)

    title = (payload.get("title") or "").strip()
    message = (payload.get("message") or "").strip()
    if not title or not message:
        raise HTTPException(status_code=400, detail="Title and message are required")

    subs = db.query(models.PushSubscription).filter(
        models.PushSubscription.business_id == business_id
    ).all()

    if not subs:
        return {"message": "No subscribed devices for this business", "sent": 0, "failed": 0, "deleted": 0}

    vapid_private_pem = os.getenv("VAPID_PRIVATE_KEY_PEM")
    vapid_sub = os.getenv("VAPID_SUB", "mailto:admin@smartpos.local")

    if not vapid_private_pem:
        raise HTTPException(status_code=500, detail="VAPID_PRIVATE_KEY_PEM not set")

    pem_text = vapid_private_pem.replace("\\n", "\n").strip()
    pem_path = Path(f"/tmp/vapid_private_{business_id}.pem")
    pem_path.write_text(pem_text, encoding="utf-8")

    sent = 0
    failed = 0
    deleted = 0

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth}
                },
                data=json.dumps({"title": title, "body": message, "url": "/auth/dashboard"}),
                vapid_private_key=str(pem_path),
                vapid_claims={"sub": vapid_sub}
            )
            sent += 1

        except WebPushException as ex:
            failed += 1

            status_code = None
            try:
                if ex.response is not None:
                    status_code = ex.response.status_code
            except Exception:
                status_code = None

            if status_code in (404, 410):
                db.delete(sub)
                deleted += 1

    if deleted:
        db.commit()

    return {"message": "Reminder processed", "sent": sent, "failed": failed, "deleted": deleted}
