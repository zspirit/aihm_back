"""
Seed riche pour remplir tous les écrans de l'app.

Contrairement à seed.py (22 candidats, pas d'entreprises) et seed_demo.py (10
candidats mono-tenant), ce script construit un dataset complet :

  • 1 Tenant + 5 Users (admin, 3 recruteurs, 1 viewer)
  • 8 Enterprises avec statuts variés (active / inactive / archived)
  • 18 Positions réparties sur les entreprises, avec :
      - statuts variés (active, paused, filled, archived, draft)
      - SLA delays variés (late, urgent, soon, normal, sans SLA)
      - niveaux de seniority variés
  • ~55 Candidats sur toutes les étapes du pipeline
  • Applications (1 par candidat + matches cross-position)
  • Interviews : scheduled, in_progress, completed, failed, no_answer
  • Analyses + Reports pour les interviews "evaluated"
  • Scorecards pour quelques évalués
  • Offers (draft / sent / signed) pour certaines applications
  • MatchScores pour le matching cross-position
  • Catalogue de Skills
  • Consents pour les stades avancés

Usage :
  python scripts/seed_rich.py            # seed si DB vide, sinon no-op
  python scripts/seed_rich.py --force    # wipe + re-seed
  python scripts/seed_rich.py --keep     # garde tenant existant si présent
"""

import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.analysis import Analysis
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.enterprise import Enterprise
from app.models.interview import Interview
from app.models.match_score import MatchScore
from app.models.notification import Notification
from app.models.offer import Offer
from app.models.position import Position
from app.models.report import Report
from app.models.scorecard import Scorecard
from app.models.skill import Skill
from app.models.tenant import Tenant
from app.models.transcription import Transcription
from app.models.user import User
from app.models.webhook_subscription import WebhookSubscription

settings = get_settings()
sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(sync_url)

NOW = datetime.now(timezone.utc)
random.seed(42)  # reproductible


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def rand_date(days_back_min: int = 1, days_back_max: int = 60) -> datetime:
    return NOW - timedelta(
        days=random.randint(days_back_min, days_back_max),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )


def future_date(days_forward_min: int = 1, days_forward_max: int = 30) -> datetime:
    return NOW + timedelta(
        days=random.randint(days_forward_min, days_forward_max),
        hours=random.randint(0, 23),
    )


def pick(items: list):
    return random.choice(items)


