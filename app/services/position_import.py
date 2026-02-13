import json

import structlog
from anthropic import Anthropic

from app.core.config import get_settings

logger = structlog.get_logger()


def extract_position_from_text(text: str) -> dict:
    """
    Use Claude to extract structured position data from raw job description text.
    """
    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": f"""Extrais les informations structurees de cette offre d'emploi. Reponds UNIQUEMENT en JSON valide.

OFFRE D'EMPLOI:
{text[:4000]}

Format JSON attendu:
{{
    "title": "titre du poste",
    "description": "description complete du poste et des missions",
    "required_skills": ["competence1", "competence2", "competence3"],
    "seniority_level": "junior|mid|senior",
    "custom_questions": [
        "question d'entretien pertinente 1",
        "question d'entretien pertinente 2",
        "question d'entretien pertinente 3"
    ]
}}

REGLES:
- required_skills: liste de 4 a 8 competences cles extraites du texte
- seniority_level: deduis le niveau en fonction de l'experience demandee (0-2 ans = junior, 2-5 ans = mid, 5+ ans = senior)
- custom_questions: genere 3 a 5 questions d'entretien pertinentes en francais basees sur le poste
- Si une information n'est pas disponible, utilise des valeurs par defaut raisonnables""",
            }
        ],
    )

    try:
        text_content = response.content[0].text
        # Extract JSON from response
        if "```json" in text_content:
            text_content = text_content.split("```json")[1].split("```")[0]
        elif "```" in text_content:
            text_content = text_content.split("```")[1].split("```")[0]

        result = json.loads(text_content.strip())

        # Validate and provide defaults
        if "title" not in result or not result["title"]:
            result["title"] = "Poste sans titre"
        if "description" not in result:
            result["description"] = text[:500]
        if "required_skills" not in result or not isinstance(result["required_skills"], list):
            result["required_skills"] = []
        if "seniority_level" not in result or result["seniority_level"] not in ["junior", "mid", "senior"]:
            result["seniority_level"] = "mid"
        if "custom_questions" not in result or not isinstance(result["custom_questions"], list):
            result["custom_questions"] = []

        logger.info("position_import_success", title=result["title"])
        return result
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logger.error("position_import_error", error=str(e))
        # Fallback response
        return {
            "title": "Poste importe",
            "description": text[:1000],
            "required_skills": [],
            "seniority_level": "mid",
            "custom_questions": [],
        }
