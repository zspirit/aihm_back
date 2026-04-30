"""Schéma audit — compare Base.metadata (modèles SQLAlchemy) vs l'état réel de la DB.

Sortie structurée, read-only (aucune DDL d'écriture):
  - Tables manquantes en DB (présentes dans les modèles)
  - Tables en DB pas dans les modèles (potentielles orphelines)
  - Pour chaque table commune: colonnes manquantes + colonnes en trop
  - État de alembic_version (table présente ? + version(s) stampée(s))

Usage:
  python scripts/audit_schema.py                    # DB locale (via settings)
  DATABASE_URL=postgresql+asyncpg://... python scripts/audit_schema.py   # autre DB

Exit code: 0 si schéma en phase avec les modèles, 1 sinon.
Contexte: Chantier 12 — consolidation alembic.
"""
from __future__ import annotations

import os
import sys

# Rendre 'app' importable quand on lance le script depuis back/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, inspect, text

# Charger TOUS les modèles pour peupler Base.metadata
import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import Base


def main() -> int:
    settings = get_settings()
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    inspector = inspect(engine)

    # Masquer mot de passe dans l'affichage
    display_url = sync_url
    if "@" in display_url and "://" in display_url:
        scheme, rest = display_url.split("://", 1)
        if "@" in rest:
            creds, host = rest.rsplit("@", 1)
            user = creds.split(":", 1)[0] if ":" in creds else creds
            display_url = f"{scheme}://{user}:***@{host}"

    db_tables = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables.keys())

    print("=" * 70)
    print(f"DB        : {display_url}")
    print(f"Tables DB : {len(db_tables)}")
    print(f"Modèles   : {len(model_tables)}")
    print("=" * 70)

    # État alembic_version
    with engine.connect() as conn:
        has_alembic = conn.dialect.has_table(conn, "alembic_version")
        if has_alembic:
            rows = list(conn.execute(text("SELECT version_num FROM alembic_version")))
            versions = [r[0] for r in rows]
            print(f"\nalembic_version : {versions or '(vide)'}")
        else:
            print("\nalembic_version : ❌ table absente (jamais stampé)")

    missing_in_db = model_tables - db_tables
    orphan_in_db = db_tables - model_tables - {"alembic_version"}
    common = model_tables & db_tables

    print()
    if missing_in_db:
        print(f"❌ Tables MANQUANTES en DB ({len(missing_in_db)}):")
        for t in sorted(missing_in_db):
            print(f"   - {t}")
    else:
        print("✅ Aucune table manquante en DB")

    print()
    if orphan_in_db:
        print(f"⚠️  Tables en DB SANS modèle correspondant ({len(orphan_in_db)}):")
        for t in sorted(orphan_in_db):
            print(f"   - {t}")
    else:
        print("✅ Aucune table orpheline")

    print()
    print("--- Diff colonnes (tables communes) ---")
    col_diffs = 0
    for t in sorted(common):
        db_cols = {c["name"] for c in inspector.get_columns(t)}
        model_cols = set(Base.metadata.tables[t].columns.keys())
        missing_cols = model_cols - db_cols
        extra_cols = db_cols - model_cols
        if missing_cols or extra_cols:
            col_diffs += 1
            print(f"\n  {t}:")
            if missing_cols:
                print(f"    missing in DB : {sorted(missing_cols)}")
            if extra_cols:
                print(f"    extra in DB   : {sorted(extra_cols)}")
    if col_diffs == 0:
        print("  ✅ Aucun diff de colonnes sur les tables communes")

    print()
    print("=" * 70)
    clean = not missing_in_db and not orphan_in_db and col_diffs == 0
    if clean:
        print("✅ Schéma DB ALIGNÉ avec les modèles SQLAlchemy")
    else:
        total_issues = len(missing_in_db) + len(orphan_in_db) + col_diffs
        print(f"❌ {total_issues} divergence(s) — voir détails ci-dessus")
    print("=" * 70)

    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
