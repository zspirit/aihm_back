"""Seed database with rich test fixtures."""

import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.analysis import Analysis
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.interview import Interview
from app.models.position import Position
from app.models.report import Report
from app.models.tenant import Tenant
from app.models.transcription import Transcription
from app.models.user import User
from app.models.webhook_subscription import WebhookSubscription

settings = get_settings()
sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(sync_url)

NOW = datetime.now(timezone.utc)


def rand_date(days_back_min=1, days_back_max=60):
    return NOW - timedelta(
        days=random.randint(days_back_min, days_back_max),
        hours=random.randint(0, 23),
    )


def seed():
    with Session(engine) as session:
        existing = session.execute(select(Tenant).limit(1)).scalar_one_or_none()
        if existing:
            print("DB already has data. Use --force to reset.")
            if "--force" not in sys.argv:
                return
            for tbl in [
                Report, Analysis, Transcription, Interview, Consent,
                AuditLog, WebhookSubscription, Candidate, Position, User, Tenant,
            ]:
                session.execute(tbl.__table__.delete())
            session.commit()
            print("Cleaned existing data.")

        # --- Tenant ---
        tenant = Tenant(name="AIHM Demo")
        session.add(tenant)
        session.flush()
        tid = tenant.id

        # --- Users ---
        admin = User(
            tenant_id=tid, email="admin@aihm.ai",
            password_hash=hash_password("Admin123!"),
            full_name="Zakaria Gafaoui", role="admin",
        )
        recruiter = User(
            tenant_id=tid, email="recruteur@aihm.ai",
            password_hash=hash_password("Recruteur123!"),
            full_name="Sara El Fassi", role="recruiter",
        )
        recruiter2 = User(
            tenant_id=tid, email="karim@aihm.ai",
            password_hash=hash_password("Karim123!"),
            full_name="Karim Benjelloun", role="recruiter",
        )
        viewer = User(
            tenant_id=tid, email="viewer@aihm.ai",
            password_hash=hash_password("Viewer123!"),
            full_name="Ahmed Tazi", role="viewer",
        )
        session.add_all([admin, recruiter, recruiter2, viewer])
        session.flush()

        print("=== Utilisateurs ===")
        print("  admin@aihm.ai / Admin123!")
        print("  recruteur@aihm.ai / Recruteur123!")
        print("  karim@aihm.ai / Karim123!")
        print("  viewer@aihm.ai / Viewer123!")

        # --- Positions ---
        positions = [
            Position(
                tenant_id=tid,
                title="Developpeur Full Stack Python/React",
                description="Backend Python/FastAPI + Frontend React/TypeScript. Equipe produit SaaS.",
                required_skills=["Python", "FastAPI", "React", "TypeScript", "PostgreSQL", "Docker"],
                seniority_level="senior", status="active", created_by=recruiter.id,
            ),
            Position(
                tenant_id=tid,
                title="Data Scientist NLP",
                description="Modeles NLP appliques au recrutement. RAG, fine-tuning, evaluation.",
                required_skills=["Python", "NLP", "Transformers", "PyTorch", "Scikit-learn"],
                seniority_level="mid", status="active", created_by=recruiter.id,
            ),
            Position(
                tenant_id=tid,
                title="Chef de projet IT",
                description="Coordination equipes dev, methodologie agile, livraisons sprint.",
                required_skills=["Gestion de projet", "Agile", "Scrum", "JIRA"],
                seniority_level="senior", status="active", created_by=admin.id,
            ),
            Position(
                tenant_id=tid,
                title="DevOps Engineer",
                description="CI/CD, Docker, Kubernetes, monitoring. Infrastructure cloud AWS/GCP.",
                required_skills=["Docker", "Kubernetes", "Terraform", "AWS", "CI/CD", "Linux"],
                seniority_level="mid", status="active", created_by=recruiter2.id,
            ),
            Position(
                tenant_id=tid,
                title="UX Designer",
                description="Design d'interfaces SaaS B2B. Recherche utilisateur, prototypage.",
                required_skills=["Figma", "UI/UX", "Design System", "Recherche utilisateur"],
                seniority_level="mid", status="draft", created_by=recruiter.id,
            ),
            Position(
                tenant_id=tid,
                title="Commercial B2B SaaS",
                description="Vente solution SaaS aupres d'entreprises. Demos, closing.",
                required_skills=["Vente B2B", "SaaS", "CRM", "Negociation"],
                seniority_level="mid", status="closed", created_by=admin.id,
            ),
        ]
        session.add_all(positions)
        session.flush()
        print(f"\n=== {len(positions)} Postes crees ===")

        # --- Candidates ---
        # (name, email, phone, position_index, pipeline_status, cv_score)
        candidates_data = [
            # Full Stack (7)
            ("Youssef El Amrani", "youssef.amrani@gmail.com", "+212661234567", 0, "evaluated", 85.5),
            ("Fatima Zahra Benali", "fatima.benali@outlook.com", "+212662345678", 0, "call_done", 72.0),
            ("Omar Kettani", "omar.kettani@yahoo.fr", "+212663456789", 0, "consent_given", 68.3),
            ("Salma Ouazzani", "salma.ouazzani@gmail.com", "+212664567890", 0, "cv_analyzed", 91.2),
            ("Mehdi Alaoui", "mehdi.alaoui@hotmail.com", "+212665678901", 0, "invited", 55.0),
            ("Nadia Chraibi", "nadia.chraibi@gmail.com", "+212666789012", 0, "new", None),
            ("Amine Berrada", "amine.berrada@outlook.com", "+212667890123", 0, "cv_uploaded", None),
            # Data Science (5)
            ("Imane Hajji", "imane.hajji@gmail.com", "+212668901234", 1, "evaluated", 88.7),
            ("Reda Bouazza", "reda.bouazza@yahoo.fr", "+212669012345", 1, "call_done", 76.4),
            ("Kenza Lamrani", "kenza.lamrani@gmail.com", "+212670123456", 1, "consent_given", 62.1),
            ("Hamza Filali", "hamza.filali@outlook.com", "+212671234567", 1, "cv_analyzed", 45.0),
            ("Zineb Idrissi", "zineb.idrissi@gmail.com", "+212672345678", 1, "invited", 79.9),
            # Chef de projet (4)
            ("Rachid Tazi", "rachid.tazi@gmail.com", "+212673456789", 2, "evaluated", 82.0),
            ("Layla Moussaoui", "layla.moussaoui@outlook.com", "+212674567890", 2, "call_done", 71.5),
            ("Khalid Bennani", "khalid.bennani@yahoo.fr", "+212675678901", 2, "cv_analyzed", 58.0),
            ("Houda Fassi", "houda.fassi@gmail.com", "+212676789012", 2, "new", None),
            # DevOps (4)
            ("Ayoub Cherkaoui", "ayoub.cherkaoui@gmail.com", "+212677890123", 3, "evaluated", 90.3),
            ("Saad Jabri", "saad.jabri@outlook.com", "+212678901234", 3, "consent_given", 67.8),
            ("Meryem Benhima", "meryem.benhima@gmail.com", "+212679012345", 3, "cv_analyzed", 73.5),
            ("Ilyas Doukkali", "ilyas.doukkali@yahoo.fr", "+212680123456", 3, "new", None),
            # Commercial (2)
            ("Soukaina Rami", "soukaina.rami@gmail.com", "+212681234567", 5, "evaluated", 77.0),
            ("Badr Sqalli", "badr.sqalli@outlook.com", "+212682345678", 5, "cv_analyzed", 60.5),
        ]

        candidates = []
        for name, email, phone, pos_idx, status, score in candidates_data:
            c = Candidate(
                tenant_id=tid,
                position_id=positions[pos_idx].id,
                name=name, email=email, phone=phone,
                pipeline_status=status,
                cv_score=score,
                cv_score_explanation={
                    "competences": random.randint(40, 95),
                    "experience": random.randint(40, 95),
                    "formation": random.randint(40, 95),
                } if score else None,
                created_at=rand_date(5, 45),
            )
            session.add(c)
            candidates.append(c)
        session.flush()
        print(f"=== {len(candidates)} Candidats crees ===")

        # --- Consents ---
        consent_stages = {"consent_given", "call_scheduled", "call_in_progress", "call_done", "evaluated"}
        consents_count = 0
        for c in candidates:
            if c.pipeline_status in consent_stages:
                session.add(Consent(
                    candidate_id=c.id,
                    token=f"consent-{c.id.hex[:12]}",
                    type="interview",
                    granted=True,
                    granted_at=rand_date(1, 30),
                    channel="email",
                ))
                consents_count += 1
        session.flush()
        print(f"=== {consents_count} Consentements ===")

        # --- Interviews ---
        interview_stages = {"call_done", "evaluated"}
        interviews = []
        for c in candidates:
            if c.pipeline_status in interview_stages:
                duration = random.randint(180, 480)
                started = rand_date(1, 20)
                iv = Interview(
                    candidate_id=c.id, position_id=c.position_id, tenant_id=tid,
                    status="completed",
                    scheduled_at=started - timedelta(hours=1),
                    started_at=started,
                    ended_at=started + timedelta(seconds=duration),
                    duration_seconds=duration,
                    questions_asked=[
                        "Parlez-nous de votre experience professionnelle.",
                        "Quelles technologies maitrisez-vous le mieux ?",
                        "Comment gerez-vous les deadlines serrees ?",
                        "Avez-vous des questions sur le poste ?",
                    ],
                    attempt_number=1,
                )
                session.add(iv)
                interviews.append((iv, c))
        session.flush()
        print(f"=== {len(interviews)} Interviews ===")

        # --- Analyses + Reports (evaluated only) ---
        reports_count = 0
        for iv, c in interviews:
            if c.pipeline_status == "evaluated":
                score_global = random.randint(55, 95)
                scores = {
                    "competences_techniques": random.randint(50, 95),
                    "communication": random.randint(50, 95),
                    "motivation": random.randint(60, 95),
                    "adequation_poste": random.randint(50, 95),
                    "score_global": score_global,
                }
                session.add(Analysis(
                    interview_id=iv.id,
                    scores=scores,
                    skills_extracted={
                        "techniques": ["Python", "FastAPI", "React"],
                        "soft": ["Communication", "Travail d'equipe"],
                    },
                    experience_examples=[
                        "5 ans d'experience en developpement web",
                        "Projet SaaS multi-tenant",
                    ],
                    communication_indicators={
                        "clarte": "bonne",
                        "structure": "bien organisee",
                        "ecoute": "attentive",
                    },
                    score_explanations={
                        "competences_techniques": "Bonne maitrise des technologies demandees",
                        "communication": "Reponses claires et structurees",
                        "motivation": "Enthousiaste et motive par le poste",
                        "adequation_poste": "Profil en adequation avec les besoins",
                    },
                ))
                session.add(Report(
                    candidate_id=c.id, interview_id=iv.id,
                    content={
                        "candidate_name": c.name,
                        "position_title": "N/A",
                        "score_global": score_global,
                        "cv_score": c.cv_score,
                        "scores": scores,
                        "summary": f"{c.name} presente un profil {'solide' if score_global >= 70 else 'a approfondir'}.",
                        "strengths": ["Competences techniques solides", "Bonne communication"],
                        "areas_to_explore": ["Leadership", "Travail en equipe internationale"],
                        "verbatims": [
                            "J'ai travaille 5 ans dans un environnement similaire.",
                            "Je suis passionne par les nouvelles technologies.",
                        ],
                        "recommendation": "retenu" if score_global >= 70 else "reserve",
                    },
                ))
                reports_count += 1
        session.flush()
        print(f"=== {reports_count} Rapports d'evaluation ===")

        # --- Audit logs ---
        audit_entries = [
            ("register", "user", str(admin.id), {"email": "admin@aihm.ai"}),
            ("login", "user", str(admin.id), {"email": "admin@aihm.ai"}),
            ("login", "user", str(recruiter.id), {"email": "recruteur@aihm.ai"}),
            ("invite_user", "user", str(recruiter2.id), {"email": "karim@aihm.ai", "role": "recruiter"}),
            ("invite_user", "user", str(viewer.id), {"email": "viewer@aihm.ai", "role": "viewer"}),
            ("login", "user", str(admin.id), {"email": "admin@aihm.ai"}),
            ("change_password", "user", str(recruiter.id), None),
            ("login", "user", str(recruiter2.id), {"email": "karim@aihm.ai"}),
        ]
        for action, entity_type, entity_id, details in audit_entries:
            session.add(AuditLog(
                tenant_id=tid, user_id=admin.id,
                action=action, entity_type=entity_type,
                entity_id=entity_id, details=details,
                created_at=rand_date(1, 30),
            ))

        session.commit()
        print(f"=== {len(audit_entries)} Audit logs ===")

        print(f"\n{'=' * 50}")
        print("Seed termine!")
        print(f"  Tenant: {tenant.name}")
        print(f"  {len(positions)} postes, {len(candidates)} candidats")
        print(f"  {len(interviews)} interviews, {reports_count} rapports")
        print(f"\nConnectez-vous avec: admin@aihm.ai / Admin123!")
        print(f"{'=' * 50}")


if __name__ == "__main__":
    seed()
