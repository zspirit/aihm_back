"""
Seed script: populate the database with rich fixtures for testing.
Run: python scripts/seed_fixtures.py
"""
import os
import sys
import json
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
engine = create_engine(DATABASE_URL)

NOW = datetime.now(timezone.utc)


def get_ids(conn):
    """Get existing IDs from the database."""
    tenant = conn.execute(text("SELECT id FROM tenants LIMIT 1")).scalar()
    users = {}
    for row in conn.execute(text("SELECT id, email FROM users")).fetchall():
        users[row[1]] = row[0]
    positions = {}
    for row in conn.execute(text("SELECT id, title FROM positions")).fetchall():
        positions[row[1]] = row[0]
    candidates = {}
    for row in conn.execute(text("SELECT id, name, position_id FROM candidates")).fetchall():
        candidates[row[1]] = {"id": row[0], "position_id": row[2]}
    interviews = {}
    for row in conn.execute(text("SELECT id, candidate_id, status FROM interviews")).fetchall():
        interviews[str(row[0])] = {"candidate_id": row[1], "status": row[2]}
    return tenant, users, positions, candidates, interviews


def seed_position_skills(conn, positions):
    """Add required_skills to positions that lack them."""
    skills_map = {
        "Developpeur Full Stack Python/React": json.dumps([
            {"name": "Python", "category": "Backend", "level_required": 4, "weight": 3},
            {"name": "React", "category": "Frontend", "level_required": 4, "weight": 3},
            {"name": "PostgreSQL", "category": "Database", "level_required": 3, "weight": 2},
            {"name": "Docker", "category": "DevOps", "level_required": 2, "weight": 1},
            {"name": "API REST", "category": "Backend", "level_required": 4, "weight": 2},
        ]),
        "Data Scientist NLP": json.dumps([
            {"name": "Python", "category": "Backend", "level_required": 5, "weight": 3},
            {"name": "NLP/Transformers", "category": "AI/ML", "level_required": 4, "weight": 3},
            {"name": "PyTorch", "category": "AI/ML", "level_required": 4, "weight": 2},
            {"name": "SQL", "category": "Database", "level_required": 3, "weight": 1},
            {"name": "MLOps", "category": "DevOps", "level_required": 2, "weight": 1},
        ]),
        "Chef de projet IT": json.dumps([
            {"name": "Gestion de projet", "category": "Management", "level_required": 5, "weight": 3},
            {"name": "Agile/Scrum", "category": "Management", "level_required": 4, "weight": 3},
            {"name": "Communication", "category": "Soft Skills", "level_required": 4, "weight": 2},
            {"name": "Budget IT", "category": "Management", "level_required": 3, "weight": 2},
            {"name": "Architecture SI", "category": "Technique", "level_required": 3, "weight": 1},
        ]),
        "DevOps Engineer": json.dumps([
            {"name": "Kubernetes", "category": "DevOps", "level_required": 4, "weight": 3},
            {"name": "Docker", "category": "DevOps", "level_required": 5, "weight": 3},
            {"name": "CI/CD", "category": "DevOps", "level_required": 4, "weight": 2},
            {"name": "AWS/GCP", "category": "Cloud", "level_required": 4, "weight": 2},
            {"name": "Terraform", "category": "IaC", "level_required": 3, "weight": 2},
            {"name": "Linux", "category": "Systeme", "level_required": 4, "weight": 1},
        ]),
        "UX Designer": json.dumps([
            {"name": "Figma", "category": "Design", "level_required": 5, "weight": 3},
            {"name": "User Research", "category": "UX", "level_required": 4, "weight": 3},
            {"name": "Prototypage", "category": "Design", "level_required": 4, "weight": 2},
            {"name": "Design System", "category": "Design", "level_required": 3, "weight": 2},
            {"name": "HTML/CSS", "category": "Frontend", "level_required": 3, "weight": 1},
        ]),
        "Commercial B2B SaaS": json.dumps([
            {"name": "Vente B2B", "category": "Sales", "level_required": 5, "weight": 3},
            {"name": "CRM (Hubspot/Salesforce)", "category": "Outils", "level_required": 4, "weight": 2},
            {"name": "Negociation", "category": "Soft Skills", "level_required": 4, "weight": 3},
            {"name": "SaaS/Tech", "category": "Domaine", "level_required": 3, "weight": 2},
            {"name": "Prospection", "category": "Sales", "level_required": 4, "weight": 2},
        ]),
    }
    for title, skills_json in skills_map.items():
        if title in positions:
            conn.execute(
                text("UPDATE positions SET required_skills = :s WHERE id = :id"),
                {"s": skills_json, "id": positions[title]},
            )
    print(f"  Updated skills for {len(skills_map)} positions")


