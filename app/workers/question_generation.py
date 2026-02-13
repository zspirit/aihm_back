import json

import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(name="questions.generate", bind=True, max_retries=3)
def generate_questions(self, candidate_id: str):
    logger.info("question_generation_start", candidate_id=candidate_id)

    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from uuid import UUID

        from app.models.candidate import Candidate
        from app.models.position import Position

        candidate = session.get(Candidate, UUID(candidate_id))
        if not candidate:
            return

        position = session.get(Position, candidate.position_id)

        questions = generate_interview_questions(candidate, position)

        # Store generated questions on the position if empty, or use per-interview
        logger.info(
            "question_generation_done",
            candidate_id=candidate_id,
            question_count=len(questions),
        )

        session.commit()
        return questions

    except Exception as e:
        session.rollback()
        logger.error("question_generation_error", candidate_id=candidate_id, error=str(e))
        raise self.retry(exc=e, countdown=30)
    finally:
        session.close()


def _format_skills_for_prompt(required_skills: list) -> str:
    """Format skills list for the prompt, handling both old (str) and new (dict) formats."""
    if not required_skills:
        return "Aucune competence specifiee"

    weight_labels = {1: "souhaitable", 2: "important", 3: "critique"}
    lines = []

    for skill in required_skills:
        if isinstance(skill, str):
            # Old format: plain string — use defaults
            lines.append(f"- {skill} (niveau requis: 3/5, poids: important) [technique]")
        elif isinstance(skill, dict):
            name = skill.get("name", "?")
            level = skill.get("level_required", 3)
            weight = skill.get("weight", 2)
            category = skill.get("category", "technique")
            weight_label = weight_labels.get(weight, "important")
            lines.append(f"- {name} (niveau requis: {level}/5, poids: {weight_label}) [{category}]")
        else:
            lines.append(f"- {skill}")

    return "\n".join(lines)


def _get_critical_skills(required_skills: list) -> list[str]:
    """Extract names of critical skills (weight=3) for emphasis in the prompt."""
    critical = []
    for skill in required_skills:
        if isinstance(skill, dict) and skill.get("weight", 2) == 3:
            critical.append(skill.get("name", "?"))
    return critical


def generate_interview_questions(candidate, position) -> list[dict]:
    from anthropic import Anthropic

    from app.core.config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    custom_questions = position.custom_questions or []
    cv_data = candidate.cv_parsed_data or {}
    required_skills = position.required_skills or []

    # Format skills with taxonomy details
    skills_formatted = _format_skills_for_prompt(required_skills)
    critical_skills = _get_critical_skills(required_skills)

    critical_instruction = ""
    if critical_skills:
        critical_instruction = (
            f"\n- Les competences critiques ({', '.join(critical_skills)}) "
            f"doivent avoir au moins 1 question dediee chacune."
        )

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": f"""Genere des questions d'entretien telephonique pour ce candidat.
L'entretien dure 5 minutes max, donc 4 a 6 questions.

FICHE DE POSTE:
- Titre: {position.title}
- Description: {position.description[:800]}
- Niveau: {position.seniority_level}

Competences requises (par priorite):
{skills_formatted}

CV DU CANDIDAT:
{json.dumps(cv_data, ensure_ascii=False)[:1500]}

QUESTIONS OBLIGATOIRES DU RECRUTEUR:
{json.dumps(custom_questions)}

REGLES:
- Questions ouvertes, pas de oui/non
- Adapte la difficulte au niveau du poste ({position.seniority_level})
- Mix: technique (2-3), experience (1-2), soft skills (1)
- Formulation naturelle en francais, pour conversation telephonique
- PAS de questions sur la personnalite, les emotions, ou les attributs personnels
- PAS de questions discriminatoires (age, famille, religion, etc.)
- Genere des questions qui evaluent chaque competence listee
- Pour chaque question, indique la competence ciblee dans le champ "target_skill"{critical_instruction}

Format JSON:
[
    {{
        "id": 1,
        "text": "la question en francais",
        "category": "technique|experience|soft_skills",
        "target_skill": "nom de la competence ciblee",
        "expected_duration_seconds": 45,
        "evaluation_criteria": "ce qu'on cherche dans la reponse"
    }}
]""",
            }
        ],
    )

    try:
        text_content = response.content[0].text
        if "```json" in text_content:
            text_content = text_content.split("```json")[1].split("```")[0]
        elif "```" in text_content:
            text_content = text_content.split("```")[1].split("```")[0]
        return json.loads(text_content.strip())
    except (json.JSONDecodeError, IndexError):
        # Fallback: basic questions
        return [
            {
                "id": 1,
                "text": f"Pouvez-vous me parler de votre experience en lien avec le poste de {position.title} ?",
                "category": "experience",
                "target_skill": "experience_generale",
                "expected_duration_seconds": 60,
                "evaluation_criteria": "Pertinence de l'experience",
            },
            {
                "id": 2,
                "text": "Quelles sont les competences techniques que vous maitrisez le mieux ?",
                "category": "technique",
                "target_skill": "competences_techniques",
                "expected_duration_seconds": 45,
                "evaluation_criteria": "Competences techniques",
            },
            {
                "id": 3,
                "text": "Pouvez-vous me donner un exemple de projet ou vous avez du collaborer avec une equipe ?",
                "category": "soft_skills",
                "target_skill": "collaboration",
                "expected_duration_seconds": 45,
                "evaluation_criteria": "Capacite de collaboration",
            },
        ]
