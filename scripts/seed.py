"""Seed database with test fixtures."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.tenant import Tenant
from app.models.user import User
from app.models.position import Position
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.interview import Interview
from app.models.transcription import Transcription
from app.models.analysis import Analysis
from app.models.report import Report
from app.models.audit_log import AuditLog

settings = get_settings()
sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(sync_url)


def seed():
    with Session(engine) as session:
        # Check if already seeded
        existing = session.execute(select(Tenant).limit(1)).scalar_one_or_none()
        if existing:
            print("DB already has data. Use --force to reset.")
            if "--force" not in sys.argv:
                return
            # Clean all data (respect FK order)
            session.execute(Report.__table__.delete())
            session.execute(Analysis.__table__.delete())
            session.execute(Transcription.__table__.delete())
            session.execute(Interview.__table__.delete())
            session.execute(Consent.__table__.delete())
            session.execute(AuditLog.__table__.delete())
            session.execute(Candidate.__table__.delete())
            session.execute(Position.__table__.delete())
            session.execute(User.__table__.delete())
            session.execute(Tenant.__table__.delete())
            session.commit()
            print("Cleaned existing data.")

        # Create tenant
        tenant = Tenant(name="AIHM Demo")
        session.add(tenant)
        session.flush()
        print(f"Tenant: {tenant.name} ({tenant.id})")

        # Create admin
        admin = User(
            tenant_id=tenant.id,
            email="admin@aihm.ai",
            password_hash=hash_password("Admin123!"),
            full_name="Zakaria Admin",
            role="admin",
        )
        session.add(admin)

        # Create recruiter
        recruiter = User(
            tenant_id=tenant.id,
            email="recruteur@aihm.ai",
            password_hash=hash_password("Recruteur123!"),
            full_name="Sara Recruteur",
            role="recruiter",
        )
        session.add(recruiter)

        # Create viewer
        viewer = User(
            tenant_id=tenant.id,
            email="viewer@aihm.ai",
            password_hash=hash_password("Viewer123!"),
            full_name="Ahmed Viewer",
            role="viewer",
        )
        session.add(viewer)
        session.flush()

        print(f"Admin: admin@aihm.ai / Admin123!")
        print(f"Recruteur: recruteur@aihm.ai / Recruteur123!")
        print(f"Viewer: viewer@aihm.ai / Viewer123!")

        # Create positions
        pos1 = Position(
            tenant_id=tenant.id,
            title="Developpeur Full Stack Python/React",
            description="Nous recherchons un developpeur full stack pour rejoindre notre equipe produit. Le candidat travaillera sur le backend Python/FastAPI et le frontend React.",
            required_skills=["Python", "FastAPI", "React", "TypeScript", "PostgreSQL", "Docker"],
            seniority_level="senior",
            status="active",
            created_by=recruiter.id,
        )
        session.add(pos1)

        pos2 = Position(
            tenant_id=tenant.id,
            title="Data Scientist NLP",
            description="Poste de Data Scientist specialise en NLP pour travailler sur nos modeles de traitement du langage naturel appliques au recrutement.",
            required_skills=["Python", "NLP", "Transformers", "PyTorch", "Scikit-learn"],
            seniority_level="mid",
            status="active",
            created_by=recruiter.id,
        )
        session.add(pos2)

        pos3 = Position(
            tenant_id=tenant.id,
            title="Chef de projet IT",
            description="Gestion de projets IT dans un environnement agile. Coordination des equipes de developpement.",
            required_skills=["Gestion de projet", "Agile", "Scrum", "JIRA", "Communication"],
            seniority_level="senior",
            status="draft",
            created_by=admin.id,
        )
        session.add(pos3)
        session.flush()

        print(f"Position 1: {pos1.title} ({pos1.id})")
        print(f"Position 2: {pos2.title} ({pos2.id})")
        print(f"Position 3: {pos3.title} ({pos3.id})")

        # Create candidates (without CV for now)
        candidates_data = [
            {"name": "Youssef El Amrani", "email": "youssef@test.ma", "phone": "+212661234567", "position": pos1},
            {"name": "Fatima Zahra Benali", "email": "fatima@test.ma", "phone": "+212662345678", "position": pos1},
            {"name": "Karim Tazi", "email": "karim@test.ma", "phone": "+212663456789", "position": pos2},
            {"name": "Amina Chraibi", "email": "amina@test.ma", "phone": "+212664567890", "position": pos2},
        ]

        for c_data in candidates_data:
            candidate = Candidate(
                tenant_id=tenant.id,
                position_id=c_data["position"].id,
                name=c_data["name"],
                email=c_data["email"],
                phone=c_data["phone"],
            )
            session.add(candidate)
            print(f"Candidat: {c_data['name']} -> {c_data['position'].title}")

        session.commit()
        print("\nFixtures creees avec succes!")


if __name__ == "__main__":
    seed()