def seed_transcriptions(conn, interviews):
    """Add transcriptions for completed interviews that lack them."""
    existing = set(
        str(r[0]) for r in conn.execute(text("SELECT interview_id FROM transcriptions")).fetchall()
    )

    transcription_templates = [
        {
            "full_text": "Bonjour, merci d'avoir accepte cet entretien. Pouvez-vous vous presenter ? - Bien sur, je suis developpeur avec 5 ans d'experience en Python et React. J'ai travaille sur des projets SaaS chez TechCorp Maroc. Mon dernier projet concernait une plateforme de gestion RH. - Tres bien. Qu'est-ce qui vous motive dans ce poste ? - L'aspect IA et l'impact sur le recrutement au Maroc. Je suis passionne par l'automatisation intelligente. - Pouvez-vous decrire un defi technique que vous avez resolu ? - Oui, on avait un probleme de performance sur une API avec 100k requetes/jour. J'ai implemente du caching Redis et optimise les requetes SQL, ce qui a reduit le temps de reponse de 2s a 200ms.",
            "segments": [
                {"start": 0, "end": 5, "text": "Bonjour, merci d'avoir accepte cet entretien.", "speaker": "ai"},
                {"start": 5, "end": 35, "text": "Je suis developpeur avec 5 ans d'experience en Python et React.", "speaker": "candidate"},
                {"start": 35, "end": 45, "text": "Qu'est-ce qui vous motive dans ce poste ?", "speaker": "ai"},
                {"start": 45, "end": 75, "text": "L'aspect IA et l'impact sur le recrutement au Maroc.", "speaker": "candidate"},
                {"start": 75, "end": 85, "text": "Pouvez-vous decrire un defi technique ?", "speaker": "ai"},
                {"start": 85, "end": 130, "text": "On avait un probleme de performance, j'ai implemente du caching Redis.", "speaker": "candidate"},
            ],
            "language": "fr",
            "confidence": 0.94,
        },
        {
            "full_text": "Bienvenue. Parlez-moi de votre parcours. - J'ai un master en data science de l'ENSIAS. J'ai travaille 3 ans sur des projets NLP chez DataLab. Mon expertise est dans les transformers et le fine-tuning de modeles. - Comment gerez-vous un dataset de mauvaise qualite ? - Je commence par un audit des donnees, nettoyage, et augmentation. Sur un projet recent, j'ai ameliore la precision de 65% a 89% en corrigeant le biais dans les labels. - Quel est votre framework prefere ? - PyTorch pour la recherche, mais j'utilise aussi HuggingFace pour le deploiement rapide.",
            "segments": [
                {"start": 0, "end": 8, "text": "Bienvenue. Parlez-moi de votre parcours.", "speaker": "ai"},
                {"start": 8, "end": 45, "text": "J'ai un master en data science de l'ENSIAS.", "speaker": "candidate"},
                {"start": 45, "end": 55, "text": "Comment gerez-vous un dataset de mauvaise qualite ?", "speaker": "ai"},
                {"start": 55, "end": 100, "text": "Je commence par un audit des donnees, nettoyage, et augmentation.", "speaker": "candidate"},
                {"start": 100, "end": 110, "text": "Quel est votre framework prefere ?", "speaker": "ai"},
                {"start": 110, "end": 140, "text": "PyTorch pour la recherche, HuggingFace pour le deploiement.", "speaker": "candidate"},
            ],
            "language": "fr",
            "confidence": 0.91,
        },
        {
            "full_text": "Merci de prendre le temps pour cet entretien. Comment decririez-vous votre style de management ? - Je suis tres oriente resultats mais aussi a l'ecoute. J'ai gere une equipe de 8 developpeurs sur un projet de migration cloud. Le cle c'etait la communication transparente et les sprints courts. - Comment gerez-vous les conflits dans l'equipe ? - J'organise des retrospectives regulieres et je favorise le dialogue direct. Un exemple : deux devs n'etaient pas d'accord sur l'architecture. J'ai organise un spike technique d'une journee et on a trouve un compromis ensemble.",
            "segments": [
                {"start": 0, "end": 10, "text": "Comment decririez-vous votre style de management ?", "speaker": "ai"},
                {"start": 10, "end": 55, "text": "Je suis tres oriente resultats mais aussi a l'ecoute.", "speaker": "candidate"},
                {"start": 55, "end": 65, "text": "Comment gerez-vous les conflits dans l'equipe ?", "speaker": "ai"},
                {"start": 65, "end": 120, "text": "J'organise des retrospectives regulieres et je favorise le dialogue direct.", "speaker": "candidate"},
            ],
            "language": "fr",
            "confidence": 0.92,
        },
    ]

    count = 0
    for iid, info in interviews.items():
        if info["status"] == "completed" and iid not in existing:
            tmpl = transcription_templates[count % len(transcription_templates)]
            conn.execute(
                text("""
                    INSERT INTO transcriptions (id, interview_id, full_text, segments, language_detected, confidence_score, created_at)
                    VALUES (:id, :iid, :ft, :seg, :lang, :conf, :cat)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "iid": iid,
                    "ft": tmpl["full_text"],
                    "seg": json.dumps(tmpl["segments"]),
                    "lang": tmpl["language"],
                    "conf": tmpl["confidence"],
                    "cat": NOW - timedelta(days=count, hours=2),
                },
            )
            count += 1
    print(f"  Created {count} transcriptions")


def seed_analyses(conn, interviews, candidates):
    """Add analyses for completed interviews that lack them."""
    existing = set(
        str(r[0]) for r in conn.execute(text("SELECT interview_id FROM analyses")).fetchall()
    )

    score_profiles = [
        {"global": 85, "competences_techniques": 88, "adequation_poste": 82, "communication": 90, "motivation": 87},
        {"global": 72, "competences_techniques": 75, "adequation_poste": 68, "communication": 78, "motivation": 65},
        {"global": 91, "competences_techniques": 93, "adequation_poste": 89, "communication": 85, "motivation": 95},
        {"global": 58, "competences_techniques": 55, "adequation_poste": 62, "communication": 60, "motivation": 52},
        {"global": 78, "competences_techniques": 80, "adequation_poste": 75, "communication": 82, "motivation": 74},
        {"global": 66, "competences_techniques": 70, "adequation_poste": 60, "communication": 65, "motivation": 68},
        {"global": 88, "competences_techniques": 85, "adequation_poste": 90, "communication": 92, "motivation": 84},
        {"global": 45, "competences_techniques": 40, "adequation_poste": 48, "communication": 50, "motivation": 42},
    ]

    skill_score_profiles = [
        {"Python": {"demonstrated": 4, "motivation": 5, "evidence": "5 ans d'experience, projets complexes"}, "React": {"demonstrated": 4, "motivation": 4, "evidence": "Projets SaaS frontend"}},
        {"NLP": {"demonstrated": 5, "motivation": 5, "evidence": "Expert transformers, publications"}, "PyTorch": {"demonstrated": 4, "motivation": 4, "evidence": "Utilisation quotidienne"}},
        {"Gestion de projet": {"demonstrated": 4, "motivation": 3, "evidence": "8 personnes gerees"}, "Agile": {"demonstrated": 5, "motivation": 4, "evidence": "Scrum master certifie"}},
        {"Kubernetes": {"demonstrated": 3, "motivation": 4, "evidence": "2 clusters en prod"}, "Docker": {"demonstrated": 5, "motivation": 4, "evidence": "Expert containerisation"}},
    ]

    explanations = [
        {"global": "Candidat solide avec de bonnes competences techniques et une forte motivation.", "competences_techniques": "Maitrise confirmee des technologies cles du poste."},
        {"global": "Profil correct mais manque d'experience sur certains aspects.", "competences_techniques": "Competences de base presentes, progression possible."},
        {"global": "Excellent candidat, depasse les attentes sur tous les criteres.", "competences_techniques": "Expert reconnu avec des realisations concretes."},
        {"global": "Profil junior, necessite un accompagnement important.", "competences_techniques": "Connaissances theoriques mais peu de pratique."},
    ]

    count = 0
    for iid, info in interviews.items():
        if info["status"] == "completed" and iid not in existing:
            idx = count % len(score_profiles)
            conn.execute(
                text("""
                    INSERT INTO analyses (id, interview_id, skills_extracted, experience_examples,
                        communication_indicators, scores, score_explanations, skill_scores, created_at)
                    VALUES (:id, :iid, :se, :ee, :ci, :sc, :sce, :sks, :cat)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "iid": iid,
                    "se": json.dumps(["Python", "React", "SQL", "Docker", "API REST", "Git"]),
                    "ee": json.dumps([
                        "Migration cloud pour 50k utilisateurs",
                        "Optimisation API de 2s a 200ms",
                        "Mise en place CI/CD complete",
                    ]),
                    "ci": json.dumps({
                        "clarity": 0.85 + (count % 3) * 0.05,
                        "confidence": 0.80 + (count % 4) * 0.04,
                        "engagement": 0.82 + (count % 3) * 0.06,
                    }),
                    "sc": json.dumps(score_profiles[idx]),
                    "sce": json.dumps(explanations[idx % len(explanations)]),
                    "sks": json.dumps(skill_score_profiles[idx % len(skill_score_profiles)]),
                    "cat": NOW - timedelta(days=count, hours=1),
                },
            )
            count += 1
    print(f"  Created {count} analyses")


