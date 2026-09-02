
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta

from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request
from starlette.status import HTTP_401_UNAUTHORIZED
from sqlalchemy.orm import Session

from backend import models
from backend.db import get_db


load_dotenv()


# ----------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30)
)

if not SECRET_KEY:
    raise ValueError(
        "SECRET_KEY environment variable is missing or not set."
    )


# ----------------------------------------------------
# TOKEN BLACKLIST
# ----------------------------------------------------

# Simple in-memory blacklist.
# Note: this resets whenever the application restarts.
token_blacklist = set()


# ----------------------------------------------------
# CREATE ACCESS TOKEN
# ----------------------------------------------------

def create_access_token(
    data: dict,
    expires_delta: timedelta = None
):
    to_encode = data.copy()

    expire = datetime.utcnow() + (
        expires_delta
        or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    to_encode.update({"exp": expire})

    return jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


# ----------------------------------------------------
# BLACKLIST TOKEN
# ----------------------------------------------------

def blacklist_token(token: str):
    token_blacklist.add(token)


# ----------------------------------------------------
# VERIFY TOKEN
# ----------------------------------------------------
#
# This is the actual authentication logic.
#
# It:
# 1. Gets the access token from the browser cookie
# 2. Checks that the token exists
# 3. Checks that it isn't blacklisted
# 4. Decodes the JWT
# 5. Gets the user ID
# 6. Finds that user in the database
# 7. Returns the SQLAlchemy User object
#
# IMPORTANT:
# This function receives the REAL database session.
# It is not itself used directly with Depends(...).
# ----------------------------------------------------

def verify_token(
    request: Request,
    db: Session
):
    token = request.cookies.get("access_token")

    # No token or blacklisted token
    if not token or token in token_blacklist:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    try:
        # Decode JWT
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        # Get user ID from token
        user_id = payload.get("user_id")

        if not user_id:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

        # Find user in database
        user = (
            db.query(models.User)
            .filter(models.User.id == user_id)
            .first()
        )

        if not user:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

        # Return actual SQLAlchemy User object
        return user

    except JWTError:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )


# ----------------------------------------------------
# FASTAPI CURRENT USER DEPENDENCY
# ----------------------------------------------------
#
# This is the function that routes should use:
#
# current_user: models.User = Depends(get_current_user)
#
# FastAPI automatically provides:
# - request
# - database session
#
# Then this function passes both into verify_token().
# ----------------------------------------------------

def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
):
    return verify_token(request, db)

