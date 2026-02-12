# AIHM Backend

API FastAPI pour AI Hiring Manager — pre-screening telephonique par IA.

## Stack

- **Python 3.12** / FastAPI / SQLAlchemy (async) / Alembic
- **PostgreSQL 16** / Redis 7 / MinIO (S3)
- **Celery** workers (scoring CV, appels Twilio, transcription Whisper, rapports)
- **Claude API** (scoring, analyse, generation questions)
- **Twilio** (appels telephoniques) / **Resend** (emails)
- **Sentry** (monitoring erreurs)

## Dev local

### Pre-requis

- Python 3.12+ (pyenv recommande)
- Docker + Docker Compose (PostgreSQL, Redis, MinIO)

### Installation

```bash
# Demarrer les services
docker compose up -d postgres redis minio

# Virtualenv
cd back
python -m venv venv
source venv/bin/activate  # ou venv\Scripts\activate (Windows)
pip install -e .

# Variables d'environnement
cp .env.example .env  # adapter les valeurs

# Migrations
alembic upgrade head

# Lancer le serveur
uvicorn app.main:app --reload

# Lancer le worker Celery (autre terminal)
celery -A app.workers.celery_app worker --loglevel=info
```

### Tests

```bash
# Necessite PostgreSQL + Redis en cours d'execution
pytest tests/ -v

# Tests unitaires seuls (sans DB)
pytest tests/test_security.py -v
```

### Scripts utilitaires

```bash
# Creer un admin
python -m app.scripts.create_admin

# Seed de donnees de test
python -m app.scripts.seed

# Backup DB
./scripts/backup.sh
```

## Deploiement production

### Architecture

```
VPS / Cloud
├── docker-compose.yml          # services de base
├── docker-compose.prod.yml     # overrides production
├── back/                       # API + workers
│   ├── Dockerfile
│   ├── .env                    # secrets (NE PAS COMMITER)
│   └── ...
└── front/                      # SPA React (nginx)
    ├── Dockerfile
    └── ...
```

### Variables d'environnement (.env)

| Variable | Description | Exemple |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL async | `postgresql+asyncpg://user:pass@host:5432/aihm` |
| `REDIS_URL` | Redis | `redis://localhost:6379/0` |
| `JWT_SECRET_KEY` | Cle secrete JWT | (generer 64 chars aleatoires) |
| `ANTHROPIC_API_KEY` | API Claude | `sk-ant-...` |
| `TWILIO_ACCOUNT_SID` | Twilio SID | `AC...` |
| `TWILIO_AUTH_TOKEN` | Twilio token | |
| `TWILIO_PHONE_NUMBER` | Numero Twilio | `+212...` |
| `TWILIO_WEBHOOK_BASE_URL` | URL publique webhooks | `https://api.aihm.ai` |
| `RESEND_API_KEY` | Resend API | `re_...` |
| `EMAIL_FROM` | Adresse expediteur | `noreply@aihm.ai` |
| `SENTRY_DSN` | Sentry DSN | `https://...@sentry.io/...` |
| `SENTRY_ENVIRONMENT` | Environnement | `production` |
| `FRONTEND_URL` | URL frontend | `https://app.aihm.ai` |
| `CORS_ORIGINS` | Origines CORS (JSON) | `["https://app.aihm.ai"]` |
| `S3_ENDPOINT` | MinIO endpoint | `http://minio:9000` |
| `S3_ACCESS_KEY` | MinIO access key | |
| `S3_SECRET_KEY` | MinIO secret key | |
| `DEBUG` | Mode debug | `false` |

### Deployer

```bash
# Premier deploiement
git clone https://github.com/zspirit/aihm_back.git /opt/aihm/back
git clone https://github.com/zspirit/aihm_front.git /opt/aihm/front
cp docker-compose.yml docker-compose.prod.yml /opt/aihm/
cd /opt/aihm

# Configurer les secrets
cp back/.env.example back/.env
nano back/.env

# Build et demarrer
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Migrations
docker compose exec -T backend bash -c "cd /app && PYTHONPATH=/app alembic upgrade head"

# Creer le premier admin
docker compose exec -it backend python -m app.scripts.create_admin
```

### Mise a jour

```bash
cd /opt/aihm/back && git pull origin main
cd /opt/aihm
docker compose -f docker-compose.yml -f docker-compose.prod.yml build backend celery-worker
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend celery-worker
docker compose exec -T backend bash -c "cd /app && PYTHONPATH=/app alembic upgrade head"
```

Le CI/CD GitHub Actions (`.github/workflows/deploy.yml`) automatise ce processus sur push main.

### Backup

Les backups PostgreSQL sont automatiques (toutes les 24h) via le service `db-backup`. Les fichiers sont stockes dans le volume `db_backups`.

```bash
# Backup manuel
docker compose exec db-backup /backup.sh

# Restaurer
gunzip < backup.sql.gz | docker compose exec -T postgres psql -U aihm aihm
```

### Health check

```
GET /health
```

Retourne l'etat de PostgreSQL, Redis et MinIO. Code 200 si tout OK.

## Securite

- JWT (access + refresh tokens)
- Rate limiting (slowapi)
- Security headers : HSTS, CSP, X-Frame-Options, Permissions-Policy
- Docs API desactivees en production
- Audit logging (actions sensibles tracees)
- RLS multi-tenant (isolation par tenant_id)
- Consentement obligatoire avant appel IA (RGPD / Loi 09-08)

## API endpoints

| Methode | Route | Description |
|---------|-------|-------------|
| POST | `/auth/register` | Inscription entreprise |
| POST | `/auth/login` | Connexion |
| POST | `/auth/refresh` | Refresh token |
| GET | `/auth/me` | Profil utilisateur |
| PUT | `/auth/me` | Modifier profil |
| POST | `/auth/change-password` | Changer mot de passe |
| GET/POST | `/auth/users` | Lister / inviter utilisateurs |
| GET | `/auth/audit-logs` | Journal d'audit (admin) |
| GET/POST | `/positions` | Lister / creer postes |
| GET/PUT/DELETE | `/positions/{id}` | Detail / modifier / supprimer poste |
| GET/POST | `/positions/{id}/candidates` | Lister / ajouter candidats |
| GET | `/positions/{id}/candidates/export` | Export CSV |
| GET/DELETE | `/candidates/{id}` | Detail / supprimer candidat |
| POST | `/candidates/{id}/grant-consent` | Accorder consentement |
| POST | `/candidates/{id}/interviews` | Planifier interview |
| GET | `/interviews/{id}` | Detail interview |
| GET | `/interviews/{id}/transcription` | Transcription |
| GET | `/interviews/{id}/analysis` | Analyse IA |
| GET | `/interviews/{id}/report` | Rapport complet |
| GET | `/consent/{token}` | Page consentement public |
| POST | `/consent/{token}/accept` | Accepter consentement |
| GET | `/analytics/overview` | KPIs globaux |
| GET | `/analytics/pipeline` | Pipeline candidats |
| GET | `/analytics/positions-stats` | Stats par poste |
| GET | `/health` | Health check |
