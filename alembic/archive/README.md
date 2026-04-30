# Alembic — Archive des revisions legacy

## Contexte

Ce dossier contient 22 fichiers de revision alembic générés au fil du projet (entre le `96aab1dc0bfa_initial_schema.py` de février 2026 et les dernières revisions d'avril 2026).

**Aucune de ces revisions n'a jamais été appliquée sur un environnement.** Le schéma prod et dev a été créé directement via `Base.metadata.create_all(engine)` depuis `scripts/init_db.py`. La chaîne alembic accumulait les intentions de DDL sans jamais tourner, ce qui a produit avec le temps :

- **1 revision ID dupliqué** — `a1b2c3d4e5f6` utilisé par `add_enterprise_and_offer.py` ET `add_feedback_and_anonymization.py` (conflit jamais détecté car alembic n'était pas exécuté).
- **3 heads non réconciliées** — `c1d2e3f4a5b6` (add_modules_config_to_tenants), `ba70d609fe91` (add_missing_tenant_columns), `f2b3c4d5e6f7` (add_skills_table).
- **Divergence complète avec la réalité** — à force de tourner via `create_all`, le schéma réel n'avait plus de rapport avec ce qu'alembic "croyait" devoir appliquer.

## Décision (Chantier 12, avril 2026)

Plutôt que de tenter de réparer cette chaîne fictive :

1. On archive les 22 fichiers ici, hors du scan d'alembic (`script_location = alembic` ne voit que `alembic/versions/`).
2. On génère une **nouvelle baseline** reflétant l'état réel du schéma prod/dev.
3. On stamp les environnements existants sur cette baseline.
4. On interdit désormais `create_all()` en prod — toute modif schéma passe par une revision alembic.

Voir `alembic/README.md` pour la procédure en vigueur à partir de maintenant.

## Pourquoi conserver ces fichiers

Ils documentent **l'intention** historique du design (ajout de scorecards, skills, enterprise, etc.) même si le DDL a été en pratique appliqué par `create_all`. Utile pour :

- Retrouver quand un champ a été introduit (via `git log` sur le fichier correspondant).
- Comprendre a posteriori les choix de nommage ou de colonnes.
- Fouiller un op spécifique (`op.alter_column`, contraintes, index) si on veut reproduire la logique dans une vraie revision.

**Ne pas les réactiver** en les déplaçant dans `versions/` — ils casseraient alembic (duplicate ID, multiple heads).
