"""Service de generation du feedback candidat post-evaluation.

Genere un feedback structure via Claude a destination du candidat :
points forts, axes d'amelioration, conseils concrets.

Regles guardrails AIHM :
- PAS d'inference de personnalite ou de traits psychologiques
- Feedback base UNIQUEMENT sur des elements factuels
- Ton bienveillant et constructif
"""

import json
import re
from datetime import datetime, timezone

import structlog
from anthropic import Anthropic

from app.core.config import get_settings

logger = structlog.get_logger()


FEEDBACK_PROMPT_TEMPLATE = """Tu es un assistant specialise en recrutement. Tu dois produire un feedback constructif et bienveillant pour un candidat apres son evaluation.

REGLES STRICTES :
- Base ton feedback UNIQUEMENT sur des elements factuels fournis
- PAS d'inference de personnalite ou de traits psychologiques
- Ton bienveillant, encourageant et constructif
- Conseils concrets et actionnables
- Ne mentionne JAMAIS de score numerique au candidat
- Ne mentionne JAMAIS la decision interne (go/no_go/to_deepen)

DONNEES CANDIDAT :
{candidate_data_json}

Produis un feedback au format JSON strict (sans markdown, juste le JSON brut) :

{{
  "greeting": "Message d'accueil personnalise (1 phrase, mentionne le poste)",
  "strengths": [
    {{
      "title": "Titre du point fort",
      "detail": "Explication factuelle en 1-2 phrases"
    }}
  ],
  "improvements": [
    {{
      "title": "Titre de l'axe d'amelioration",
      "detail": "Explication factuelle en 1-2 phrases",
      "advice": "Conseil concret et actionnable"
    }}
  ],
  "general_advice": "Conseil general pour la suite de la carriere (2-3 phrases max)",
  "closing": "Message de conclusion encourageant (1 phrase)"
}}

Regles pour chaque champ :
- greeting : personnalise avec le prenom et le poste vise
- strengths : 2-4 points forts, bases sur des faits (competences, experience, entretien)
- improvements : 1-3 axes d'amelioration, chacun avec un conseil actionnable. Pas de critique negative, formuler en "piste de progression"
- general_advice : conseils pratiques pour progresser
- closing : encourageant, professionnel

Reponds UNIQUEMENT avec le JSON brut, sans texte avant ou apres."""


def _build_feedback_data(candidate: dict, position: dict | None, analysis: dict | None) -> dict:
    """Construit le dictionnaire de donnees pour le prompt feedback."""
    data = {}

    cv = candidate.get("cv_parsed_data") or {}
    data["candidate"] = {
        "name": candidate.get("name", "Candidat"),
        "skills": cv.get("skills", []),
        "experience_years": cv.get("experience_years"),
        "experiences": cv.get("experiences", cv.get("experience", [])),
        "education": cv.get("education", []),
        "languages": cv.get("languages", []),
    }

    data["scores"] = {
        "cv_score": candidate.get("cv_score"),
        "profile_score": candidate.get("profile_score"),
    }

    if position:
        data["position"] = {
            "title": position.get("title", ""),
            "required_skills": position.get("required_skills", []),
        }

    if analysis:
        data["interview_analysis"] = {
            "scores": analysis.get("scores"),
            "skills_extracted": analysis.get("skills_extracted"),
            "communication_indicators": analysis.get("communication_indicators"),
            "score_explanations": analysis.get("score_explanations"),
        }

    return data


def generate_candidate_feedback(
    candidate: dict,
    position: dict | None = None,
    analysis: dict | None = None,
) -> dict:
    """Genere un feedback candidat via Claude.

    Appel SYNCHRONE a Claude - a wrapper dans run_in_threadpool pour FastAPI async.

    Args:
        candidate: Donnees du candidat (dict)
        position: Donnees du poste (optionnel)
        analysis: Donnees de l'analyse entretien (optionnel)

    Returns:
        dict avec greeting, strengths, improvements, general_advice, closing, generated_at

    Raises:
        ValueError: Si la reponse Claude n'est pas du JSON valide
        Exception: Si l'appel Claude echoue
    """
    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    feedback_data = _build_feedback_data(candidate, position, analysis)

    prompt = FEEDBACK_PROMPT_TEMPLATE.format(
        candidate_data_json=json.dumps(feedback_data, ensure_ascii=False, indent=2)
    )

    logger.info(
        "generate_candidate_feedback_start",
        candidate_name=candidate.get("name"),
        has_analysis=analysis is not None,
    )

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    text_content = response.content[0].text.strip()

    # Nettoyage des eventuels wrappers markdown
    if "```json" in text_content:
        text_content = text_content.split("```json")[1].split("```")[0].strip()
    elif "```" in text_content:
        text_content = text_content.split("```")[1].split("```")[0].strip()

    # Extraire le JSON si du texte le precede
    json_match = re.search(r'\{[\s\S]*\}', text_content)
    if json_match:
        text_content = json_match.group(0)

    try:
        result = json.loads(text_content)
    except json.JSONDecodeError as e:
        logger.error(
            "generate_candidate_feedback_json_error",
            error=str(e),
            raw_response=text_content[:500],
        )
        raise ValueError(f"Reponse Claude non parseable: {e}") from e

    # Validation et normalisation
    result["greeting"] = result.get("greeting", "Bonjour,")
    result["strengths"] = result.get("strengths", [])[:4]
    result["improvements"] = result.get("improvements", [])[:3]
    result["general_advice"] = result.get("general_advice", "")
    result["closing"] = result.get("closing", "Nous vous souhaitons bonne continuation.")
    result["generated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info(
        "generate_candidate_feedback_done",
        candidate_name=candidate.get("name"),
        strengths_count=len(result["strengths"]),
        improvements_count=len(result["improvements"]),
    )

    return result
