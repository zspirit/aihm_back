"""Seed la base de données avec les données de démo.

⚠️ Ce script ne crée PLUS les tables (plus de Base.metadata.create_all).
   Le schéma est géré exclusivement par alembic à partir de Chantier 12.

Pré-requis avant de lancer: `alembic upgrade head` (crée les 22 tables via
la baseline) — ce script refuse de tourner si alembic_version est absente
ou non stampée.

Usage:
    alembic upgrade head         # une fois, crée le schéma
    python scripts/init_db.py    # peuple les données de démo (idempotent)

Comportement:
- Si un tenant existe déjà → le script sort sans rien faire.
- Sinon → crée 1 tenant + 2 users (admin + recruteur) + 1 position demo.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.position import Position
from app.models.tenant import Tenant
from app.models.user import User


def _assert_alembic_stamped(engine) -> None:
    """Refuse de tourner si alembic n'a pas été initialisé.

    Garantit qu'on ne seed jamais une DB dont le schéma n'a pas été créé via
    alembic — sinon on perd le filet de sécurité qu'on a mis en place.
    """
    with engine.connect() as conn:
        if not conn.dialect.has_table(conn, "alembic_version"):
            print(
                "[ERREUR] Table 'alembic_version' absente.\n"
                "         Lance d'abord:  alembic upgrade head",
                file=sys.stderr,
            )
            sys.exit(2)
        rows = list(conn.execute(text("SELECT version_num FROM alembic_version")))
        if not rows:
            print(
                "[ERREUR] alembic_version est vide — schéma pas encore appliqué.\n"
                "         Lance:  alembic upgrade head",
                file=sys.stderr,
            )
            sys.exit(2)
        print(f"[OK] alembic_version: {[r[0] for r in rows]}")


def init() -> None:
    settings = get_settings()
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    _assert_alembic_stamped(engine)

    with Session(engine) as session:
        existing = session.query(Tenant).first()
        if existing:
            print("[WARN] Base déjà seedée — rien à faire.")
            return

        tenant = Tenant(name="AIHM Demo")
        session.add(tenant)
        session.flush()

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

        position = Position(
            tenant_id=tenant.id,
            title="Developpeur Full Stack",
            description="Backend Python/FastAPI + Frontend React/TypeScript",
            required_skills=[
                {"name": "Python", "level_required": 3},
                {"name": "React", "level_required": 3},
            ],
            seniority_level="mid",
            status="active",
            created_by=admin.id,
        )
        session.add(position)
        session.commit()

        print("[OK] Seed terminé — tenant + 2 users + 1 position.")
        print("\n=== Comptes de démo ===")
        print("  admin@aihm.ai       / Admin123!")
        print("  recruteur@aihm.ai   / Recruteur123!")


if __name__ == "__main__":
    init()
