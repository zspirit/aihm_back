import json

import structlog
from celery import shared_task

from app.workers.base import worker_task

logger = structlog.get_logger()


@shared_task(name="questions.generate", bind=True, max_retries=3)
def generate_questions(self, candidate_id: str):
    with worker_task("question_generation", self, candidate_id=candidate_id) as ctx:
        from uuid import UUID

        from app.models.candidate import Candidate
        from app.models.position import Position

        session = ctx.session
        candidate = session.get(Candidate, UUID(candidate_id))
        if not candidate:
            return

        position = session.get(Position, candidate.position_id)
        if not position:
            logger.error("position_not_found", position_id=str(candidate.position_id))
            return

        questions = generate_interview_questions(candidate, position)

        logger.info(
            "question_generation_done",
            candidate_id=candidate_id,
            question_count=len(questions),
        )

        session.commit()
        return questions


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

    # System prompt: persona Léa, ton conversationnel, conformité EU AI Act.
    # Séparé du user message pour que Claude internalise la persona avant
    # d'analyser les données du candidat. Le ton vise un naturel chaleureux
    # qui réduit le perçu "robot" tout en restant pro et neutre.
    system_prompt = """Tu es Léa, recruteuse IA qui mène un entretien téléphonique pré-qualification.

PERSONA & TON :
- Chaleureuse, professionnelle, à l'écoute. Ton humain et bienveillant.
- Tu poses des questions ouvertes, pas des interrogatoires.
- Tu reformules avec tes propres mots, jamais en mode "questionnaire à puces".
- Tu utilises des transitions naturelles entre les sujets ("D'accord, parlons maintenant de…", "Intéressant, on enchaîne sur…", "Très bien, dernière question").

CONFORMITÉ EU AI ACT (Art. 50 — transparence) :
- Le candidat sait déjà qu'il parle à une IA (annoncé en intro de l'appel).
- Tes questions ne doivent JAMAIS prétendre être humaines ou émotionnellement empathiques au-delà du raisonnable. Évite "je comprends ce que vous ressentez", "ça doit être difficile". Reste analytique mais chaleureuse.

QUALITÉ DES QUESTIONS :
- Phrases courtes (<25 mots si possible), faciles à comprendre à l'oral.
- Une seule question à la fois — pas de "et aussi… et puis…".
- Concrètes : demande des exemples, des projets, des situations vécues, pas des opinions générales.
- Adaptées au niveau du poste et au profil du candidat (regarde son CV).

INTERDITS LÉGAUX :
- AUCUNE question sur la personnalité, les émotions intimes, les attributs personnels.
- AUCUNE question discriminatoire (âge, famille, religion, origine, santé, orientation, etc.).
- Reste strictement sur les compétences, l'expérience, et les soft skills professionnels.

FORMAT DE SORTIE :
Tu retournes EXACTEMENT un JSON array, sans commentaire avant/après, structuré comme indiqué."""

    user_message = f"""Génère des questions d'entretien téléphonique pour ce candidat.
L'entretien dure 5 minutes max, donc exactement 3 questions.

FICHE DE POSTE :
- Titre : {position.title}
- Description : {position.description[:800]}
- Niveau : {position.seniority_level}

Compétences requises (par priorité) :
{skills_formatted}

CV DU CANDIDAT :
{json.dumps(cv_data, ensure_ascii=False)[:1500]}

QUESTIONS OBLIGATOIRES DU RECRUTEUR :
{json.dumps(custom_questions)}

CONSIGNES SUPPLÉMENTAIRES :
- Mix recommandé : 2 questions techniques, 1 expérience/soft skills.
- Pour chaque question, indique la compétence ciblée dans `target_skill`.
- Formulation : pense "conversation entre deux pros au téléphone", pas "questionnaire d'évaluation".{critical_instruction}

Format JSON (rien d'autre dans ta réponse) :
[
    {{
        "id": 1,
        "text": "la question, formulée naturellement, comme tu la dirais à l'oral",
        "category": "technique|experience|soft_skills",
        "target_skill": "nom de la competence ciblee",
        "expected_duration_seconds": 45,
        "evaluation_criteria": "ce que tu cherches à évaluer dans la réponse"
    }}
]"""

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1500,
        timeout=60.0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
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
