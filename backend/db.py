from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os
from pathlib import Path

# -------------------------------------------------
# Load environment variables from backend/.env
# -------------------------------------------------
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is missing or not set.")

print("DATABASE_URL LOADED:", DATABASE_URL)

# -------------------------------------------------
# Ensure correct MySQL driver format (safe conversion)
# -------------------------------------------------
if DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "mysql://", "mysql+pymysql://", 1
    )

# -------------------------------------------------
# Create engine
# -------------------------------------------------
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # Reconnect automatically if MySQL times out
    pool_recycle=280,     # Recycle connections every ~5 minutes
)

# -------------------------------------------------
# Session factory
# -------------------------------------------------
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# -------------------------------------------------
# Base model
# -------------------------------------------------
Base = declarative_base()

# -------------------------------------------------
# Dependency for FastAPI
# -------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()