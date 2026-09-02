from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend import models
from backend.auth_utils import get_current_user
from backend.onboarding_utils import record_onboarding_event


router = APIRouter(
    prefix="/onboarding",
    tags=["onboarding"]
)


# ----------------------------------------------------
# DB DEPENDENCY
# ----------------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------------------------------
# MARK APP AS INSTALLED
# ----------------------------------------------------
# Called by the frontend when the user installs the PWA.
# Any authenticated user in that business can trigger it.
# The business_id comes from the logged-in User record.
# ----------------------------------------------------

@router.post("/mark_installed")
def mark_installed(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    business_id = current_user.business_id

    if not business_id:
        raise HTTPException(
            status_code=400,
            detail="No business associated with this user"
        )

    # Idempotent because of the onboarding event unique constraint
    record_onboarding_event(
        db,
        business_id,
        "install_app"
    )

    return {
        "message": "Install recorded"
    }


# ----------------------------------------------------
# ONBOARDING STATUS
# ----------------------------------------------------

@router.get("/status")
def onboarding_status(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    business_id = current_user.business_id

    if not business_id:
        raise HTTPException(
            status_code=400,
            detail="No business associated with this user"
        )

    # ------------------------------------------------
    # REALITY CHECKS
    # ------------------------------------------------

    has_product = (
        db.query(models.Product)
        .filter(
            models.Product.business_id == business_id
        )
        .first()
        is not None
    )

    has_sale = (
        db.query(models.Order)
        .filter(
            models.Order.business_id == business_id
        )
        .first()
        is not None
    )

    # ------------------------------------------------
    # EVENT CHECKS
    # ------------------------------------------------

    viewed_report = (
        db.query(models.OnboardingEvent)
        .filter(
            models.OnboardingEvent.business_id == business_id,
            models.OnboardingEvent.event == "view_report"
        )
        .first()
        is not None
    )

    installed_app = (
        db.query(models.OnboardingEvent)
        .filter(
            models.OnboardingEvent.business_id == business_id,
            models.OnboardingEvent.event == "install_app"
        )
        .first()
        is not None
    )

    # ------------------------------------------------
    # FOUR-STEP ONBOARDING
    # ------------------------------------------------

    steps = {
        "add_product": has_product,
        "sell_product": has_sale,
        "view_report": viewed_report or has_sale,
        "install_app": installed_app
    }

    completed = sum(
        1
        for value in steps.values()
        if value
    )

    progress = int(
        (completed / 4) * 100
    )

    # ------------------------------------------------
    # FIND NEXT ACTION
    # ------------------------------------------------

    def next_action_from_steps():
        if not steps["add_product"]:
            return "add_product"

        if not steps["sell_product"]:
            return "sell_product"

        if not steps["view_report"]:
            return "view_report"

        if not steps["install_app"]:
            return "install_app"

        return None

    next_action = next_action_from_steps()

    # ------------------------------------------------
    # ACTIVATION MODAL
    # ------------------------------------------------

    show_activation_modal = False

    if next_action and progress < 100:

        stage_event = (
            f"activation_modal_shown:{next_action}"
        )

        already_shown = (
            db.query(models.OnboardingEvent)
            .filter(
                models.OnboardingEvent.business_id == business_id,
                models.OnboardingEvent.event == stage_event
            )
            .first()
            is not None
        )

        if not already_shown:
            show_activation_modal = True

            record_onboarding_event(
                db,
                business_id,
                stage_event
            )

    return {
        "steps": steps,
        "progress": progress,
        "show_activation_modal": show_activation_modal,
        "next_action": next_action
    }