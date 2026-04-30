"""
Seed demo data for early adopter presentation.
Inserts realistic candidates at every pipeline stage with full interview data.

Usage: cd back && source venv/Scripts/activate && python scripts/seed_demo.py
"""

import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.analysis import Analysis
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.interview import Interview
from app.models.position import Position
from app.models.report import Report
from app.models.tenant import Tenant
from app.models.transcription import Transcription
from app.models.user import User

settings = get_settings()
sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(sync_url)

NOW = datetime.now(timezone.utc)


def r_date(days_back=1, days_max=30):
    return NOW - timedelta(days=random.randint(days_back, days_max), hours=random.randint(0, 12))


def seed():
    with Session(engine) as s:
        # Check existing tenant
        existing = s.execute(select(Tenant).where(Tenant.name == "TechRecruit Maroc")).scalar_one_or_none()
        if existing:
            print("Demo tenant 'TechRecruit Maroc' existe deja. Suppression...")
            from sqlalchemy import text
            tid_str = str(existing.id)
            # Delete all tenant data in correct FK order
            s.execute(text(f"""
                DELETE FROM reports WHERE candidate_id IN (SELECT id FROM candidates WHERE tenant_id = '{tid_str}');
                DELETE FROM analyses WHERE interview_id IN (SELECT id FROM interviews WHERE tenant_id = '{tid_str}');
                DELETE FROM transcriptions WHERE interview_id IN (SELECT id FROM interviews WHERE tenant_id = '{tid_str}');
                DELETE FROM interviews WHERE tenant_id = '{tid_str}';
                DELETE FROM consents WHERE candidate_id IN (SELECT id FROM candidates WHERE tenant_id = '{tid_str}');
                DELETE FROM match_scores WHERE tenant_id = '{tid_str}';
                DELETE FROM match_sessions WHERE tenant_id = '{tid_str}';
                DELETE FROM applications WHERE tenant_id = '{tid_str}';
                DELETE FROM candidates WHERE tenant_id = '{tid_str}';
                DELETE FROM webhook_subscriptions WHERE tenant_id = '{tid_str}';
                DELETE FROM audit_logs WHERE tenant_id = '{tid_str}';
                DELETE FROM positions WHERE tenant_id = '{tid_str}';
                DELETE FROM users WHERE tenant_id = '{tid_str}';
                DELETE FROM tenants WHERE id = '{tid_str}';
            """))
            s.commit()

        # ── Tenant ──
        tenant = Tenant(name="TechRecruit Maroc", plan="pro", timezone="Africa/Casablanca")
        s.add(tenant)
        s.flush()
        tid = tenant.id

        # ── Users ──
        admin = User(tenant_id=tid, email="demo@techrecruit.ma", password_hash=hash_password("Demo2026!"), full_name="Yasmine El Idrissi", role="admin")
        recruiter = User(tenant_id=tid, email="sara@techrecruit.ma", password_hash=hash_password("Demo2026!"), full_name="Sara Bennani", role="recruiter")
        s.add_all([admin, recruiter])
        s.flush()

        # ── Positions ──
        pos_backend = Position(
            tenant_id=tid, title="Developpeur Backend Python Senior",
            description="Nous recherchons un developpeur backend Python senior pour renforcer notre equipe technique. Vous concevrez et developperez des APIs RESTful performantes avec FastAPI, gererez des bases de donnees PostgreSQL, et mettrez en place des architectures microservices. Environnement agile, CI/CD, Docker/Kubernetes.",
            required_skills=[
                {"name": "Python", "level_required": 4, "weight": 3, "category": "technique"},
                {"name": "FastAPI", "level_required": 3, "weight": 3, "category": "technique"},
                {"name": "PostgreSQL", "level_required": 3, "weight": 2, "category": "technique"},
                {"name": "Docker", "level_required": 3, "weight": 2, "category": "technique"},
                {"name": "Redis", "level_required": 2, "weight": 1, "category": "technique"},
                {"name": "CI/CD", "level_required": 2, "weight": 1, "category": "technique"},
                {"name": "Communication", "level_required": 3, "weight": 2, "category": "soft_skills"},
            ],
            custom_questions=[
                "Decrivez un projet complexe ou vous avez utilise Python en production.",
                "Comment gerez-vous la scalabilite d'une API REST ?",
                "Quelle est votre experience avec les bases de donnees relationnelles ?",
                "Comment abordez-vous le travail en equipe dans un contexte agile ?",
            ],
            seniority_level="senior", status="active", created_by=recruiter.id,
            auto_advance_threshold=70, auto_reject_threshold=30,
        )
        pos_fullstack = Position(
            tenant_id=tid, title="Developpeur Full Stack React/Node",
            description="Poste de developpeur full stack pour notre produit SaaS B2B. Stack : React 19, TypeScript, Node.js, PostgreSQL. Vous travaillerez sur de nouvelles fonctionnalites, l'amelioration de l'UX et l'optimisation des performances.",
            required_skills=[
                {"name": "React", "level_required": 4, "weight": 3, "category": "technique"},
                {"name": "TypeScript", "level_required": 3, "weight": 3, "category": "technique"},
                {"name": "Node.js", "level_required": 3, "weight": 2, "category": "technique"},
                {"name": "PostgreSQL", "level_required": 2, "weight": 2, "category": "technique"},
                {"name": "Git", "level_required": 3, "weight": 1, "category": "technique"},
                {"name": "Anglais", "level_required": 3, "weight": 2, "category": "langue"},
            ],
            custom_questions=[
                "Quel est le projet React dont vous etes le plus fier ?",
                "Comment optimisez-vous les performances d'une application React ?",
                "Decrivez votre workflow Git ideal.",
            ],
            seniority_level="mid", status="active", created_by=admin.id,
        )
        pos_devops = Position(
            tenant_id=tid, title="Ingenieur DevOps / SRE",
            description="Rejoignez notre equipe infrastructure pour gerer nos environnements cloud AWS, automatiser les deployments et garantir la haute disponibilite de nos services.",
            required_skills=[
                {"name": "AWS", "level_required": 4, "weight": 3, "category": "technique"},
                {"name": "Kubernetes", "level_required": 3, "weight": 3, "category": "technique"},
                {"name": "Terraform", "level_required": 3, "weight": 2, "category": "technique"},
                {"name": "Linux", "level_required": 4, "weight": 2, "category": "technique"},
                {"name": "CI/CD", "level_required": 3, "weight": 2, "category": "technique"},
                {"name": "Monitoring", "level_required": 3, "weight": 1, "category": "technique"},
            ],
            custom_questions=[
                "Decrivez votre experience avec Kubernetes en production.",
                "Comment gerez-vous un incident en production ?",
            ],
            seniority_level="senior", status="active", created_by=recruiter.id,
        )
        s.add_all([pos_backend, pos_fullstack, pos_devops])
        s.flush()

        print(f"  3 postes crees")

        # ── Candidates data ──
        # Format: (name, email, phone, position, pipeline_status, cv_score, cv_data)
        CANDIDATES = [
            # ── Backend Python ── pipeline complet
            {
                "name": "Karim Benassou", "email": "karim.benassou@gmail.com", "phone": "+212661234567",
                "position": pos_backend, "status": "evaluated", "cv_score": 88,
                "cv_parsed": {
                    "skills": ["Python", "FastAPI", "Django", "PostgreSQL", "Redis", "Docker", "Kubernetes", "CI/CD", "Git", "Celery", "SQLAlchemy"],
                    "experience_years": 7,
                    "summary": "Ingenieur backend senior avec 7 ans d'experience en Python. Expert FastAPI/Django, architectures microservices, DevOps. Ancien lead tech chez une fintech casablancaise.",
                    "experiences": [
                        {"title": "Lead Backend Engineer", "company": "PayTech Maroc", "duration": "3 ans (2023-present)", "description": "Architecture microservices, migration monolithe vers FastAPI, gestion equipe de 5 devs."},
                        {"title": "Backend Developer Senior", "company": "DataFlow Solutions", "duration": "2.5 ans (2020-2023)", "description": "Developpement APIs REST, integration systemes bancaires, optimisation requetes SQL."},
                        {"title": "Developpeur Python", "company": "StartupLab", "duration": "1.5 ans (2019-2020)", "description": "MVP d'une plateforme e-commerce, stack Django/PostgreSQL/Redis."},
                    ],
                    "education": [{"degree": "Master Genie Logiciel", "school": "ENSIAS Rabat", "year": "2018"}],
                    "languages": [{"name": "Francais", "level": "natif"}, {"name": "Anglais", "level": "courant (C1)"}, {"name": "Arabe", "level": "natif"}],
                },
                "cv_explanation": {
                    "skills_match": {"score": 92, "matched": ["Python", "FastAPI", "PostgreSQL", "Docker", "Redis", "CI/CD"], "missing": [], "transferable": ["Django", "Kubernetes"], "justification": "Toutes les competences requises sont maitrisees. Python et FastAPI sont ses technologies principales avec 7 ans d'experience. PostgreSQL et Docker utilises quotidiennement."},
                    "experience_match": {"score": 88, "justification": "7 ans d'experience dont 3 en tant que Lead Backend. Experience directement pertinente en architecture microservices et APIs REST. Parcours progressif et coherent."},
                    "education_match": {"score": 85, "justification": "Master en Genie Logiciel de l'ENSIAS, ecole d'ingenieurs reconnue au Maroc. Formation solide et pertinente."},
                },
                "interview": {
                    "duration": 487,
                    "questions": [
                        "Bonjour Karim, pouvez-vous vous presenter et nous parler de votre parcours ?",
                        "Decrivez un projet complexe ou vous avez utilise Python en production.",
                        "Comment gerez-vous la scalabilite d'une API REST ?",
                        "Quelle est votre experience avec les bases de donnees relationnelles ?",
                        "Comment abordez-vous le travail en equipe dans un contexte agile ?",
                        "Avez-vous des questions sur le poste ou l'entreprise ?",
                    ],
                    "transcription_segments": {
                        "segment_1": {"question": "Bonjour Karim, pouvez-vous vous presenter ?", "answer": "Bonjour, merci pour cette opportunite. Je suis Karim Benassou, ingenieur backend senior avec 7 ans d'experience principalement en Python. Actuellement Lead Backend chez PayTech Maroc ou je dirige une equipe de 5 developpeurs. Nous avons migre l'ensemble de notre architecture monolithique Django vers des microservices FastAPI, ce qui a permis de diviser par 3 nos temps de reponse et de supporter 10 fois plus de transactions simultanées."},
                        "segment_2": {"question": "Decrivez un projet complexe ou vous avez utilise Python en production.", "answer": "Le projet le plus marquant est la refonte complete du systeme de paiement chez PayTech. Nous traitions environ 50 000 transactions par jour avec un monolithe Django qui montrait ses limites. J'ai concu et implemente une architecture event-driven avec FastAPI, Celery et Redis pour le messaging. Chaque microservice gere un domaine metier : authentification, transactions, notifications, reporting. Le resultat : temps de reponse moyen passe de 800ms a 120ms, zero downtime pendant la migration grace a un pattern strangler fig."},
                        "segment_3": {"question": "Comment gerez-vous la scalabilite d'une API REST ?", "answer": "Ma strategie repose sur plusieurs niveaux. D'abord le caching intelligent avec Redis, pas juste du cache brut mais des strategies adaptees : cache-aside pour les donnees chaudes, write-through pour la coherence. Ensuite, le connection pooling PostgreSQL avec PgBouncer. J'utilise aussi l'async massivement avec FastAPI et SQLAlchemy async. Pour la scalabilite horizontale, on utilise Kubernetes avec auto-scaling base sur les metriques custom, pas juste le CPU. Et evidemment, les index PostgreSQL bien penses, j'ai l'habitude d'analyser les plans d'execution avec EXPLAIN ANALYZE."},
                        "segment_4": {"question": "Quelle est votre experience avec les bases de donnees relationnelles ?", "answer": "PostgreSQL est ma base de donnees principale depuis 5 ans. J'ai gere des bases avec des tables de plus de 100 millions de lignes. Je maitrise le partitioning, les index GIN et GiST pour la recherche full-text, les CTE recursives, et les fonctions window. Chez PayTech, j'ai mis en place une strategie de read replicas avec streaming replication pour separer les lectures analytiques des ecritures transactionnelles. J'ai aussi de l'experience avec les migrations zero-downtime grace a des outils comme Alembic."},
                        "segment_5": {"question": "Comment abordez-vous le travail en equipe dans un contexte agile ?", "answer": "Chez PayTech, nous fonctionnons en sprints de 2 semaines. En tant que lead, j'anime les daily standups et les sprint reviews. Je crois beaucoup au pair programming pour les sujets complexes et au code review systematique. J'ai mis en place une culture de documentation technique avec des ADR, des Architecture Decision Records, pour tracer nos choix techniques. Ce qui est important pour moi c'est la transparence : si un sujet est bloque, on en parle immediatement, on ne cache pas les problemes."},
                        "segment_6": {"question": "Avez-vous des questions sur le poste ?", "answer": "Oui, j'aimerais comprendre votre stack technique actuelle et les principaux defis que vous rencontrez. Aussi, quelle est la taille de l'equipe backend et comment est organisee la collaboration avec le front ? Et enfin, quelle est votre strategie de deploiement, est-ce que vous utilisez Kubernetes ?"},
                    },
                    "scores": {"technical": 90, "experience": 88, "communication": 85, "global": 88},
                    "score_explanations": {
                        "technical": "Expertise technique exceptionnelle en Python/FastAPI. Maitrise avancee de PostgreSQL, Redis, Docker et Kubernetes. Architecture microservices demonstree avec des resultats concrets (3x performance).",
                        "experience": "7 ans d'experience progressive et coherente. Role de Lead confirmant la seniorite. Projets a fort impact (migration, scalabilite) directement pertinents.",
                        "communication": "Reponses structurees et detaillees. Vocabulaire technique precis. Capacite a vulgariser (pattern strangler fig bien explique). Pose des questions pertinentes en retour.",
                        "global": "Profil senior solide avec expertise technique prouvee, experience de leadership et excellente communication. Forte adequation avec le poste.",
                    },
                    "skill_scores": [
                        {"skill": "Python", "category": "technique", "level_required": 4, "demonstrated": 5, "motivation": 5, "evidence": "Expert Python confirme avec 7 ans de pratique. Migration FastAPI reussie, Celery/async maitrise.", "gap_analysis": "Depasse le niveau requis."},
                        {"skill": "FastAPI", "category": "technique", "level_required": 3, "demonstrated": 5, "motivation": 5, "evidence": "Migration complete d'un monolithe vers FastAPI. Async, dependency injection, performance 120ms.", "gap_analysis": "Depasse largement."},
                        {"skill": "PostgreSQL", "category": "technique", "level_required": 3, "demonstrated": 4, "motivation": 4, "evidence": "100M+ lignes, partitioning, GIN/GiST, CTE recursives, read replicas.", "gap_analysis": "Solide."},
                        {"skill": "Docker", "category": "technique", "level_required": 3, "demonstrated": 4, "motivation": 3, "evidence": "Utilisation quotidienne, orchestration Kubernetes.", "gap_analysis": "OK."},
                        {"skill": "Redis", "category": "technique", "level_required": 2, "demonstrated": 4, "motivation": 4, "evidence": "Cache-aside, write-through, messaging avec Celery.", "gap_analysis": "Depasse."},
                        {"skill": "CI/CD", "category": "technique", "level_required": 2, "demonstrated": 3, "motivation": 3, "evidence": "Mentionne dans le contexte DevOps mais pas detaille.", "gap_analysis": "OK."},
                        {"skill": "Communication", "category": "soft_skills", "level_required": 3, "demonstrated": 4, "motivation": 4, "evidence": "Lead tech, anime standups/reviews, ADR, transparence.", "gap_analysis": "Solide."},
                    ],
                    "experience_examples": [
                        {"situation": "Monolithe Django atteignant ses limites avec 50k transactions/jour", "task": "Concevoir et executer la migration vers microservices", "action": "Architecture event-driven FastAPI/Celery/Redis, pattern strangler fig pour migration sans downtime", "result": "Temps de reponse 800ms→120ms, capacite 10x, zero downtime"},
                        {"situation": "Base PostgreSQL de 100M+ lignes avec des requetes lentes", "task": "Optimiser les performances de lecture", "action": "Mise en place de read replicas, partitioning, index GIN/GiST, analyse EXPLAIN ANALYZE", "result": "Requetes analytiques separees des transactions, performances ameliorees significativement"},
                    ],
                    "communication_indicators": {
                        "clarity": {"score": 88, "evidence": "Reponses structurees avec contexte-action-resultat. Chiffres precis (50k transactions, 800ms→120ms)."},
                        "structure": {"score": 85, "evidence": "Organisation logique des reponses, progression naturelle des idees."},
                        "fluency": {"score": 82, "evidence": "Expression fluide et naturelle. Vocabulaire technique precis sans jargon inutile."},
                    },
                    "report": {
                        "summary": "Karim Benassou presente un profil senior exceptionnel pour ce poste. Avec 7 ans d'experience en Python dont 3 en tant que Lead Backend, il demontre une expertise technique approfondie (FastAPI, PostgreSQL, microservices) validee par des resultats concrets. Sa capacite a communiquer clairement et a diriger une equipe en fait un candidat ideal.",
                        "matching_score": 88,
                        "strengths": [
                            "Expertise Python/FastAPI exceptionnelle avec 7 ans de pratique intensive",
                            "Experience concrete de migration monolithe vers microservices avec resultats mesurables (3x performance)",
                            "Leadership confirme : gestion d'equipe de 5 devs, mise en place de bonnes pratiques (ADR, code review)",
                            "Maitrise avancee de PostgreSQL (100M+ lignes, partitioning, replicas)",
                        ],
                        "areas_to_explore": [
                            "Quelle est son experience specifique avec les tests automatises et le TDD ?",
                            "Comment gere-t-il la dette technique dans un contexte de forte croissance ?",
                            "Son experience en management est-elle un atout ou un risque de retour a un role purement technique ?",
                        ],
                        "key_quotes": [
                            "Nous avons migre l'ensemble de notre architecture monolithique Django vers des microservices FastAPI, ce qui a permis de diviser par 3 nos temps de reponse.",
                            "Ce qui est important pour moi c'est la transparence : si un sujet est bloque, on en parle immediatement.",
                            "J'ai l'habitude d'analyser les plans d'execution avec EXPLAIN ANALYZE.",
                        ],
                        "recommendation": "retenu",
                    },
                },
            },
            {
                "name": "Sophie El Amrani", "email": "sophie.elamrani@outlook.com", "phone": "+212662345678",
                "position": pos_backend, "status": "evaluated", "cv_score": 72,
                "cv_parsed": {
                    "skills": ["Python", "Django", "PostgreSQL", "Docker", "Git", "Celery", "REST API"],
                    "experience_years": 4,
                    "summary": "Developpeuse backend Python avec 4 ans d'experience. Specialisee Django/DRF, bonne connaissance de PostgreSQL et Docker.",
                    "experiences": [
                        {"title": "Backend Developer", "company": "E-Commerce Plus", "duration": "2 ans (2024-present)", "description": "APIs Django REST Framework, integration paiement, gestion catalogue produits."},
                        {"title": "Developpeur Junior", "company": "WebAgency Casa", "duration": "2 ans (2022-2024)", "description": "Developpement web Django, sites clients, bases de donnees."},
                    ],
                    "education": [{"degree": "Licence Informatique", "school": "Universite Hassan II Casablanca", "year": "2021"}],
                    "languages": [{"name": "Francais", "level": "natif"}, {"name": "Anglais", "level": "intermediaire (B1)"}],
                },
                "cv_explanation": {
                    "skills_match": {"score": 70, "matched": ["Python", "PostgreSQL", "Docker"], "missing": ["FastAPI", "Redis"], "transferable": ["Django"], "justification": "Python et PostgreSQL maitrises mais pas FastAPI (utilise Django). Redis absent. Docker mentionne."},
                    "experience_match": {"score": 68, "justification": "4 ans d'experience, niveau mid plutot que senior. Pas de leadership ni d'architecture microservices."},
                    "education_match": {"score": 65, "justification": "Licence en informatique, formation correcte mais pas ecole d'ingenieurs."},
                },
                "interview": {
                    "duration": 342,
                    "questions": [
                        "Presentez-vous et votre parcours.",
                        "Decrivez un projet complexe en Python.",
                        "Comment gerez-vous la scalabilite ?",
                        "Votre experience avec les BDD relationnelles ?",
                    ],
                    "transcription_segments": {
                        "segment_1": {"question": "Presentez-vous.", "answer": "Bonjour, je suis Sophie El Amrani, 4 ans d'experience en Python principalement avec Django. Je travaille actuellement chez E-Commerce Plus ou je developpe des APIs pour une plateforme e-commerce. Avant ca j'etais dans une agence web."},
                        "segment_2": {"question": "Decrivez un projet complexe en Python.", "answer": "Le plus gros projet c'est la refonte de l'API catalogue chez E-Commerce Plus. On avait 20 000 produits avec des variantes, des prix dynamiques, et des promotions. J'ai restructure le modele de donnees avec Django REST Framework et optimise les requetes pour reduire le temps de chargement de la page catalogue de 3 secondes a 800ms. J'ai utilise du caching avec Django cache framework."},
                        "segment_3": {"question": "Comment gerez-vous la scalabilite ?", "answer": "Honnêtement c'est un domaine ou j'ai moins d'experience. Chez nous on utilise un serveur dédié avec Gunicorn. J'ai mis en place du caching et j'optimise les requetes SQL. Je n'ai pas encore travaille avec des architectures distribuees mais c'est quelque chose que j'aimerais apprendre, notamment FastAPI et les microservices."},
                        "segment_4": {"question": "Votre experience avec les BDD relationnelles ?", "answer": "PostgreSQL depuis 3 ans. Je gere les migrations avec Django ORM, j'ecris des requetes raw quand l'ORM ne suffit pas. J'ai de l'experience avec les indexes, les joins complexes et les transactions. J'ai aussi utilise MySQL au debut de ma carriere."},
                    },
                    "scores": {"technical": 65, "experience": 62, "communication": 75, "global": 67},
                    "score_explanations": {
                        "technical": "Bonne maitrise de Django/Python mais manque FastAPI et Redis. Architecture limitee a du monolithe.",
                        "experience": "4 ans d'experience coherente mais niveau mid. Pas de leadership ni d'architecture distribuee.",
                        "communication": "Honnete et transparente sur ses limites. Reponses claires bien que moins detaillees.",
                        "global": "Profil mid solide avec potentiel de progression. Manque de seniorite pour le poste mais motivation visible.",
                    },
                    "skill_scores": [
                        {"skill": "Python", "category": "technique", "level_required": 4, "demonstrated": 3, "motivation": 4, "evidence": "4 ans Django, maitrise solide mais pas de FastAPI/async.", "gap_analysis": "Bon niveau mais en dessous du requis senior."},
                        {"skill": "FastAPI", "category": "technique", "level_required": 3, "demonstrated": 0, "motivation": 5, "evidence": "N'a pas utilise FastAPI mais exprime un fort interet.", "gap_analysis": "Competence manquante, necessiterait formation."},
                        {"skill": "PostgreSQL", "category": "technique", "level_required": 3, "demonstrated": 3, "motivation": 3, "evidence": "3 ans, migrations, requetes raw, indexes.", "gap_analysis": "Niveau adequat."},
                        {"skill": "Docker", "category": "technique", "level_required": 3, "demonstrated": 2, "motivation": 3, "evidence": "Usage basique mentionne.", "gap_analysis": "En dessous du requis."},
                        {"skill": "Redis", "category": "technique", "level_required": 2, "demonstrated": 0, "motivation": 3, "evidence": "Utilise Django cache framework, pas Redis directement.", "gap_analysis": "Absent."},
                        {"skill": "Communication", "category": "soft_skills", "level_required": 3, "demonstrated": 4, "motivation": 4, "evidence": "Honnete sur ses limites, reponses claires.", "gap_analysis": "Bon."},
                    ],
                    "experience_examples": [
                        {"situation": "Catalogue e-commerce de 20k produits avec temps de chargement de 3s", "task": "Optimiser les performances de l'API catalogue", "action": "Restructuration modele Django REST, caching, optimisation SQL", "result": "Temps de chargement reduit de 3s a 800ms"},
                    ],
                    "communication_indicators": {
                        "clarity": {"score": 78, "evidence": "Reponses directes et honnetes. Reconnnait ses limites."},
                        "structure": {"score": 72, "evidence": "Reponses plus courtes mais bien organisees."},
                        "fluency": {"score": 75, "evidence": "Expression naturelle, quelques hesitations sur les sujets techniques avances."},
                    },
                    "report": {
                        "summary": "Sophie El Amrani est une developpeuse Python mid-level avec un profil solide en Django. Ses competences correspondent partiellement au poste senior : elle maitrise Python et PostgreSQL mais manque d'experience avec FastAPI, Redis et les architectures distribuees. Sa transparence et sa motivation a progresser sont des points positifs. Profil a considerer pour un plan de montee en competences.",
                        "matching_score": 67,
                        "strengths": [
                            "Maitrise solide de Django et PostgreSQL",
                            "Transparente et honnete sur son niveau",
                            "Forte motivation pour monter en competences (FastAPI, microservices)",
                            "Resultats concrets en optimisation (3s→800ms)",
                        ],
                        "areas_to_explore": [
                            "Est-elle prete a investir dans l'apprentissage de FastAPI rapidement ?",
                            "Son niveau d'anglais B1 est-il suffisant pour la documentation technique ?",
                            "Comment reagit-elle a la pression et aux deadlines serrees ?",
                        ],
                        "key_quotes": [
                            "Honnetement c'est un domaine ou j'ai moins d'experience mais c'est quelque chose que j'aimerais apprendre.",
                            "J'ai restructure le modele de donnees et optimise les requetes pour reduire le temps de chargement de 3 secondes a 800ms.",
                        ],
                        "recommendation": "reserve",
                    },
                },
            },
            {
                "name": "Youssef Cherkaoui", "email": "youssef.cherkaoui@gmail.com", "phone": "+212663456789",
                "position": pos_backend, "status": "consent_given", "cv_score": 81,
                "cv_parsed": {
                    "skills": ["Python", "FastAPI", "Flask", "PostgreSQL", "MongoDB", "Docker", "AWS", "Git"],
                    "experience_years": 5,
                    "summary": "Backend developer 5 ans, Python/FastAPI, experience cloud AWS et bases NoSQL.",
                    "experiences": [
                        {"title": "Backend Engineer", "company": "CloudFirst", "duration": "2.5 ans", "description": "APIs FastAPI, deploiement AWS, Lambda, microservices."},
                        {"title": "Developer", "company": "DataViz", "duration": "2.5 ans", "description": "Backend Flask, dashboards, ETL pipelines."},
                    ],
                    "education": [{"degree": "Master Informatique", "school": "EMI Rabat", "year": "2020"}],
                    "languages": [{"name": "Francais", "level": "natif"}, {"name": "Anglais", "level": "courant"}],
                },
                "cv_explanation": {
                    "skills_match": {"score": 82, "matched": ["Python", "FastAPI", "PostgreSQL", "Docker"], "missing": ["Redis"], "transferable": ["AWS", "MongoDB"], "justification": "Competences techniques bien alignees. FastAPI maitrise, AWS en bonus."},
                    "experience_match": {"score": 78, "justification": "5 ans avec experience directe FastAPI et cloud. Profil senior-1."},
                    "education_match": {"score": 82, "justification": "Master EMI, excellente ecole d'ingenieurs marocaine."},
                },
            },
            {
                "name": "Marc Benjelloun", "email": "marc.benjelloun@hotmail.com", "phone": "+212664567890",
                "position": pos_backend, "status": "invited", "cv_score": 65,
                "cv_parsed": {
                    "skills": ["Python", "Django", "MySQL", "Git", "Linux"],
                    "experience_years": 3,
                    "summary": "Developpeur Python 3 ans, Django, bases SQL.",
                    "experiences": [{"title": "Developpeur", "company": "WebDev Maroc", "duration": "3 ans", "description": "Sites web Django, gestion clients."}],
                    "education": [{"degree": "Licence Informatique", "school": "FSTM", "year": "2022"}],
                    "languages": [{"name": "Francais", "level": "natif"}],
                },
                "cv_explanation": {
                    "skills_match": {"score": 55, "matched": ["Python"], "missing": ["FastAPI", "PostgreSQL", "Docker", "Redis", "CI/CD"], "transferable": ["Django", "MySQL"], "justification": "Seul Python correspond. Beaucoup de competences requises absentes."},
                    "experience_match": {"score": 60, "justification": "3 ans, profil junior. Pas d'architecture ni de scalabilite."},
                    "education_match": {"score": 60, "justification": "Licence basique."},
                },
            },
            {
                "name": "Fatima Zahra Idrissi", "email": "fz.idrissi@gmail.com", "phone": "+212665678901",
                "position": pos_backend, "status": "cv_analyzed", "cv_score": 76,
                "cv_parsed": {
                    "skills": ["Python", "FastAPI", "Django", "PostgreSQL", "Docker", "Celery", "RabbitMQ"],
                    "experience_years": 5,
                    "summary": "Backend Python 5 ans, FastAPI et Django, experience fintech.",
                    "experiences": [
                        {"title": "Senior Developer", "company": "FinServ", "duration": "2 ans", "description": "APIs FastAPI, integration bancaire."},
                        {"title": "Developer", "company": "TechCorp", "duration": "3 ans", "description": "Backend Django, APIs REST."},
                    ],
                    "education": [{"degree": "Ingenieur Informatique", "school": "INPT Rabat", "year": "2020"}],
                    "languages": [{"name": "Francais", "level": "natif"}, {"name": "Anglais", "level": "courant (B2)"}],
                },
                "cv_explanation": {
                    "skills_match": {"score": 78, "matched": ["Python", "FastAPI", "PostgreSQL", "Docker"], "missing": ["Redis"], "transferable": ["RabbitMQ", "Celery"], "justification": "Bon profil technique. FastAPI maitrise. RabbitMQ transferable vers Redis."},
                    "experience_match": {"score": 75, "justification": "5 ans pertinents en backend Python. Experience fintech interessante."},
                    "education_match": {"score": 78, "justification": "Ingenieur INPT, bonne ecole."},
                },
            },

            # ── Full Stack ──
            {
                "name": "Thomas Hassani", "email": "thomas.hassani@gmail.com", "phone": "+212666789012",
                "position": pos_fullstack, "status": "evaluated", "cv_score": 85,
                "cv_parsed": {
                    "skills": ["React", "TypeScript", "Node.js", "PostgreSQL", "Next.js", "TailwindCSS", "Git", "Docker"],
                    "experience_years": 5,
                    "summary": "Full stack React/Node.js avec 5 ans d'experience. Specialise SaaS B2B, TypeScript avance.",
                    "experiences": [
                        {"title": "Full Stack Developer", "company": "SaaSify", "duration": "3 ans", "description": "Plateforme SaaS B2B, React/Node, 50k users."},
                        {"title": "Frontend Developer", "company": "DigitalAgency", "duration": "2 ans", "description": "Sites clients React, Next.js."},
                    ],
                    "education": [{"degree": "Master Dev Web", "school": "Universite Al Akhawayn", "year": "2020"}],
                    "languages": [{"name": "Francais", "level": "natif"}, {"name": "Anglais", "level": "courant (C1)"}],
                },
                "cv_explanation": {
                    "skills_match": {"score": 90, "matched": ["React", "TypeScript", "Node.js", "PostgreSQL", "Git"], "missing": [], "transferable": ["Next.js", "TailwindCSS"], "justification": "Toutes les competences cles sont la. TypeScript et React avances."},
                    "experience_match": {"score": 82, "justification": "5 ans full stack, experience SaaS B2B directement pertinente."},
                    "education_match": {"score": 80, "justification": "Master Al Akhawayn, universite internationale reconnue."},
                },
                "interview": {
                    "duration": 410,
                    "questions": ["Presentez-vous.", "Projet React dont vous etes le plus fier ?", "Comment optimisez-vous React ?", "Votre workflow Git ?"],
                    "transcription_segments": {
                        "segment_1": {"question": "Presentez-vous.", "answer": "Je suis Thomas Hassani, 5 ans en full stack React/Node. Je travaille chez SaaSify ou on a construit une plateforme de gestion de projets B2B utilisee par 50 000 utilisateurs. TypeScript partout, cote client et serveur."},
                        "segment_2": {"question": "Projet React dont vous etes le plus fier ?", "answer": "La plateforme SaaSify sans hesiter. On a un dashboard temps reel avec des graphiques complexes, du drag and drop pour la gestion de taches, et un systeme de notifications push. Le defi c'etait la performance avec beaucoup de donnees affichees simultanement. J'ai implemente du virtual scrolling, React.memo strategique, et un state management avec Zustand plutot que Redux pour la simplicite."},
                        "segment_3": {"question": "Comment optimisez-vous React ?", "answer": "Trois axes principaux. Premier : le rendering, avec React.memo, useMemo et useCallback pour eviter les re-renders inutiles. Je mesure avec React DevTools Profiler. Deuxieme : le code splitting avec lazy() et Suspense pour charger les pages a la demande. Troisieme : les donnees avec React Query pour le caching et la deduplication des requetes API. On a reduit notre bundle de 2.5MB a 800KB avec ces techniques."},
                        "segment_4": {"question": "Votre workflow Git ?", "answer": "Trunk-based development avec des feature branches courtes, maximum 2-3 jours. Pull requests avec au moins un review obligatoire. CI/CD avec GitHub Actions : lint, tests, build, deploy automatique en staging. Conventional commits pour generer les changelogs automatiquement."},
                    },
                    "scores": {"technical": 87, "experience": 84, "communication": 88, "global": 86},
                    "score_explanations": {
                        "technical": "Excellente maitrise de React/TypeScript/Node. Optimisation performance avancee. Architecture solide.",
                        "experience": "5 ans pertinents en SaaS B2B. 50k users en production.",
                        "communication": "Reponses structurees, precises, avec des exemples concrets.",
                        "global": "Profil tres solide pour le poste full stack.",
                    },
                    "skill_scores": [
                        {"skill": "React", "category": "technique", "level_required": 4, "demonstrated": 5, "motivation": 5, "evidence": "Dashboard temps reel, virtual scrolling, optimisation avancee.", "gap_analysis": "Depasse."},
                        {"skill": "TypeScript", "category": "technique", "level_required": 3, "demonstrated": 4, "motivation": 5, "evidence": "TypeScript partout, client et serveur.", "gap_analysis": "Solide."},
                        {"skill": "Node.js", "category": "technique", "level_required": 3, "demonstrated": 4, "motivation": 4, "evidence": "Backend SaaS en production.", "gap_analysis": "OK."},
                        {"skill": "PostgreSQL", "category": "technique", "level_required": 2, "demonstrated": 3, "motivation": 3, "evidence": "Utilise en production.", "gap_analysis": "OK."},
                        {"skill": "Anglais", "category": "langue", "level_required": 3, "demonstrated": 4, "motivation": 4, "evidence": "C1, Al Akhawayn est anglophone.", "gap_analysis": "Solide."},
                    ],
                    "experience_examples": [
                        {"situation": "Dashboard SaaS affichant beaucoup de donnees avec des performances degradees", "task": "Optimiser le rendu React", "action": "Virtual scrolling, React.memo, code splitting, React Query", "result": "Bundle 2.5MB→800KB, interface fluide"},
                    ],
                    "communication_indicators": {
                        "clarity": {"score": 90, "evidence": "Reponses detaillees avec exemples chiffres (50k users, 2.5MB→800KB)."},
                        "structure": {"score": 88, "evidence": "Organisation en axes (3 axes d'optimisation), progression logique."},
                        "fluency": {"score": 86, "evidence": "Expression tres fluide et naturelle."},
                    },
                    "report": {
                        "summary": "Thomas Hassani est un excellent candidat full stack avec une expertise avancee en React/TypeScript et Node.js. Son experience SaaS B2B avec 50k utilisateurs est directement pertinente. Profil recommande sans reserve.",
                        "matching_score": 86,
                        "strengths": ["Expert React/TypeScript avec optimisation performance avancee", "Experience SaaS B2B a 50k users", "Workflow Git professionnel (trunk-based, CI/CD)", "Anglais courant (C1)"],
                        "areas_to_explore": ["Experience en management d'equipe ?", "Connaissance des tests E2E (Playwright, Cypress) ?"],
                        "key_quotes": ["On a reduit notre bundle de 2.5MB a 800KB avec ces techniques.", "TypeScript partout, cote client et serveur."],
                        "recommendation": "retenu",
                    },
                },
            },
            {
                "name": "Lea Bouazza", "email": "lea.bouazza@gmail.com", "phone": "+212667890123",
                "position": pos_fullstack, "status": "call_done", "cv_score": 70,
                "cv_parsed": {
                    "skills": ["React", "JavaScript", "Node.js", "MongoDB", "CSS", "Git"],
                    "experience_years": 3,
                    "summary": "Frontend React 3 ans, en transition vers full stack.",
                    "experiences": [{"title": "Frontend Developer", "company": "WebStudio", "duration": "3 ans", "description": "Sites React, integration APIs."}],
                    "education": [{"degree": "DUT Informatique", "school": "EST Casablanca", "year": "2022"}],
                    "languages": [{"name": "Francais", "level": "natif"}, {"name": "Anglais", "level": "intermediaire (B1)"}],
                },
                "cv_explanation": {
                    "skills_match": {"score": 65, "matched": ["React", "Node.js", "Git"], "missing": ["TypeScript", "PostgreSQL"], "transferable": ["JavaScript", "MongoDB"], "justification": "React et Node presents mais TypeScript absent. MongoDB au lieu de PostgreSQL."},
                    "experience_match": {"score": 62, "justification": "3 ans, principalement frontend. Transition vers full stack en cours."},
                    "education_match": {"score": 60, "justification": "DUT, formation courte."},
                },
                "interview": {
                    "duration": 295,
                    "questions": ["Presentez-vous.", "Projet React prefere ?", "Optimisation React ?"],
                    "transcription_segments": {
                        "segment_1": {"question": "Presentez-vous.", "answer": "Je suis Lea, 3 ans en frontend React. Je commence a toucher au backend avec Node.js et Express. J'aimerais devenir full stack."},
                        "segment_2": {"question": "Projet React prefere ?", "answer": "Un dashboard d'analytics pour un client e-commerce. Charts avec Recharts, filtres dynamiques, export PDF. Le plus dur c'etait de gerer les states complexes avec plusieurs filtres imbriques."},
                        "segment_3": {"question": "Optimisation React ?", "answer": "J'utilise React.memo et useMemo quand je vois des re-renders inutiles dans le DevTools. Aussi le lazy loading pour les routes. Je n'ai pas encore beaucoup d'experience avec le code splitting avance."},
                    },
                    "scores": {"technical": 58, "experience": 55, "communication": 70, "global": 60},
                    "score_explanations": {
                        "technical": "Bonne base React mais manque TypeScript et experience backend solide.",
                        "experience": "3 ans principalement frontend. Backend debutant.",
                        "communication": "Honnete et directe. Motivation claire.",
                        "global": "Profil junior/mid, en dessous du niveau requis mais potentiel.",
                    },
                    "skill_scores": [
                        {"skill": "React", "category": "technique", "level_required": 4, "demonstrated": 3, "motivation": 5, "evidence": "3 ans React, dashboards, bonne base.", "gap_analysis": "En dessous du senior requis."},
                        {"skill": "TypeScript", "category": "technique", "level_required": 3, "demonstrated": 0, "motivation": 4, "evidence": "Pas mentionne.", "gap_analysis": "Absent."},
                        {"skill": "Node.js", "category": "technique", "level_required": 3, "demonstrated": 1, "motivation": 4, "evidence": "Debutant, Express basique.", "gap_analysis": "Insuffisant."},
                    ],
                    "experience_examples": [],
                    "communication_indicators": {
                        "clarity": {"score": 72, "evidence": "Directe et concise."}, "structure": {"score": 68, "evidence": "Reponses courtes."}, "fluency": {"score": 70, "evidence": "Expression correcte."},
                    },
                    "report": {
                        "summary": "Salma est une developpeuse frontend junior/mid avec une bonne base React mais insuffisante pour un poste mid full stack. TypeScript et backend Node.js sont a developper.",
                        "matching_score": 60,
                        "strengths": ["Bonne base React", "Motivation forte pour devenir full stack"],
                        "areas_to_explore": ["Formation TypeScript necessaire", "Experience backend tres limitee"],
                        "key_quotes": ["J'aimerais devenir full stack."],
                        "recommendation": "reserve",
                    },
                },
            },
            {
                "name": "Omar Lefebvre", "email": "omar.lefebvre@gmail.com", "phone": "+212668901234",
                "position": pos_fullstack, "status": "cv_analyzed", "cv_score": 78,
                "cv_parsed": {
                    "skills": ["React", "TypeScript", "Vue.js", "Node.js", "PostgreSQL", "Docker", "Git"],
                    "experience_years": 4,
                    "summary": "Full stack 4 ans, React/Vue/Node, experience startup.",
                    "experiences": [{"title": "Full Stack Dev", "company": "StartupFlow", "duration": "4 ans", "description": "Developpement produit SaaS."}],
                    "education": [{"degree": "Ingenieur ENSA", "school": "ENSA Kenitra", "year": "2021"}],
                    "languages": [{"name": "Francais", "level": "natif"}, {"name": "Anglais", "level": "courant"}],
                },
                "cv_explanation": {
                    "skills_match": {"score": 80, "matched": ["React", "TypeScript", "Node.js", "PostgreSQL", "Git"], "missing": [], "transferable": ["Vue.js"], "justification": "Toutes les competences requises presentes."},
                    "experience_match": {"score": 75, "justification": "4 ans, experience startup pertinente pour un contexte SaaS."},
                    "education_match": {"score": 75, "justification": "Ingenieur ENSA, bonne ecole."},
                },
            },

            # ── DevOps ──
            {
                "name": "Mehdi Dupont", "email": "mehdi.dupont@gmail.com", "phone": "+212669012345",
                "position": pos_devops, "status": "evaluated", "cv_score": 90,
                "cv_parsed": {
                    "skills": ["AWS", "Kubernetes", "Terraform", "Docker", "Linux", "CI/CD", "Prometheus", "Grafana", "Python", "Ansible"],
                    "experience_years": 8,
                    "summary": "SRE/DevOps senior 8 ans, expert AWS/Kubernetes, infrastructure as code.",
                    "experiences": [
                        {"title": "SRE Lead", "company": "CloudScale", "duration": "3 ans", "description": "Gestion infrastructure AWS, 200+ microservices Kubernetes."},
                        {"title": "DevOps Engineer", "company": "TechBridge", "duration": "3 ans", "description": "Migration cloud, CI/CD pipelines."},
                        {"title": "Sysadmin", "company": "HostPro", "duration": "2 ans", "description": "Administration Linux, monitoring."},
                    ],
                    "education": [{"degree": "Ingenieur Reseaux", "school": "INPT Rabat", "year": "2017"}],
                    "languages": [{"name": "Francais", "level": "natif"}, {"name": "Anglais", "level": "courant (C1)"}],
                },
                "cv_explanation": {
                    "skills_match": {"score": 95, "matched": ["AWS", "Kubernetes", "Terraform", "Linux", "CI/CD", "Monitoring"], "missing": [], "transferable": ["Ansible", "Python"], "justification": "Profil parfaitement aligne. Toutes les competences requises maitrisees a un niveau avance."},
                    "experience_match": {"score": 90, "justification": "8 ans d'experience progressive. Lead SRE avec 200+ microservices. Parcours ideal."},
                    "education_match": {"score": 85, "justification": "Ingenieur INPT en reseaux, formation parfaitement adaptee."},
                },
                "interview": {
                    "duration": 520,
                    "questions": ["Presentez-vous.", "Experience Kubernetes en production ?", "Comment gerez-vous un incident ?"],
                    "transcription_segments": {
                        "segment_1": {"question": "Presentez-vous.", "answer": "Mehdi Dupont, 8 ans en infrastructure et SRE. Actuellement Lead SRE chez CloudScale ou je gere l'infrastructure AWS pour 200+ microservices Kubernetes. Mon equipe de 4 personnes assure le 99.99% d'uptime sur nos services critiques. Avant ca, j'ai fait la migration cloud chez TechBridge, on est passe de bare metal a AWS en 18 mois."},
                        "segment_2": {"question": "Experience Kubernetes en production ?", "answer": "Chez CloudScale, on gere 15 clusters EKS repartis sur 3 regions AWS. Plus de 200 microservices, environ 2000 pods en permanence. J'ai mis en place le GitOps avec ArgoCD, le service mesh Istio pour la communication inter-services, et un systeme de canary deployments avec Flagger. Pour le monitoring, stack complete : Prometheus, Grafana, alertes PagerDuty avec des runbooks automatises."},
                        "segment_3": {"question": "Comment gerez-vous un incident ?", "answer": "On a un processus structure. D'abord le triage : est-ce que ca impacte les utilisateurs ? Si oui, on declare un incident et on mobilise l'equipe via PagerDuty. Ensuite, mitigation rapide, souvent un rollback Kubernetes. Puis investigation root cause avec les metriques Prometheus et les logs centralises ELK. Et enfin, le plus important : le postmortem blameless dans les 48h avec des action items concrets. On a reduit nos MTTR de 45 minutes a 8 minutes en un an grace a l'automatisation."},
                    },
                    "scores": {"technical": 95, "experience": 92, "communication": 88, "global": 92},
                    "score_explanations": {
                        "technical": "Expert Kubernetes/AWS avec 200+ microservices en production. GitOps, service mesh, monitoring avance.",
                        "experience": "8 ans progressifs, Lead SRE, 99.99% uptime. Migration cloud complete.",
                        "communication": "Reponses extremement detaillees et structurees. Vocabulaire SRE precis.",
                        "global": "Candidat exceptionnel pour le poste DevOps/SRE.",
                    },
                    "skill_scores": [
                        {"skill": "AWS", "category": "technique", "level_required": 4, "demonstrated": 5, "motivation": 5, "evidence": "15 clusters EKS, 3 regions, migration complete.", "gap_analysis": "Expert."},
                        {"skill": "Kubernetes", "category": "technique", "level_required": 3, "demonstrated": 5, "motivation": 5, "evidence": "200+ microservices, 2000 pods, GitOps/ArgoCD, Istio, Flagger.", "gap_analysis": "Expert."},
                        {"skill": "Terraform", "category": "technique", "level_required": 3, "demonstrated": 4, "motivation": 4, "evidence": "Infrastructure as code mentionne.", "gap_analysis": "OK."},
                        {"skill": "Linux", "category": "technique", "level_required": 4, "demonstrated": 5, "motivation": 4, "evidence": "2 ans sysadmin + 6 ans en environnement Linux.", "gap_analysis": "Expert."},
                        {"skill": "Monitoring", "category": "technique", "level_required": 3, "demonstrated": 5, "motivation": 5, "evidence": "Prometheus, Grafana, PagerDuty, runbooks, ELK.", "gap_analysis": "Expert."},
                    ],
                    "experience_examples": [
                        {"situation": "MTTR de 45 minutes pour les incidents production", "task": "Reduire le temps de resolution", "action": "Automatisation runbooks, alerting intelligent PagerDuty, canary deployments Flagger", "result": "MTTR reduit de 45min a 8min en un an"},
                        {"situation": "Infrastructure bare metal vieillissante chez TechBridge", "task": "Migration complete vers le cloud", "action": "Migration AWS en 18 mois, Terraform IaC, Kubernetes", "result": "Infrastructure cloud scalable, couts reduits de 30%"},
                    ],
                    "communication_indicators": {
                        "clarity": {"score": 92, "evidence": "Chiffres precis : 200+ microservices, 2000 pods, 99.99%, MTTR 45→8min."},
                        "structure": {"score": 88, "evidence": "Processus incident en 4 etapes claires. Progression logique."},
                        "fluency": {"score": 85, "evidence": "Expression technique fluide et precise."},
                    },
                    "report": {
                        "summary": "Mehdi Dupont est un candidat exceptionnel pour le poste DevOps/SRE. Avec 8 ans d'experience et un role de Lead SRE gerant 200+ microservices sur AWS/Kubernetes, son profil depasse les exigences du poste. Recommandation forte.",
                        "matching_score": 92,
                        "strengths": ["Expert AWS/Kubernetes avec experience massive (200+ microservices, 15 clusters)", "MTTR 45→8min grace a l'automatisation", "Migration cloud complete en 18 mois", "99.99% uptime sur services critiques"],
                        "areas_to_explore": ["Attentes salariales pour ce niveau d'expertise ?", "Risque de surqualification ?"],
                        "key_quotes": ["On a reduit nos MTTR de 45 minutes a 8 minutes en un an grace a l'automatisation.", "Mon equipe assure le 99.99% d'uptime sur nos services critiques."],
                        "recommendation": "retenu",
                    },
                },
            },
        ]

        # ── Insert candidates ──
        print(f"\n=== Insertion des candidats ===")
        for cd in CANDIDATES:
            cand = Candidate(
                tenant_id=tid, position_id=cd["position"].id,
                name=cd["name"], email=cd["email"], phone=cd["phone"],
                pipeline_status=cd["status"], cv_score=cd["cv_score"],
                cv_parsed_data=cd["cv_parsed"],
                cv_score_explanation=cd.get("cv_explanation"),
                created_at=r_date(2, 20),
            )
            s.add(cand)
            s.flush()

            # Consent for invited+
            if cd["status"] in ("invited", "consent_given", "call_scheduled", "call_done", "evaluated"):
                consent = Consent(
                    candidate_id=cand.id, token=str(uuid.uuid4()),
                    type="data_processing", granted=cd["status"] != "invited",
                    granted_at=r_date(1, 10) if cd["status"] != "invited" else None,
                    channel="email",
                )
                s.add(consent)

            # Interview data
            iv_data = cd.get("interview")
            if iv_data and cd["status"] in ("call_done", "evaluated"):
                started = r_date(1, 10)
                iv = Interview(
                    candidate_id=cand.id, position_id=cd["position"].id, tenant_id=tid,
                    status="completed",
                    scheduled_at=started - timedelta(hours=1),
                    started_at=started,
                    ended_at=started + timedelta(seconds=iv_data["duration"]),
                    duration_seconds=iv_data["duration"],
                    questions_asked=iv_data["questions"],
                    attempt_number=1,
                )
                s.add(iv)
                s.flush()

                # Transcription
                segments = iv_data.get("transcription_segments", {})
                full_text = "\n\n".join(
                    f"Q: {seg['question']}\nR: {seg['answer']}"
                    for seg in segments.values()
                )
                trans = Transcription(
                    interview_id=iv.id,
                    full_text=full_text,
                    segments=segments,
                    language_detected="fr",
                    confidence_score=0.94,
                )
                s.add(trans)

                # Analysis
                analysis = Analysis(
                    interview_id=iv.id,
                    scores=iv_data["scores"],
                    score_explanations=iv_data.get("score_explanations"),
                    skill_scores=iv_data.get("skill_scores"),
                    skills_extracted=[{"skill": ss["skill"], "level": "avance" if ss["demonstrated"] >= 4 else "intermediaire", "type": "demontre"} for ss in (iv_data.get("skill_scores") or [])],
                    experience_examples=iv_data.get("experience_examples"),
                    communication_indicators=iv_data.get("communication_indicators"),
                )
                s.add(analysis)

                # Report (evaluated only)
                if cd["status"] == "evaluated" and iv_data.get("report"):
                    rpt = iv_data["report"]
                    report = Report(
                        candidate_id=cand.id, interview_id=iv.id,
                        content={
                            "candidate_name": cd["name"],
                            "position_title": cd["position"].title,
                            "score_global": iv_data["scores"]["global"],
                            "cv_score": cd["cv_score"],
                            "scores": iv_data["scores"],
                            "matching_score": rpt["matching_score"],
                            "summary": rpt["summary"],
                            "strengths": rpt["strengths"],
                            "areas_to_explore": rpt["areas_to_explore"],
                            "key_quotes": rpt["key_quotes"],
                            "recommendation": rpt["recommendation"],
                            "skill_matrix": iv_data.get("skill_scores"),
                            "metadata": {
                                "interview_duration": f"{iv_data['duration']}s",
                                "questions_count": len(iv_data["questions"]),
                                "generated_by": "AIHM AI Assistant",
                                "disclaimer": "Rapport genere par IA a titre informatif. Ne constitue pas une recommandation d'embauche.",
                            },
                        },
                    )
                    s.add(report)

            # Profile data (for all candidates with parsed CV)
            if cd.get("cv_parsed"):
                skills = cd["cv_parsed"].get("skills", [])
                exp_years = cd["cv_parsed"].get("experience_years", 0)
                p_score = min(95, max(35, cd["cv_score"] + random.randint(-8, 8)))
                cand.profile_score = p_score
                cand.profile_score_explanation = {
                    "overall": f"Profil {'senior' if exp_years >= 5 else 'mid-level'} avec {exp_years} ans d'experience. {'Expertise technique solide.' if p_score >= 70 else 'Profil en progression.'}",
                    "breakdown": {
                        "technical_depth": {"score": min(95, cd["cv_score"] + random.randint(-5, 10)), "detail": f"{len(skills)} competences techniques identifiees."},
                        "experience_quality": {"score": min(95, cd["cv_score"] + random.randint(-10, 5)), "detail": f"{exp_years} ans d'experience professionnelle."},
                        "education_relevance": {"score": min(95, cd["cv_score"] + random.randint(-15, 5)), "detail": cd["cv_parsed"].get("education", [{}])[0].get("degree", "Formation non precisee") if cd["cv_parsed"].get("education") else "Non precise."},
                        "cv_completeness": {"score": random.randint(55, 85), "detail": "CV structure avec les sections essentielles."},
                    },
                    "cv_quality_score": float(random.randint(50, 80)),
                    "cv_quality_details": {"impact": random.randint(40, 85), "clarity": random.randint(55, 90), "consistency": random.randint(50, 85), "completeness": random.randint(45, 80)},
                }
                cand.profile_competencies = {
                    "technical": [
                        {"name": sk, "level": random.randint(2, 5), "normalized": sk.lower().replace(" ", "_"), "demonstrated": True}
                        for sk in (skills[:12] if isinstance(skills[0], str) else [s.get("name", s) for s in skills[:12]])
                    ] if skills else [],
                    "experience": [
                        {"title": exp.get("title", ""), "company": exp.get("company", ""), "duration_months": random.randint(12, 48), "responsibilities": [exp.get("description", "")]}
                        for exp in cd["cv_parsed"].get("experiences", [])[:3]
                    ],
                    "education": [
                        {"degree": edu.get("degree", ""), "field": "Informatique", "institution": edu.get("school", "")}
                        for edu in cd["cv_parsed"].get("education", [])
                    ],
                    "languages": cd["cv_parsed"].get("languages", []),
                    "soft_skills": ["Travail en equipe", "Communication", "Autonomie"] if p_score >= 70 else ["Motivation", "Apprentissage rapide"],
                }
                cand.profile_suggestions = {
                    "suggestions": [
                        {"category": "impact", "priority": "high" if p_score < 70 else "medium", "suggestion": "Ajouter des resultats chiffres pour chaque experience professionnelle."},
                        {"category": "skills", "priority": "medium", "suggestion": "Detailler le niveau de maitrise pour chaque competence technique."},
                        {"category": "structure", "priority": "low", "suggestion": "Ajouter une section certifications si applicable."},
                    ],
                    "cv_quality_score": float(random.randint(50, 80)),
                    "cv_quality_details": {"impact": random.randint(40, 85), "clarity": random.randint(55, 90), "consistency": random.randint(50, 85), "completeness": random.randint(45, 80)},
                }

            print(f"  [{cd['status']}] {cd['name']} (score: {cd['cv_score']})")

        # ── Applications (cross-position matching) ──
        print("\n=== Candidatures croisees ===")
        from app.models.application import Application
        all_candidates = s.execute(select(Candidate).where(Candidate.tenant_id == tid)).scalars().all()
        all_positions = [pos_backend, pos_fullstack, pos_devops]
        app_count = 0
        for cand in all_candidates:
            # Create application for their own position
            if cand.position_id:
                app = Application(
                    tenant_id=tid, candidate_id=cand.id, position_id=cand.position_id,
                    match_score=cand.cv_score,
                    match_score_explanation=cand.cv_score_explanation,
                    pipeline_status=cand.pipeline_status,
                    decision="accepted" if cand.pipeline_status == "evaluated" and (cand.cv_score or 0) >= 75 else
                             "rejected" if cand.pipeline_status == "evaluated" and (cand.cv_score or 0) < 60 else "pending",
                    created_at=cand.created_at,
                )
                s.add(app)
                app_count += 1

            # Add 1-2 cross-position applications for some candidates
            if (cand.cv_score or 0) >= 70:
                other_positions = [p for p in all_positions if p.id != cand.position_id]
                for cross_pos in random.sample(other_positions, min(len(other_positions), random.randint(1, 2))):
                    cross_score = max(20, (cand.cv_score or 50) + random.randint(-25, -5))
                    s.add(Application(
                        tenant_id=tid, candidate_id=cand.id, position_id=cross_pos.id,
                        match_score=cross_score,
                        match_score_explanation={
                            "skills_overlap": {"score": cross_score + random.randint(-5, 5), "details": "Competences partiellement transferables."},
                            "experience_relevance": {"score": cross_score + random.randint(-10, 5), "details": "Experience dans un domaine adjacent."},
                            "seniority_fit": {"score": cross_score + random.randint(-5, 10), "details": "Niveau de seniorite compatible."},
                        },
                        pipeline_status="new",
                        decision="pending",
                        created_at=r_date(1, 15),
                    ))
                    app_count += 1

        print(f"  {app_count} candidatures creees")

        s.commit()

        print(f"\n{'='*60}")
        print(f"Demo seed termine !")
        print(f"  Tenant: TechRecruit Maroc")
        print(f"  3 postes actifs")
        print(f"  {len(CANDIDATES)} candidats a differents stades du pipeline")
        print(f"  4 entretiens complets avec transcriptions")
        print(f"  4 rapports d'evaluation detailles")
        print(f"\nConnexion: demo@techrecruit.ma / Demo2026!")
        print(f"{'='*60}")


if __name__ == "__main__":
    seed()
