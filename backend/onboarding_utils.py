from sqlalchemy.exc import IntegrityError
from backend import models

def record_onboarding_event(db, business_id: int, event: str):
    try:
        obj = models.OnboardingEvent(business_id=business_id, event=event)
        db.add(obj)
        db.commit()
    except IntegrityError:
        db.rollback()  # already exists (unique constraint), ignore
