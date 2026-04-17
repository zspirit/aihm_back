"""Initialize database without migrations."""
import sys
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.security import hash_password
from app.core.database import Base
from app.models.tenant import Tenant
from app.models.user import User
from app.models.position import Position

settings = get_settings()
sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(sync_url)

def init():
    """Initialize database with tables and seed data."""
    # Create all tables
    Base.metadata.create_all(engine)
    print("[OK] Database tables created")

    with Session(engine) as session:
        # Check if already seeded
        existing = session.query(Tenant).first()
        if existing:
            print("[WARN] Database already seeded")
            return

        # Create tenant
        tenant = Tenant(name="AIHM Demo")
        session.add(tenant)
        session.flush()

        # Create users
        admin = User(
            tenant_id=tenant.id,
            email="admin@aihm.ai",
            password_hash=hash_password("Admin123!"),
            full_name="Zakaria Gafaoui",
            role="admin",
        )
        recruiter = User(
            tenant_id=tenant.id,
            email="recruteur@aihm.ai",
            password_hash=hash_password("Recruteur123!"),
            full_name="Sara El Fassi",
            role="recruiter",
        )
        session.add_all([admin, recruiter])
        session.flush()

        # Create a position
        position = Position(
            tenant_id=tenant.id,
            title="Developpeur Full Stack",
            description="Backend Python/FastAPI + Frontend React/TypeScript",
            required_skills=[{"name": "Python", "level_required": 3}, {"name": "React", "level_required": 3}],
            seniority_level="mid",
            status="active",
            created_by=admin.id,
        )
        session.add(position)
        session.commit()

        print("[OK] Database initialized with seed data")
        print("\n=== Login Credentials ===")
        print("[EMAIL] Email: admin@aihm.ai")
        print("[PASS] Password: Admin123!")

if __name__ == "__main__":
    init()
