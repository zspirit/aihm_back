"""Create an admin user interactively.

Usage: python -m app.scripts.create_admin
"""

import getpass
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.tenant import Tenant
from app.models.user import User

settings = get_settings()
sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(sync_url)


def main():
    print("=== AIHM — Creation admin ===\n")

    company = input("Nom entreprise: ").strip()
    if not company:
        print("Nom entreprise requis.")
        sys.exit(1)

    full_name = input("Nom complet: ").strip()
    if not full_name:
        print("Nom complet requis.")
        sys.exit(1)

    email = input("Email: ").strip()
    if not email or "@" not in email:
        print("Email invalide.")
        sys.exit(1)

    password = getpass.getpass("Mot de passe (min 8 car.): ")
    if len(password) < 8:
        print("Mot de passe trop court.")
        sys.exit(1)

    confirm = getpass.getpass("Confirmer mot de passe: ")
    if password != confirm:
        print("Les mots de passe ne correspondent pas.")
        sys.exit(1)

    with Session(engine) as session:
        existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing:
            print(f"Erreur: email {email} deja utilise.")
            sys.exit(1)

        tenant = Tenant(name=company)
        session.add(tenant)
        session.flush()

        user = User(
            tenant_id=tenant.id,
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role="admin",
        )
        session.add(user)
        session.commit()

        print("\nAdmin cree avec succes!")
        print(f"  Entreprise: {company}")
        print(f"  Email: {email}")
        print(f"  Connectez-vous sur {settings.FRONTEND_URL}")


if __name__ == "__main__":
    main()