def wipe_all(session: Session, tenant_id: uuid.UUID | None = None) -> None:
    """Supprime toutes les données (ordre respectant les FK).

    Si tenant_id est fourni, on ne supprime que ce tenant. Sinon, wipe total.
    """
    # Ordre reverse-dépendance : feuilles d'abord, puis racines.
    if tenant_id is not None:
        # Tenant-scoped wipe via raw SQL (chaines cascade gèrent la descente).
        session.execute(text("DELETE FROM offers WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM applications WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM match_scores WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM match_sessions WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM scorecards WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text(
            "DELETE FROM reports WHERE interview_id IN "
            "(SELECT id FROM interviews WHERE tenant_id = :t)"
        ), {"t": str(tenant_id)})
        session.execute(text(
            "DELETE FROM analyses WHERE interview_id IN "
            "(SELECT id FROM interviews WHERE tenant_id = :t)"
        ), {"t": str(tenant_id)})
        session.execute(text(
            "DELETE FROM transcriptions WHERE interview_id IN "
            "(SELECT id FROM interviews WHERE tenant_id = :t)"
        ), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM interviews WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text(
            "DELETE FROM consents WHERE candidate_id IN "
            "(SELECT id FROM candidates WHERE tenant_id = :t)"
        ), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM candidates WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM positions WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM enterprises WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM skills WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM notifications WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM audit_logs WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM webhook_subscriptions WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": str(tenant_id)})
        session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": str(tenant_id)})
    else:
        for tbl in [
            Offer, Application, MatchScore, Scorecard, Report, Analysis,
            Transcription, Interview, Consent, Notification, AuditLog,
            WebhookSubscription, Candidate, Position, Enterprise, Skill,
            User, Tenant,
        ]:
            session.execute(tbl.__table__.delete())
    session.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Data constants
# ═══════════════════════════════════════════════════════════════════════════

ENTERPRISES = [
    {
        "name": "TechNova Solutions",
        "industry": "Éditeur logiciel",
        "domain": "technova.ma",
        "contact_email": "contact@technova.ma",
        "contact_phone": "+212522334455",
        "address": "12 Bd Zerktouni, Casablanca",
        "status": "active",
    },
    {
        "name": "FinSecure Bank",
        "industry": "Banque",
        "domain": "finsecure.ma",
        "contact_email": "rh@finsecure.ma",
        "contact_phone": "+212537445566",
        "address": "Avenue Mohammed V, Rabat",
        "status": "active",
    },
    {
        "name": "MediHealth Group",
        "industry": "Santé",
        "domain": "medihealth.ma",
        "contact_email": "recrutement@medihealth.ma",
        "contact_phone": "+212522778899",
        "address": "Anfa, Casablanca",
        "status": "active",
    },
    {
        "name": "GreenEnergy Maroc",
        "industry": "Énergie & Environnement",
        "domain": "greenenergy.ma",
        "contact_email": "jobs@greenenergy.ma",
        "contact_phone": "+212539112233",
        "address": "Zone Franche, Tanger",
        "status": "active",
    },
    {
        "name": "EduTech Academy",
        "industry": "Éducation / Formation",
        "domain": "edutech.ma",
        "contact_email": "rh@edutech.ma",
        "contact_phone": "+212524998877",
        "address": "Gueliz, Marrakech",
        "status": "active",
    },
    {
        "name": "LogiSmart",
        "industry": "Logistique & Supply Chain",
        "domain": "logismart.ma",
        "contact_email": "contact@logismart.ma",
        "contact_phone": "+212522667788",
        "address": "Port de Casablanca",
        "status": "active",
    },
    {
        "name": "RetailX",
        "industry": "Distribution",
        "domain": "retailx.ma",
        "contact_email": "rh@retailx.ma",
        "contact_phone": "+212522554433",
        "address": "Ain Sebaa, Casablanca",
        "status": "inactive",
    },
    {
        "name": "Acme Legacy Corp",
        "industry": "Industrie",
        "domain": "acme-legacy.ma",
        "contact_email": "contact@acme-legacy.ma",
        "contact_phone": None,
        "address": None,
        "status": "archived",
    },
]

# Positions : (enterprise_idx, title, seniority, level, status, sla_days,
#              sla_offset_days, auto_advance, auto_reject, required_skills)
# sla_offset_days : décalage de la deadline par rapport à maintenant.
#   négatif => SLA dépassé (late), 0-2 => urgent, 3-7 => soon, >7 => normal
POSITIONS = [
    # TechNova (5 postes actifs, variété SLA)
    (0, "Développeur Full Stack Python/React", "senior", "senior", "active", 45, -3,
     80, 35, ["Python", "FastAPI", "React", "TypeScript", "PostgreSQL", "Docker"]),
    (0, "Data Scientist NLP", "mid", "mid", "active", 30, 1,
     75, 40, ["Python", "NLP", "Transformers", "PyTorch", "Scikit-learn"]),
    (0, "DevOps Engineer Senior", "senior", "senior", "active", 45, 5,
     80, 40, ["Docker", "Kubernetes", "Terraform", "AWS", "CI/CD", "Linux"]),
    (0, "Lead Tech Back-end", "lead", "lead", "active", 60, 20,
     85, 45, ["Python", "Architecture", "PostgreSQL", "Redis", "Leadership"]),
    (0, "UX Designer", "mid", "mid", "draft", None, None,
     None, None, ["Figma", "UI/UX", "Design System", "Recherche utilisateur"]),

    # FinSecure (3 actifs + 1 pourvu)
    (1, "Chef de Projet IT Conformité", "senior", "senior", "active", 45, -8,
     80, 40, ["Gestion de projet", "Agile", "Scrum", "JIRA", "Conformité bancaire"]),
    (1, "Développeur Java Spring Boot", "mid", "mid", "active", 30, 2,
     75, 35, ["Java", "Spring Boot", "Oracle", "Kafka", "Microservices"]),
    (1, "Analyste Risque Crédit", "mid", "mid", "active", 60, 25,
     None, None, ["SAS", "Risk Management", "Python", "Excel avancé"]),
    (1, "Cyber Security Officer", "senior", "senior", "filled", 45, -15,
     None, None, ["CISSP", "SOC", "SIEM", "ISO 27001", "Audit sécurité"]),

    # MediHealth (2 actifs)
    (2, "Data Engineer Santé", "mid", "mid", "active", 30, 4,
     75, 40, ["Python", "SQL", "ETL", "HL7/FHIR", "Airflow"]),
    (2, "Responsable SI Hospitalier", "senior", "manager", "active", 60, 15,
     80, 40, ["Gestion équipe", "ITIL", "Gouvernance SI", "Hôpital"]),

    # GreenEnergy (2 actifs, 1 paused)
    (3, "Ingénieur Énergies Renouvelables", "mid", "mid", "active", 45, 0,
     70, 35, ["Photovoltaïque", "Éolien", "CAO", "AutoCAD"]),
    (3, "Développeur IoT Embedded", "senior", "senior", "active", 45, 10,
     80, 40, ["C/C++", "MQTT", "Raspberry Pi", "LoRa", "Linux embedded"]),
    (3, "Commercial grands comptes", "senior", "senior", "paused", None, None,
     None, None, ["Vente B2B", "Négociation", "Grands comptes", "Energie"]),

    # EduTech (2 postes dont 1 pourvu)
    (4, "Formateur Data Science", "mid", "mid", "active", 30, 3,
     70, 35, ["Pédagogie", "Python", "Machine Learning", "SQL"]),
    (4, "Product Owner Plateforme LMS", "senior", "senior", "filled", 45, -30,
     None, None, ["Product Management", "Agile", "LMS", "Analytics"]),

    # LogiSmart (2 postes dont 1 paused)
    (5, "Responsable Logistique", "senior", "senior", "active", 45, 6,
     75, 40, ["Supply Chain", "WMS", "Gestion équipe", "Lean"]),
    (5, "Développeur ERP SAP", "mid", "mid", "paused", None, None,
     None, None, ["SAP", "ABAP", "MM/SD", "Débogage"]),

    # Acme Legacy (archivé — 1 poste archived)
    (7, "Technicien support N1", "junior", "junior", "archived", None, None,
     None, None, ["Support utilisateur", "Windows", "Ticketing"]),
]

# Candidats : (name, email_handle, phone_suffix, target_position_idx,
#              pipeline_status, cv_score, has_profile_data)
# position_idx est l'index dans POSITIONS ci-dessus
CANDIDATES = [
    # --- Full Stack Python/React (idx 0) — 6 candidats ---
    ("Youssef El Amrani", "youssef.amrani", "661", 0, "evaluated", 88.5, True),
    ("Fatima Zahra Benali", "fatima.benali", "662", 0, "call_done", 76.0, True),
    ("Omar Kettani", "omar.kettani", "663", 0, "consent_given", 68.3, True),
    ("Salma Ouazzani", "salma.ouazzani", "664", 0, "cv_analyzed", 91.2, True),
    ("Mehdi Alaoui", "mehdi.alaoui", "665", 0, "invited", 55.0, True),
    ("Amine Berrada", "amine.berrada", "667", 0, "cv_uploaded", None, False),

    # --- Data Scientist NLP (idx 1) — 5 candidats ---
    ("Imane Hajji", "imane.hajji", "668", 1, "evaluated", 92.1, True),
    ("Reda Bouazza", "reda.bouazza", "669", 1, "call_done", 78.4, True),
    ("Kenza Lamrani", "kenza.lamrani", "670", 1, "call_scheduled", 82.1, True),
    ("Hamza Filali", "hamza.filali", "671", 1, "cv_analyzed", 65.0, True),
    ("Zineb Idrissi", "zineb.idrissi", "672", 1, "invited", 79.9, True),

    # --- DevOps Senior (idx 2) — 4 candidats ---
    ("Ayoub Cherkaoui", "ayoub.cherkaoui", "677", 2, "evaluated", 90.3, True),
    ("Saad Jabri", "saad.jabri", "678", 2, "consent_given", 77.8, True),
    ("Meryem Benhima", "meryem.benhima", "679", 2, "call_in_progress", 84.5, True),
    ("Ilyas Doukkali", "ilyas.doukkali", "680", 2, "cv_analyzed", 71.0, True),

    # --- Lead Back-end (idx 3) — 3 candidats ---
    ("Adil Lahbabi", "adil.lahbabi", "611", 3, "call_done", 81.0, True),
    ("Karima Sefrioui", "karima.sefrioui", "612", 3, "cv_analyzed", 87.3, True),
    ("Nabil Chaouki", "nabil.chaouki", "613", 3, "new", None, False),

    # --- UX Designer (idx 4, draft) — 2 candidats ---
    ("Dounia El Khattabi", "dounia.khattabi", "614", 4, "cv_uploaded", None, False),
    ("Tarik Bennouna", "tarik.bennouna", "615", 4, "new", None, False),

    # --- Chef de Projet Conformité (idx 5, SLA dépassé) — 4 candidats ---
    ("Rachid Tazi", "rachid.tazi", "673", 5, "evaluated", 84.0, True),
    ("Layla Moussaoui", "layla.moussaoui", "674", 5, "call_done", 73.5, True),
    ("Khalid Bennani", "khalid.bennani", "675", 5, "cv_analyzed", 62.0, True),
    ("Houda Fassi", "houda.fassi", "676", 5, "invited", None, True),

    # --- Développeur Java Spring Boot (idx 6) — 5 candidats ---
    ("Younes Ramdani", "younes.ramdani", "616", 6, "call_scheduled", 74.5, True),
    ("Soumia Maghraoui", "soumia.maghraoui", "617", 6, "consent_given", 69.0, True),
    ("Anas Senhaji", "anas.senhaji", "618", 6, "cv_analyzed", 80.2, True),
    ("Loubna Tarik", "loubna.tarik", "619", 6, "invited", 58.7, True),
    ("Hassan Zemzami", "hassan.zemzami", "620", 6, "cv_uploaded", None, False),

    # --- Analyste Risque Crédit (idx 7) — 3 candidats ---
    ("Nouhaila El Fassi", "nouhaila.elfassi", "621", 7, "call_done", 79.0, True),
    ("Bilal Saadi", "bilal.saadi", "622", 7, "cv_analyzed", 66.5, True),
    ("Sara Laraki", "sara.laraki", "623", 7, "new", None, False),

    # --- Cyber Security (idx 8, filled) — 2 candidats (anciens) ---
    ("Mohammed Hachimi", "mohammed.hachimi", "624", 8, "evaluated", 93.0, True),
    ("Siham Mekouar", "siham.mekouar", "625", 8, "call_done", 71.2, True),

    # --- Data Engineer Santé (idx 9) — 4 candidats ---
    ("Othmane Berrechid", "othmane.berrechid", "626", 9, "call_scheduled", 77.8, True),
    ("Naima Khalid", "naima.khalid", "627", 9, "consent_given", 72.0, True),
    ("Wassim Laazouli", "wassim.laazouli", "628", 9, "cv_analyzed", 68.5, True),
    ("Jihane Rachidi", "jihane.rachidi", "629", 9, "new", None, False),

    # --- Responsable SI Hospitalier (idx 10) — 2 candidats ---
    ("Driss Benkirane", "driss.benkirane", "630", 10, "call_done", 85.7, True),
    ("Malika Oudaha", "malika.oudaha", "631", 10, "cv_analyzed", 70.0, True),

    # --- Ingénieur EnR (idx 11) — 3 candidats ---
    ("Youssra Ghali", "youssra.ghali", "632", 11, "invited", 76.0, True),
    ("Abdessamad Rhalib", "abdessamad.rhalib", "633", 11, "cv_analyzed", 82.5, True),
    ("Fadoua Tebbani", "fadoua.tebbani", "634", 11, "cv_uploaded", None, False),

    # --- Dev IoT (idx 12) — 2 candidats ---
    ("Ismail Hmimsa", "ismail.hmimsa", "635", 12, "call_done", 88.0, True),
    ("Hajar Saoudi", "hajar.saoudi", "636", 12, "cv_analyzed", 74.0, True),

    # --- Formateur Data Science (idx 13) — 3 candidats ---
    ("Mouad El Farouki", "mouad.elfarouki", "637", 13, "consent_given", 80.5, True),
    ("Rania Boukhris", "rania.boukhris", "638", 13, "cv_analyzed", 68.0, True),
    ("Samir Ouadi", "samir.ouadi", "639", 13, "invited", 71.0, True),

    # --- Product Owner LMS (idx 14, filled) — 1 candidat ---
    ("Chadia El Ouardi", "chadia.elouardi", "640", 14, "evaluated", 89.5, True),

    # --- Responsable Logistique (idx 15) — 2 candidats ---
    ("Zakariae Bouknadel", "zakariae.bouknadel", "641", 15, "call_in_progress", 78.0, True),
    ("Amal Chami", "amal.chami", "642", 15, "cv_analyzed", 66.0, True),
]


SKILLS_CATALOG = [
    "Python", "JavaScript", "TypeScript", "React", "Vue.js", "Angular",
    "Node.js", "FastAPI", "Django", "Flask", "Spring Boot", "Java",
    "C#", ".NET", "Go", "Rust", "C/C++", "PHP", "Laravel", "Symfony",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch",
    "Docker", "Kubernetes", "Terraform", "AWS", "GCP", "Azure",
    "CI/CD", "Jenkins", "GitLab CI", "GitHub Actions",
    "NLP", "Machine Learning", "PyTorch", "TensorFlow", "Scikit-learn",
    "Figma", "UI/UX", "Design System", "Adobe XD",
    "Gestion de projet", "Agile", "Scrum", "Kanban", "JIRA",
    "Supply Chain", "SAP", "ERP", "Lean", "Six Sigma",
    "CISSP", "ISO 27001", "SIEM", "SOC", "Audit sécurité",
]


# ═══════════════════════════════════════════════════════════════════════════
# Seed function
# ═══════════════════════════════════════════════════════════════════════════

def seed():
    force = "--force" in sys.argv
    keep = "--keep" in sys.argv

    with Session(engine) as session:
        existing_tenant = session.execute(
            select(Tenant).where(Tenant.name == "AIHM Demo").limit(1)
        ).scalar_one_or_none()

        if existing_tenant:
            if keep:
                print("[seed_rich] Tenant 'AIHM Demo' existe — --keep → rien à faire.")
                return
            if not force:
                print(
                    "[seed_rich] Tenant 'AIHM Demo' existe déjà.\n"
                    "             Relance avec --force pour wipe + re-seed,\n"
                    "             ou --keep pour ne rien faire."
                )
                return
            print(f"[seed_rich] --force → wipe du tenant {existing_tenant.id}…")
            wipe_all(session, tenant_id=existing_tenant.id)
            print("[seed_rich] Wipe OK.")

        # ───── 1. Tenant ─────
        tenant = Tenant(name="AIHM Demo")
        session.add(tenant)
        session.flush()
        tid = tenant.id
        print(f"[seed_rich] Tenant créé : {tenant.name} ({tid})")

        # ───── 2. Users ─────
        admin = User(
            tenant_id=tid, email="admin@aihm.ai",
            password_hash=hash_password("Admin123!"),
            full_name="Zakaria Gafaoui", role="admin",
            email_verified=True,
        )
        sara = User(
            tenant_id=tid, email="sara@aihm.ai",
            password_hash=hash_password("Sara123!"),
            full_name="Sara El Fassi", role="recruiter",
            email_verified=True,
        )
        karim = User(
            tenant_id=tid, email="karim@aihm.ai",
            password_hash=hash_password("Karim123!"),
            full_name="Karim Benjelloun", role="recruiter",
            email_verified=True,
        )
        leila = User(
            tenant_id=tid, email="leila@aihm.ai",
            password_hash=hash_password("Leila123!"),
            full_name="Leila Moustapha", role="recruiter",
            email_verified=True,
        )
        viewer = User(
            tenant_id=tid, email="viewer@aihm.ai",
            password_hash=hash_password("Viewer123!"),
            full_name="Ahmed Tazi", role="viewer",
            email_verified=True,
        )
        session.add_all([admin, sara, karim, leila, viewer])
        session.flush()
        recruiters = [sara, karim, leila]
        print(f"[seed_rich] {5} users créés.")

        # ───── 3. Enterprises ─────
        enterprises: list[Enterprise] = []
        for data in ENTERPRISES:
            e = Enterprise(
                tenant_id=tid,
                created_by=admin.id,
                created_at=rand_date(30, 180),
                **data,
            )
            session.add(e)
            enterprises.append(e)
        session.flush()
        print(f"[seed_rich] {len(enterprises)} entreprises créées.")

        # ───── 4. Skills catalog ─────
        for skill_name in SKILLS_CATALOG:
            session.add(Skill(tenant_id=tid, name=skill_name))
        session.flush()
        print(f"[seed_rich] {len(SKILLS_CATALOG)} compétences cataloguées.")

        # ───── 5. Positions ─────
        positions: list[Position] = []
        for (
            ent_idx, title, seniority, level, status, sla_days, sla_offset,
            auto_adv, auto_rej, skills,
        ) in POSITIONS:
            sla_deadline = (NOW + timedelta(days=sla_offset)) if sla_offset is not None else None
            creator = pick([admin] + recruiters)
            p = Position(
                tenant_id=tid,
                enterprise_id=enterprises[ent_idx].id,
                title=title,
                description=f"Poste chez {enterprises[ent_idx].name}. Mission : contribuer aux projets clés de l'équipe.",
                required_skills=skills,
                seniority_level=seniority,
                level=level,
                status=status,
                sla_days=sla_days,
                sla_deadline=sla_deadline,
                auto_advance_threshold=auto_adv,
                auto_reject_threshold=auto_rej,
                created_by=creator.id,
                created_at=rand_date(20, 90),
            )
            session.add(p)
            positions.append(p)
        session.flush()
        print(f"[seed_rich] {len(positions)} postes créés.")
        status_counts: dict[str, int] = {}
        for p in positions:
            status_counts[p.status] = status_counts.get(p.status, 0) + 1
        for s, c in sorted(status_counts.items()):
            print(f"            · {s}: {c}")

        # ───── 6. Candidates ─────
        candidates: list[tuple[Candidate, int, str]] = []  # (candidate, pos_idx, pipeline_status)
        for name, email_handle, phone_suffix, pos_idx, status, score, has_profile in CANDIDATES:
            position = positions[pos_idx]
            c = Candidate(
                tenant_id=tid,
                position_id=position.id,
                name=name,
                email=f"{email_handle}@gmail.com",
                phone=f"+212{phone_suffix}234567",
                pipeline_status=status,
                cv_score=score,
                cv_score_explanation={
                    "competences": random.randint(50, 95),
                    "experience": random.randint(50, 95),
                    "formation": random.randint(50, 95),
                } if score else None,
                profile_score=score + random.uniform(-5, 5) if score and has_profile else None,
                profile_competencies={
                    "technical": [
                        {"name": s, "level": random.randint(3, 5)}
                        for s in random.sample(position.required_skills, min(3, len(position.required_skills)))
                    ],
                    "experience": [
                        {
                            "title": "Développeur Senior" if "senior" in (position.seniority_level or "") else "Développeur",
                            "company": pick(["DXC", "Atos", "Capgemini", "CGI", "Sopra Steria"]),
                            "duration_months": random.randint(12, 60),
                        }
                    ],
                    "languages": [
                        {"name": "Français", "level": "natif"},
                        {"name": "Anglais", "level": pick(["courant", "professionnel"])},
                    ],
                    "soft_skills": random.sample(
                        ["Leadership", "Communication", "Autonomie", "Travail d'équipe", "Curiosité"], 3
                    ),
                } if has_profile else None,
                tags=random.sample(["top-talent", "urgent", "relocation", "bilingue"], random.randint(0, 2)),
                created_at=rand_date(3, 45),
            )
            session.add(c)
            candidates.append((c, pos_idx, status))
        session.flush()
        print(f"[seed_rich] {len(candidates)} candidats créés.")

        # ───── 7. Applications (1 par candidat sur son poste cible) ─────
        applications: dict[uuid.UUID, Application] = {}  # candidate_id -> Application
        for c, pos_idx, status in candidates:
            a = Application(
                tenant_id=tid,
                candidate_id=c.id,
                position_id=c.position_id,
                match_score=c.cv_score,
                pipeline_status=status,
                decision="accepted" if status == "evaluated" and (c.cv_score or 0) >= 80 else (
                    "rejected" if status == "evaluated" and (c.cv_score or 0) < 60 else None
                ),
                created_at=c.created_at,
            )
            session.add(a)
            applications[c.id] = a
        session.flush()
        print(f"[seed_rich] {len(applications)} applications créées.")

        # ───── 8. Consents (stades avancés) ─────
        consent_stages = {
            "consent_given", "call_scheduled", "call_in_progress",
            "call_done", "evaluated",
        }
        consents_count = 0
        for c, _, status in candidates:
            if status in consent_stages:
                session.add(Consent(
                    candidate_id=c.id,
                    token=f"seed-{c.id.hex[:12]}",
                    type="interview",
                    granted=True,
                    granted_at=rand_date(1, 25),
                    channel=pick(["email", "sms", "whatsapp"]),
                ))
                consents_count += 1
        session.flush()
        print(f"[seed_rich] {consents_count} consentements créés.")

        # ───── 9. Interviews (scheduled / in_progress / completed / failed) ─────
        interviews: list[tuple[Interview, Candidate, str]] = []
        interview_stages = {
            "call_scheduled", "call_in_progress", "call_done", "evaluated",
        }
        for c, _, status in candidates:
            if status not in interview_stages:
                continue

            if status == "call_scheduled":
                iv = Interview(
                    candidate_id=c.id, position_id=c.position_id, tenant_id=tid,
                    status="scheduled",
                    scheduled_at=future_date(1, 10),
                    attempt_number=1,
                )
            elif status == "call_in_progress":
                started = NOW - timedelta(minutes=random.randint(2, 8))
                iv = Interview(
                    candidate_id=c.id, position_id=c.position_id, tenant_id=tid,
                    status="in_progress",
                    scheduled_at=started - timedelta(minutes=5),
                    started_at=started,
                    attempt_number=1,
                )
            else:  # call_done, evaluated
                duration = random.randint(240, 720)
                started = rand_date(1, 20)
                iv = Interview(
                    candidate_id=c.id, position_id=c.position_id, tenant_id=tid,
                    status="completed",
                    scheduled_at=started - timedelta(hours=1),
                    started_at=started,
                    ended_at=started + timedelta(seconds=duration),
                    duration_seconds=duration,
                    questions_asked=[
                        "Parlez-nous de votre expérience professionnelle.",
                        "Quelles technologies maîtrisez-vous le mieux ?",
                        "Comment gérez-vous les deadlines serrées ?",
                        "Donnez un exemple de projet dont vous êtes fier.",
                        "Avez-vous des questions sur le poste ?",
                    ],
                    attempt_number=1,
                )
            session.add(iv)
            interviews.append((iv, c, status))

        # Ajout de quelques interviews failed / no_answer pour enrichir la vue
        failed_candidates = random.sample(
            [c for c, _, s in candidates if s in {"invited", "consent_given"}],
            min(3, len([c for c, _, s in candidates if s in {"invited", "consent_given"}])),
        )
        for c in failed_candidates:
            iv = Interview(
                candidate_id=c.id, position_id=c.position_id, tenant_id=tid,
                status=pick(["failed", "no_answer"]),
                scheduled_at=rand_date(1, 15),
                attempt_number=pick([1, 2]),
            )
            session.add(iv)
            interviews.append((iv, c, "failed"))

        session.flush()
        print(f"[seed_rich] {len(interviews)} interviews créés (scheduled/in_progress/completed/failed).")

        # ───── 10. Transcriptions + Analyses + Reports (evaluated) ─────
        analyses_count = 0
        reports_count = 0
        for iv, c, status in interviews:
            if iv.status != "completed":
                continue

            # Transcription systématique pour les completed
            session.add(Transcription(
                interview_id=iv.id,
                segments=[
                    {"speaker": "assistant", "text": "Bonjour, merci d'avoir pris le temps pour cet entretien.", "start": 0.0, "end": 4.2},
                    {"speaker": "candidate", "text": "Bonjour, merci à vous.", "start": 4.5, "end": 6.0},
                    {"speaker": "assistant", "text": "Pouvez-vous vous présenter en quelques mots ?", "start": 6.5, "end": 9.0},
                    {"speaker": "candidate", "text": f"Je suis {c.name.split()[0]}, j'ai {random.randint(3, 10)} ans d'expérience dans le développement.", "start": 9.5, "end": 15.0},
                ],
                full_text=f"Transcription complète de l'entretien avec {c.name}. Échange d'environ {iv.duration_seconds // 60 if iv.duration_seconds else 10} minutes couvrant les questions techniques, le parcours, et la motivation.",
                language_detected="fr",
                confidence_score=round(random.uniform(0.85, 0.98), 2),
            ))

            if status == "evaluated":
                score_global = int(c.cv_score or random.randint(60, 92))
                scores = {
                    "competences_techniques": random.randint(55, 95),
                    "communication": random.randint(60, 95),
                    "motivation": random.randint(65, 95),
                    "adequation_poste": random.randint(55, 95),
                    "score_global": score_global,
                }
                session.add(Analysis(
                    interview_id=iv.id,
                    scores=scores,
                    skills_extracted={
                        "techniques": random.sample(SKILLS_CATALOG[:20], 4),
                        "soft": random.sample(["Communication", "Leadership", "Autonomie", "Esprit d'équipe"], 2),
                    },
                    experience_examples=[
                        f"{random.randint(3, 10)} ans d'expérience en développement",
                        f"Projet SaaS multi-tenant de {random.randint(5, 30)}k utilisateurs",
                    ],
                    communication_indicators={
                        "clarte": pick(["excellente", "bonne", "correcte"]),
                        "structure": pick(["très organisée", "bien organisée", "à améliorer"]),
                        "ecoute": "attentive",
                    },
                    score_explanations={
                        "competences_techniques": "Bonne maîtrise des technologies demandées.",
                        "communication": "Réponses claires et structurées.",
                        "motivation": "Enthousiaste et motivé par le poste.",
                        "adequation_poste": "Profil en adéquation avec les besoins.",
                    },
                ))
                analyses_count += 1

                session.add(Report(
                    candidate_id=c.id,
                    interview_id=iv.id,
                    content={
                        "candidate_name": c.name,
                        "position_title": c.position.title if c.position else "N/A",
                        "score_global": score_global,
                        "cv_score": c.cv_score,
                        "scores": scores,
                        "recommandation": (
                            "✅ Candidat recommandé" if score_global >= 75
                            else "⚠️ Candidat à reconsidérer" if score_global >= 60
                            else "❌ Profil non retenu"
                        ),
                        "points_forts": [
                            "Expertise technique confirmée",
                            "Bonne communication",
                            "Motivation claire",
                        ],
                        "points_attention": [
                            "Exposition limitée à certains outils",
                            "À confirmer sur la gestion d'équipe",
                        ] if score_global < 85 else [],
                    },
                ))
                reports_count += 1
        session.flush()
        print(f"[seed_rich] {analyses_count} analyses + {reports_count} rapports créés.")

        # ───── 11. Scorecards (2-3 évaluateurs sur les candidats evaluated) ─────
        scorecards_count = 0
        for iv, c, status in interviews:
            if status != "evaluated":
                continue
            # 1 à 2 scorecards par interview évalué
            n_eval = random.randint(1, 2)
            evaluators = random.sample([admin] + recruiters, n_eval)
            for ev in evaluators:
                session.add(Scorecard(
                    interview_id=iv.id,
                    tenant_id=tid,
                    evaluator_id=ev.id,
                    technical=random.randint(3, 5),
                    problem_solving=random.randint(3, 5),
                    communication=random.randint(3, 5),
                    behavioral=random.randint(3, 5),
                    notes=pick([
                        "Excellent profil, recommandation forte.",
                        "Bonnes bases techniques, à confirmer sur le leadership.",
                        "Candidat motivé avec une bonne adéquation culturelle.",
                        None,
                    ]),
                ))
                scorecards_count += 1
        session.flush()
        print(f"[seed_rich] {scorecards_count} scorecards créés.")

        # ───── 12. Offers (quelques candidats evaluated avec score >= 80) ─────
        offers_count = 0
        for c, pos_idx, status in candidates:
            if status != "evaluated" or (c.cv_score or 0) < 80:
                continue
            app = applications.get(c.id)
            if not app:
                continue
            position = positions[pos_idx]
            if not position.enterprise_id:
                continue
            offer_status = pick(["draft", "sent", "sent", "signed", "signed"])
            offer = Offer(
                tenant_id=tid,
                enterprise_id=position.enterprise_id,
                application_id=app.id,
                salary_min=random.choice([35000, 45000, 55000, 65000, 80000]),
                salary_max=None,
                currency="MAD",
                contract_type="permanent",
                start_date=future_date(14, 60),
                benefits="Télétravail partiel, mutuelle, tickets restaurant",
                status=offer_status,
                sent_at=rand_date(1, 10) if offer_status != "draft" else None,
                signed_at=rand_date(1, 5) if offer_status == "signed" else None,
                created_by=pick([admin] + recruiters).id,
                created_at=rand_date(3, 15),
            )
            offer.salary_max = offer.salary_min + 15000
            session.add(offer)
            offers_count += 1
        session.flush()
        print(f"[seed_rich] {offers_count} offres créées.")

        # ───── 13. MatchScores (matching cross-position) ─────
        # Pour chaque candidat avec cv_score, on calcule 2-3 scores sur d'autres
        # postes actifs. Ça permet à l'écran Matching d'avoir du contenu.
        active_positions = [p for p in positions if p.status == "active"]
        match_count = 0
        for c, pos_idx, _ in candidates:
            if not c.cv_score:
                continue
            others = [p for p in active_positions if p.id != c.position_id]
            if not others:
                continue
            for p in random.sample(others, min(3, len(others))):
                # Score de matching dérivé du CV avec du bruit
                score = max(0, min(100, (c.cv_score or 50) + random.uniform(-25, 15)))
                session.add(MatchScore(
                    tenant_id=tid,
                    candidate_id=c.id,
                    position_id=p.id,
                    score=round(score, 1),
                    reasons={
                        "skills_match": round(random.uniform(0.4, 0.95), 2),
                        "seniority_match": pick([True, False]),
                        "top_skills": random.sample(p.required_skills, min(2, len(p.required_skills))),
                    },
                ))
                match_count += 1
        session.flush()
        print(f"[seed_rich] {match_count} match scores cross-position créés.")

        # ───── 14. Notifications (derniers événements) ─────
        notif_count = 0
        for c, _, status in candidates[:15]:
            msg_by_status = {
                "evaluated": f"Rapport disponible pour {c.name}",
                "call_done": f"Entretien terminé avec {c.name}",
                "call_scheduled": f"Entretien planifié avec {c.name}",
                "consent_given": f"Consentement reçu de {c.name}",
                "cv_analyzed": f"CV analysé : {c.name}",
            }
            msg = msg_by_status.get(status, f"Activité sur {c.name}")
            session.add(Notification(
                tenant_id=tid,
                user_id=pick([admin] + recruiters).id,
                type=pick(["interview_completed", "candidate_new", "report_ready"]),
                title=msg,
                message=f"Statut actuel : {status}",
                read=random.random() > 0.6,
                created_at=rand_date(0, 7),
            ))
            notif_count += 1
        session.flush()
        print(f"[seed_rich] {notif_count} notifications créées.")

        # ───── 15. Audit logs (quelques actions récentes) ─────
        audit_count = 0
        actions = [
            ("position.create", "position", "Création du poste"),
            ("candidate.create", "candidate", "Nouveau candidat"),
            ("interview.complete", "interview", "Entretien terminé"),
            ("offer.sent", "offer", "Offre envoyée"),
            ("user.login", "user", "Connexion"),
        ]
        for _ in range(20):
            action, entity_type, _ = pick(actions)
            session.add(AuditLog(
                tenant_id=tid,
                user_id=pick([admin] + recruiters).id,
                action=action,
                entity_type=entity_type,
                entity_id=str(uuid.uuid4()),
                details={"source": "seed_rich"},
                created_at=rand_date(0, 14),
            ))
            audit_count += 1
        session.flush()
        print(f"[seed_rich] {audit_count} entrées d'audit créées.")

        session.commit()
        print()
        print("═══════════════════════════════════════════════════════════════")
        print("✅ Seed terminé avec succès")
        print("═══════════════════════════════════════════════════════════════")
        print()
        print("Comptes de connexion :")
        print("  admin@aihm.ai      / Admin123!     (admin)")
        print("  sara@aihm.ai       / Sara123!      (recruiter)")
        print("  karim@aihm.ai      / Karim123!     (recruiter)")
        print("  leila@aihm.ai      / Leila123!     (recruiter)")
        print("  viewer@aihm.ai     / Viewer123!    (viewer)")
        print()
        print(f"Tenant : AIHM Demo ({tid})")
        print()


if __name__ == "__main__":
    seed()