def seed_reports(conn, interviews, candidates):
    """Add reports for completed interviews that lack them."""
    existing_interviews = set(
        str(r[0]) for r in conn.execute(text("SELECT interview_id FROM reports")).fetchall()
    )

    # Reverse map candidate_id -> name
    cand_id_to_name = {}
    for name, info in candidates.items():
        cand_id_to_name[str(info["id"])] = name

    report_templates = [
        {
            "recommendation": "Recommande",
            "summary": "Candidat avec un profil technique solide et une bonne capacite de communication. Repond aux exigences du poste avec une experience pertinente.",
            "strengths": ["Expertise technique confirmee", "Bonne capacite d'analyse", "Motivation elevee"],
            "weaknesses": ["Manque d'experience en management", "Anglais a ameliorer"],
        },
        {
            "recommendation": "Recommande avec reserves",
            "summary": "Profil interessant mais necessite un accompagnement sur certains aspects techniques. Potentiel de progression.",
            "strengths": ["Bonne motivation", "Capacite d'apprentissage", "Esprit d'equipe"],
            "weaknesses": ["Competences techniques a approfondir", "Peu d'experience en production"],
        },
        {
            "recommendation": "Fortement recommande",
            "summary": "Excellent candidat qui depasse les attentes. Profil rare avec une combinaison de competences techniques et humaines exceptionnelle.",
            "strengths": ["Expert technique reconnu", "Leadership naturel", "Communication excellente", "Vision strategique"],
            "weaknesses": ["Attentes salariales elevees"],
        },
        {
            "recommendation": "Non recommande",
            "summary": "Le candidat ne repond pas aux exigences minimales du poste. Les lacunes techniques sont trop importantes.",
            "strengths": ["Motivation presente", "Ponctualite"],
            "weaknesses": ["Competences techniques insuffisantes", "Difficulte a structurer ses reponses", "Manque d'exemples concrets"],
        },
    ]

    count = 0
    for iid, info in interviews.items():
        if info["status"] == "completed" and iid not in existing_interviews:
            cand_name = cand_id_to_name.get(str(info["candidate_id"]), "Candidat")
            tmpl = report_templates[count % len(report_templates)]
            content = {
                "candidate_name": cand_name,
                "recommendation": tmpl["recommendation"],
                "summary": tmpl["summary"],
                "strengths": tmpl["strengths"],
                "weaknesses": tmpl["weaknesses"],
                "skill_matrix": [
                    {"skill": "Python", "required": 4, "demonstrated": 3 + (count % 3), "gap": max(0, 4 - 3 - (count % 3))},
                    {"skill": "React", "required": 4, "demonstrated": 2 + (count % 4), "gap": max(0, 4 - 2 - (count % 4))},
                    {"skill": "SQL", "required": 3, "demonstrated": 3 + (count % 2), "gap": 0},
                ],
                "matching_score": 60 + (count * 7) % 35,
            }
            conn.execute(
                text("""
                    INSERT INTO reports (id, candidate_id, interview_id, content, generated_at)
                    VALUES (:id, :cid, :iid, :content, :gat)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "cid": str(info["candidate_id"]),
                    "iid": iid,
                    "content": json.dumps(content),
                    "gat": NOW - timedelta(days=count),
                },
            )
            count += 1
    print(f"  Created {count} reports")


def seed_new_interviews(conn, tenant, users, candidates):
    """Add interviews in various statuses (scheduled, in_progress, failed)."""
    admin_id = users["admin@aihm.ai"]

    # Candidates that should have scheduled/in-progress interviews
    interview_data = [
        {"candidate": "Omar Kettani", "status": "scheduled", "scheduled_at": NOW + timedelta(days=2, hours=10)},
        {"candidate": "Mehdi Alaoui", "status": "scheduled", "scheduled_at": NOW + timedelta(days=3, hours=14)},
        {"candidate": "Kenza Lamrani", "status": "scheduled", "scheduled_at": NOW + timedelta(days=1, hours=9)},
        {"candidate": "Saad Jabri", "status": "scheduled", "scheduled_at": NOW + timedelta(days=4, hours=11)},
        {"candidate": "Meryem Benhima", "status": "in_progress", "scheduled_at": NOW - timedelta(minutes=15), "started_at": NOW - timedelta(minutes=10)},
        {"candidate": "Zineb Idrissi", "status": "failed", "scheduled_at": NOW - timedelta(days=1), "started_at": NOW - timedelta(days=1), "ended_at": NOW - timedelta(days=1, hours=-0.1)},
        {"candidate": "Khalid Bennani", "status": "no_answer", "scheduled_at": NOW - timedelta(days=2), "started_at": NOW - timedelta(days=2)},
    ]

    # Check existing interviews for these candidates
    existing_cands = set(
        str(r[0]) for r in conn.execute(text("SELECT candidate_id FROM interviews")).fetchall()
    )

    count = 0
    for item in interview_data:
        cand_name = item["candidate"]
        if cand_name not in candidates:
            continue
        cand = candidates[cand_name]
        if str(cand["id"]) in existing_cands:
            continue

        params = {
            "id": str(uuid.uuid4()),
            "candidate_id": str(cand["id"]),
            "position_id": str(cand["position_id"]),
            "tenant_id": str(tenant),
            "status": item["status"],
            "scheduled_at": item.get("scheduled_at"),
            "started_at": item.get("started_at"),
            "ended_at": item.get("ended_at"),
            "duration_seconds": None,
            "attempt_number": 1,
            "created_at": NOW - timedelta(days=5 - count),
        }
        conn.execute(
            text("""
                INSERT INTO interviews (id, candidate_id, position_id, tenant_id, status,
                    scheduled_at, started_at, ended_at, duration_seconds, attempt_number, created_at)
                VALUES (:id, :candidate_id, :position_id, :tenant_id, :status,
                    :scheduled_at, :started_at, :ended_at, :duration_seconds, :attempt_number, :created_at)
            """),
            params,
        )
        count += 1
    print(f"  Created {count} new interviews (scheduled/in_progress/failed)")


def seed_notifications(conn, tenant, users):
    """Add sample notifications."""
    # Clear old
    conn.execute(text("DELETE FROM notifications"))

    admin_id = users["admin@aihm.ai"]
    recruiter_id = users["karim@aihm.ai"]

    notifs = [
        {"user": admin_id, "type": "cv_scored", "title": "CV evalue", "message": "Le CV de Ayoub Cherkaoui a obtenu un score de 90.3/100", "read": False, "ago_hours": 1},
        {"user": admin_id, "type": "interview_completed", "title": "Entretien termine", "message": "L'entretien avec Layla Moussaoui est termine (6min 07s)", "read": False, "ago_hours": 3},
        {"user": admin_id, "type": "interview_scheduled", "title": "Entretien planifie", "message": "Entretien avec Omar Kettani planifie pour le 27/02 a 10h", "read": False, "ago_hours": 5},
        {"user": admin_id, "type": "report_ready", "title": "Rapport genere", "message": "Le rapport d'evaluation de Rachid Tazi est disponible", "read": True, "ago_hours": 12},
        {"user": admin_id, "type": "candidate_new", "title": "Nouveau candidat", "message": "3 nouveaux candidats importes pour le poste DevOps Engineer", "read": True, "ago_hours": 24},
        {"user": admin_id, "type": "consent_granted", "title": "Consentement accorde", "message": "Kenza Lamrani a accepte l'entretien telephonique", "read": True, "ago_hours": 28},
        {"user": admin_id, "type": "auto_advance", "title": "Avancement automatique", "message": "Imane Hajji avancee automatiquement (score CV: 88.7 >= seuil 80)", "read": False, "ago_hours": 6},
        {"user": admin_id, "type": "auto_reject", "title": "Rejet automatique", "message": "Hamza Filali rejete automatiquement (score CV: 45.0 < seuil 50)", "read": False, "ago_hours": 7},
        {"user": recruiter_id, "type": "interview_completed", "title": "Entretien termine", "message": "L'entretien avec Reda Bouazza est termine (5min 54s)", "read": False, "ago_hours": 2},
        {"user": recruiter_id, "type": "cv_scored", "title": "CV evalue", "message": "Le CV de Soukaina Rami a obtenu un score de 77.0/100", "read": True, "ago_hours": 15},
        {"user": recruiter_id, "type": "interview_failed", "title": "Entretien echoue", "message": "Zineb Idrissi n'a pas repondu a l'appel. Nouvelle tentative possible.", "read": False, "ago_hours": 8},
        {"user": recruiter_id, "type": "candidate_new", "title": "Nouveau candidat", "message": "Nadia Chraibi ajoutee au poste Developpeur Full Stack", "read": True, "ago_hours": 48},
    ]

    for n in notifs:
        conn.execute(
            text("""
                INSERT INTO notifications (id, tenant_id, user_id, type, title, message, data, read, created_at)
                VALUES (:id, :tid, :uid, :type, :title, :msg, :data, :read, :cat)
            """),
            {
                "id": str(uuid.uuid4()),
                "tid": str(tenant),
                "uid": str(n["user"]),
                "type": n["type"],
                "title": n["title"],
                "msg": n["message"],
                "data": json.dumps({}),
                "read": n["read"],
                "cat": NOW - timedelta(hours=n["ago_hours"]),
            },
        )
    print(f"  Created {len(notifs)} notifications")


def seed_audit_logs(conn, tenant, users):
    """Add diverse audit log entries."""
    admin_id = users["admin@aihm.ai"]
    recruiter_id = users["karim@aihm.ai"]
    recruteur_id = users["recruteur@aihm.ai"]

    logs = [
        {"user": admin_id, "action": "login", "type": "user", "details": {"email": "admin@aihm.ai"}, "ago_days": 0, "ago_hours": 1},
        {"user": admin_id, "action": "position_create", "type": "position", "details": {"title": "DevOps Engineer"}, "ago_days": 5},
        {"user": admin_id, "action": "position_update", "type": "position", "details": {"title": "DevOps Engineer", "changes": ["description", "required_skills"]}, "ago_days": 4},
        {"user": recruiter_id, "action": "login", "type": "user", "details": {"email": "karim@aihm.ai"}, "ago_days": 0, "ago_hours": 2},
        {"user": recruiter_id, "action": "candidate_delete", "type": "candidate", "details": {"name": "Test Candidat", "reason": "doublon"}, "ago_days": 3},
        {"user": admin_id, "action": "interview_reschedule", "type": "interview", "details": {"candidate": "Omar Kettani", "new_date": "2026-02-27T10:00:00Z"}, "ago_days": 1},
        {"user": recruteur_id, "action": "login", "type": "user", "details": {"email": "recruteur@aihm.ai"}, "ago_days": 0, "ago_hours": 5},
        {"user": admin_id, "action": "interview_cancel", "type": "interview", "details": {"candidate": "Khalid Bennani", "reason": "pas de reponse"}, "ago_days": 2},
        {"user": admin_id, "action": "position_delete", "type": "position", "details": {"title": "Stage Marketing (test)"}, "ago_days": 6},
        {"user": admin_id, "action": "user_invite", "type": "user", "details": {"email": "karim@aihm.ai", "role": "recruiter"}, "ago_days": 10},
        {"user": admin_id, "action": "password_change", "type": "user", "details": {}, "ago_days": 8},
        {"user": admin_id, "action": "auto_advance", "type": "candidate", "details": {"candidate": "Imane Hajji", "cv_score": 88.7, "threshold": 80}, "ago_days": 1},
        {"user": admin_id, "action": "auto_reject", "type": "candidate", "details": {"candidate": "Hamza Filali", "cv_score": 45.0, "threshold": 50}, "ago_days": 1},
    ]

    count = 0
    for log in logs:
        conn.execute(
            text("""
                INSERT INTO audit_logs (id, tenant_id, user_id, action, entity_type, entity_id, details, created_at)
                VALUES (:id, :tid, :uid, :action, :etype, :eid, :details, :cat)
            """),
            {
                "id": str(uuid.uuid4()),
                "tid": str(tenant),
                "uid": str(log["user"]),
                "action": log["action"],
                "etype": log["type"],
                "eid": str(uuid.uuid4()),
                "details": json.dumps(log["details"]),
                "cat": NOW - timedelta(days=log.get("ago_days", 0), hours=log.get("ago_hours", 0)),
            },
        )
        count += 1
    print(f"  Created {count} audit logs")


def seed_consents(conn, candidates):
    """Add consents for candidates in consent_given and later stages."""
    existing = set(
        str(r[0]) for r in conn.execute(text("SELECT candidate_id FROM consents")).fetchall()
    )

    consent_candidates = [
        "Kenza Lamrani", "Omar Kettani", "Saad Jabri",
        "Imane Hajji", "Reda Bouazza", "Rachid Tazi", "Layla Moussaoui",
        "Ayoub Cherkaoui", "Soukaina Rami",
        "Salma Ouazzani", "Youssef El Amrani", "Fatima Zahra Benali",
        # New candidates
        "Amina Fikri", "Yasmine Bouzid", "Rania Chami",
        "Hicham Boukili", "Tariq El Mansouri",
        "Yassine Berrada", "Najat El Idrissi", "Mouad Skalli",
        "Driss Kadiri", "Samira Zouak",
        "Hajar Idrissi", "Kamal Mouhssine",
    ]

    count = 0
    for name in consent_candidates:
        if name not in candidates:
            continue
        cand = candidates[name]
        if str(cand["id"]) in existing:
            continue
        conn.execute(
            text("""
                INSERT INTO consents (id, candidate_id, token, type, granted, granted_at, channel, created_at)
                VALUES (:id, :cid, :token, :type, :granted, :gat, :channel, :cat)
            """),
            {
                "id": str(uuid.uuid4()),
                "cid": str(cand["id"]),
                "token": str(uuid.uuid4()),
                "type": "phone_interview",
                "granted": True,
                "gat": NOW - timedelta(days=count + 1, hours=3),
                "channel": "email",
                "cat": NOW - timedelta(days=count + 2),
            },
        )
        count += 1
    print(f"  Created {count} consents")


def seed_candidates(conn, tenant, positions, candidates):
    """Add more candidates across all positions, including UX Designer."""
    import random as rnd

    new_candidates = [
        # UX Designer (currently 0 candidates)
        ("Amina Fikri", "amina.fikri@gmail.com", "+212683456789", "UX Designer", "evaluated", 86.2),
        ("Yasmine Bouzid", "yasmine.bouzid@outlook.com", "+212684567890", "UX Designer", "call_done", 74.0),
        ("Rania Chami", "rania.chami@gmail.com", "+212685678901", "UX Designer", "consent_given", 69.5),
        ("Othmane Lahlou", "othmane.lahlou@yahoo.fr", "+212686789012", "UX Designer", "cv_analyzed", 81.3),
        ("Leila Tahiri", "leila.tahiri@gmail.com", "+212687890123", "UX Designer", "new", None),

        # Full Stack (more candidates)
        ("Hicham Boukili", "hicham.boukili@gmail.com", "+212688901234", "Developpeur Full Stack Python/React", "evaluated", 78.9),
        ("Sara Amrani", "sara.amrani@outlook.com", "+212689012345", "Developpeur Full Stack Python/React", "cv_analyzed", 64.5),
        ("Tariq El Mansouri", "tariq.elmansouri@gmail.com", "+212690123456", "Developpeur Full Stack Python/React", "consent_given", 82.1),
        ("Ghita Ouaziz", "ghita.ouaziz@yahoo.fr", "+212691234567", "Developpeur Full Stack Python/React", "new", None),

        # Data Science (more)
        ("Yassine Berrada", "yassine.berrada@gmail.com", "+212692345678", "Data Scientist NLP", "evaluated", 92.0),
        ("Maha Senhaji", "maha.senhaji@outlook.com", "+212693456789", "Data Scientist NLP", "cv_analyzed", 71.8),
        ("Adil Benchekroun", "adil.benchekroun@gmail.com", "+212694567890", "Data Scientist NLP", "new", None),

        # Chef de projet (more)
        ("Najat El Idrissi", "najat.elidrissi@gmail.com", "+212695678901", "Chef de projet IT", "evaluated", 87.3),
        ("Mouad Skalli", "mouad.skalli@outlook.com", "+212696789012", "Chef de projet IT", "consent_given", 75.0),
        ("Wiam Benkirane", "wiam.benkirane@gmail.com", "+212697890123", "Chef de projet IT", "cv_analyzed", 66.8),

        # DevOps (more)
        ("Driss Kadiri", "driss.kadiri@gmail.com", "+212698901234", "DevOps Engineer", "evaluated", 84.6),
        ("Samira Zouak", "samira.zouak@outlook.com", "+212699012345", "DevOps Engineer", "call_done", 70.2),
        ("Anas Bennani", "anas.bennani@gmail.com", "+212700123456", "DevOps Engineer", "cv_analyzed", 78.4),

        # Commercial (more)
        ("Hajar Idrissi", "hajar.idrissi@gmail.com", "+212701234567", "Commercial B2B SaaS", "evaluated", 83.0),
        ("Kamal Mouhssine", "kamal.mouhssine@outlook.com", "+212702345678", "Commercial B2B SaaS", "consent_given", 59.8),
        ("Rim El Ouafi", "rim.elouafi@gmail.com", "+212703456789", "Commercial B2B SaaS", "cv_analyzed", 72.5),
    ]

    existing_emails = set(
        r[0] for r in conn.execute(text("SELECT email FROM candidates WHERE email IS NOT NULL")).fetchall()
    )

    count = 0
    for name, email, phone, pos_title, status, score in new_candidates:
        if email in existing_emails:
            continue
        if pos_title not in positions:
            continue

        score_explanation = json.dumps({
            "competences": rnd.randint(45, 95),
            "experience": rnd.randint(40, 95),
            "formation": rnd.randint(45, 90),
        }) if score else None

        parsed_data = json.dumps({
            "summary": f"Professionnel avec expertise en {pos_title.split()[0].lower()}",
            "skills": rnd.sample(["Python", "React", "Docker", "SQL", "Git", "Figma", "NLP", "Scrum", "AWS", "Vente B2B", "Negociation", "Kubernetes"], min(5, rnd.randint(3, 6))),
            "experience_years": rnd.randint(2, 12),
            "languages": rnd.sample(["Francais", "Arabe", "Anglais", "Espagnol"], rnd.randint(2, 3)),
        }) if score else None

        cand_id = str(uuid.uuid4())
        conn.execute(
            text("""
                INSERT INTO candidates (id, tenant_id, position_id, name, email, phone,
                    pipeline_status, cv_score, cv_score_explanation, cv_parsed_data, created_at)
                VALUES (:id, :tid, :pid, :name, :email, :phone,
                    :status, :score, :explanation, :parsed, :cat)
            """),
            {
                "id": cand_id,
                "tid": str(tenant),
                "pid": positions[pos_title],
                "name": name,
                "email": email,
                "phone": phone,
                "status": status,
                "score": score,
                "explanation": score_explanation,
                "parsed": parsed_data,
                "cat": NOW - timedelta(days=rnd.randint(2, 40), hours=rnd.randint(0, 23)),
            },
        )
        count += 1

    print(f"  Created {count} new candidates")


def seed_extra_interviews(conn, tenant, candidates):
    """Add extra interviews for candidates with evaluated/call_done status that don't have one yet."""
    import random as rnd

    # Get candidates with evaluated/call_done that need interviews
    existing_cand_ids = set(
        str(r[0]) for r in conn.execute(text("SELECT DISTINCT candidate_id FROM interviews")).fetchall()
    )

    need_interviews = [
        name for name, info in candidates.items()
        if str(info["id"]) not in existing_cand_ids
    ]

    # Get pipeline status of these candidates
    count = 0
    for name in need_interviews:
        cand = candidates[name]
        cid = str(cand["id"])
        pid = str(cand["position_id"])

        # Check pipeline_status
        row = conn.execute(
            text("SELECT pipeline_status FROM candidates WHERE id = :id"),
            {"id": cid},
        ).fetchone()
        if not row or row[0] not in ("call_done", "evaluated"):
            continue

        duration = rnd.randint(180, 480)
        started = NOW - timedelta(days=rnd.randint(1, 15), hours=rnd.randint(1, 20))
        conn.execute(
            text("""
                INSERT INTO interviews (id, candidate_id, position_id, tenant_id, status,
                    scheduled_at, started_at, ended_at, duration_seconds, attempt_number, created_at)
                VALUES (:id, :cid, :pid, :tid, 'completed',
                    :sched, :started, :ended, :dur, 1, :cat)
            """),
            {
                "id": str(uuid.uuid4()),
                "cid": cid,
                "pid": pid,
                "tid": str(tenant),
                "sched": started - timedelta(hours=1),
                "started": started,
                "ended": started + timedelta(seconds=duration),
                "dur": duration,
                "cat": started - timedelta(hours=2),
            },
        )
        count += 1
    print(f"  Created {count} extra interviews for new candidates")


def seed_cv_parsed_data(conn, candidates):
    """Fill cv_parsed_data for candidates that have a cv_score but no parsed data."""
    import random as rnd

    skill_pools = {
        "tech": ["Python", "JavaScript", "TypeScript", "React", "FastAPI", "Django", "Node.js", "PostgreSQL", "Docker", "Git", "Redis", "GraphQL"],
        "data": ["Python", "PyTorch", "TensorFlow", "NLP", "Transformers", "Pandas", "SQL", "Scikit-learn", "MLOps", "HuggingFace"],
        "management": ["Gestion de projet", "Agile", "Scrum", "JIRA", "Confluence", "Budget IT", "Risk Management", "Kanban"],
        "devops": ["Docker", "Kubernetes", "Terraform", "AWS", "GCP", "CI/CD", "Linux", "Ansible", "Prometheus", "Grafana"],
        "design": ["Figma", "Sketch", "Adobe XD", "Prototypage", "Design System", "User Research", "Wireframing", "HTML/CSS"],
        "sales": ["Vente B2B", "CRM", "Hubspot", "Salesforce", "Negociation", "Prospection", "SaaS", "Account Management"],
    }

    summaries = [
        "Professionnel experimente avec une solide expertise technique et une bonne capacite d'adaptation.",
        "Candidat motive avec un parcours diversifie et des competences variees.",
        "Profil junior prometteur avec de bonnes bases theoriques et une envie d'apprendre.",
        "Expert senior avec plus de 8 ans d'experience dans le domaine.",
        "Professionnel polyvalent avec une double competence technique et fonctionnelle.",
    ]

    count = 0
    for name, info in candidates.items():
        cid = str(info["id"])
        row = conn.execute(
            text("SELECT cv_score, cv_parsed_data, position_id FROM candidates WHERE id = :id"),
            {"id": cid},
        ).fetchone()

        if not row or row[0] is None or row[1] is not None:
            continue

        # Determine skill pool based on position
        pos_title = conn.execute(
            text("SELECT title FROM positions WHERE id = :id"),
            {"id": str(row[2])},
        ).scalar() or ""

        pool = "tech"
        if "Data" in pos_title or "NLP" in pos_title:
            pool = "data"
        elif "Chef" in pos_title or "projet" in pos_title:
            pool = "management"
        elif "DevOps" in pos_title:
            pool = "devops"
        elif "UX" in pos_title or "Design" in pos_title:
            pool = "design"
        elif "Commercial" in pos_title:
            pool = "sales"

        skills = rnd.sample(skill_pools[pool], min(len(skill_pools[pool]), rnd.randint(4, 7)))
        parsed = json.dumps({
            "summary": rnd.choice(summaries),
            "skills": skills,
            "experience_years": rnd.randint(2, 12),
            "languages": rnd.sample(["Francais", "Arabe", "Anglais", "Espagnol", "Allemand"], rnd.randint(2, 3)),
        })

        conn.execute(
            text("UPDATE candidates SET cv_parsed_data = :data WHERE id = :id"),
            {"data": parsed, "id": cid},
        )
        count += 1

    print(f"  Filled cv_parsed_data for {count} candidates")


def seed_workflow_thresholds(conn, positions):
    """Set auto_advance and auto_reject thresholds on some positions."""
    thresholds = {
        "Developpeur Full Stack Python/React": {"advance": 80, "reject": 40},
        "Data Scientist NLP": {"advance": 85, "reject": 50},
        "DevOps Engineer": {"advance": 75, "reject": 35},
    }
    for title, t in thresholds.items():
        if title in positions:
            conn.execute(
                text("""
                    UPDATE positions SET auto_advance_threshold = :adv, auto_reject_threshold = :rej
                    WHERE id = :id
                """),
                {"adv": t["advance"], "rej": t["reject"], "id": positions[title]},
            )
    print(f"  Set workflow thresholds on {len(thresholds)} positions")


def main():
    print("Seeding AIHM fixtures...")
    with engine.begin() as conn:
        tenant, users, positions, candidates, interviews = get_ids(conn)
        print(f"Found: {len(users)} users, {len(positions)} positions, {len(candidates)} candidates, {len(interviews)} interviews")

        print("\n1. Position skills...")
        seed_position_skills(conn, positions)

        print("2. Workflow thresholds...")
        seed_workflow_thresholds(conn, positions)

        print("3. New candidates...")
        seed_candidates(conn, tenant, positions, candidates)

        # Refresh candidates after adding new ones
        candidates = {}
        for row in conn.execute(text("SELECT id, name, position_id FROM candidates")).fetchall():
            candidates[row[1]] = {"id": row[0], "position_id": row[2]}

        print("4. CV parsed data...")
        seed_cv_parsed_data(conn, candidates)

        print("5. Consents...")
        seed_consents(conn, candidates)

        print("6. New interviews...")
        seed_new_interviews(conn, tenant, users, candidates)

        print("7. Extra interviews for new candidates...")
        seed_extra_interviews(conn, tenant, candidates)

        # Refresh interviews
        interviews = {}
        for row in conn.execute(text("SELECT id, candidate_id, status FROM interviews")).fetchall():
            interviews[str(row[0])] = {"candidate_id": row[1], "status": row[2]}

        print("8. Transcriptions...")
        seed_transcriptions(conn, interviews)

        print("9. Analyses...")
        seed_analyses(conn, interviews, candidates)

        print("10. Reports...")
        seed_reports(conn, interviews, candidates)

        print("11. Notifications...")
        seed_notifications(conn, tenant, users)

        print("12. Audit logs...")
        seed_audit_logs(conn, tenant, users)

    # Final counts
    with engine.connect() as conn:
        print("\nFinal counts:")
        for t in ["positions", "candidates", "interviews", "transcriptions", "analyses", "reports", "consents", "notifications", "audit_logs"]:
            r = conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()
            print(f"  {t}: {r}")

    print("\nDone!")


if __name__ == "__main__":
    main()
