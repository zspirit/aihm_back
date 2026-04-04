"""Service de generation du resume candidat 30 secondes.

Genere un resume concis d'un candidat via Claude, lisible en 30 secondes
par un recruteur. Combine les donnees CV, scores, entretien et analyse.

Regles guardrails AIHM :
- PAS d'inference de personnalite ou de traits psychologiques
- PAS de recommandation d'embauche definitive
- Evaluation basee UNIQUEMENT sur des elements factuels
"""

import json
import re
from datetime import datetime, timezone

import structlog
from anthropic import Anthropic

from app.core.config import get_settings

logger = structlog.get_logger()


SUMMARY_PROMPT_TEMPLATE = """Tu es un assistant specialise en recrutement. Tu dois produire un resume concis d'un candidat, lisible en 30 secondes par un recruteur.

REGLES STRICTES :
- Base ton analyse UNIQUEMENT sur des elements factuels fournis
- PAS d'inference de personnalite ou de traits psychologiques
- La recommandation est un AVIS pour aider le recruteur, PAS une decision
- Sois concis et percutant : le recruteur doit tout comprendre en 30 secondes

DONNEES CANDIDAT :
{candidate_data_json}

Produis un resume au format JSON strict (sans markdown, juste le JSON brut) :

{{
  "pitch": "Resume du profil en 1-2 phrases percutantes (qui est ce candidat, son experience cle, sa valeur ajoutee)",
  "strengths": ["Point fort 1 (factuel et concret)", "Point fort 2", "Point fort 3 max"],
  "concerns": ["Point d'attention 1 (factuel)", "Point d'attention 2 max"],
  "overall_score": 0,
  "recommendation": "go | no_go | to_deepen"
}}

Regles pour chaque champ :
- pitch : 1-2 phrases max, percutantes, factuelles. Mentionne le niveau d'experience et le domaine.
- strengths : 3 points forts max, chacun en 1 phrase courte. Bases sur des faits (competences demontrees, annees d'experience, realisations).
- concerns : 2 points d'attention max. Bases sur des lacunes factuelles (pas de speculation). Si aucun, tableau vide.
- overall_score : score de 0 a 100 base sur l'ensemble des donnees disponibles. Si seul le CV est disponible, se baser sur le score CV/profil. Si un entretien a ete realise, ponderer fortement le resultat d'entretien.
- recommendation :
  - "go" : candidat solide, profil coherent, pas de signal d'alerte majeur
  - "no_go" : lacunes significatives par rapport aux attentes ou signaux d'alerte
  - "to_deepen" : profil interessant mais necessitant des verifications complementaires

Reponds UNIQUEMENT avec le JSON brut, sans texte avant ou apres."""


def _build_candidate_data(candidate, position, interview, analysis) -> dict:
    """Construit le dictionnaire de donnees candidat pour le prompt."""
    data = {}

    # Donnees CV
    cv = candidate.get("cv_parsed_data") or {}
    data["cv"] = {
        "name": candidate.get("name", "Inconnu"),
        "summary": cv.get("summary", ""),
        "skills": cv.get("skills", []),
        "experience_years": cv.get("experience_years"),
        "experiences": cv.get("experiences", cv.get("experience", [])),
        "education": cv.get("education", []),
        "languages": cv.get("languages", []),
    }

    # Scores
    data["scores"] = {
        "cv_score": candidate.get("cv_score"),
        "profile_score": candidate.get("profile_score"),
    }

    # Position (si disponible)
    if position:
        data["position"] = {
            "title": position.get("title", ""),
            "required_skills": position.get("required_skills", []),
            "seniority_level": position.get("seniority_level", ""),
        }

    # Entretien (si disponible)
    if interview:
        data["interview"] = {
            "status": interview.get("status", ""),
            "duration_seconds": interview.get("duration_seconds"),
            "questions_asked": interview.get("questions_asked"),
        }

    # Analyse entretien (si disponible)
    if analysis:
        data["analysis"] = {
            "scores": analysis.get("scores"),
            "skills_extracted": analysis.get("skills_extracted"),
            "communication_indicators": analysis.get("communication_indicators"),
            "score_explanations": analysis.get("score_explanations"),
        }

    return data


def generate_candidate_summary(
    candidate: dict,
    position: dict | None = None,
    interview: dict | None = None,
    analysis: dict | None = None,
) -> dict:
    """Genere un resume 30 secondes d'un candidat via Claude.

    Appel SYNCHRONE a Claude - a wrapper dans run_in_threadpool pour FastAPI async.

    Args:
        candidate: Donnees du candidat (dict avec name, cv_parsed_data, cv_score, etc.)
        position: Donnees du poste (optionnel)
        interview: Donnees de l'entretien (optionnel)
        analysis: Donnees de l'analyse entretien (optionnel)

    Returns:
        dict avec pitch, strengths, concerns, overall_score, recommendation, generated_at

    Raises:
        ValueError: Si la reponse Claude n'est pas du JSON valide
        Exception: Si l'appel Claude echoue
    """
    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    candidate_data = _build_candidate_data(candidate, position, interview, analysis)

    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        candidate_data_json=json.dumps(candidate_data, ensure_ascii=False, indent=2)
    )

    logger.info(
        "generate_candidate_summary_start",
        candidate_name=candidate.get("name"),
        has_interview=interview is not None,
        has_analysis=analysis is not None,
    )

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1000,
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
            "generate_candidate_summary_json_error",
            error=str(e),
            raw_response=text_content[:500],
        )
        raise ValueError(f"Reponse Claude non parseable: {e}") from e

    # Validation et normalisation
    result["pitch"] = result.get("pitch", "Resume non disponible")
    result["strengths"] = result.get("strengths", [])[:3]
    result["concerns"] = result.get("concerns", [])[:2]

    if "overall_score" in result:
        result["overall_score"] = float(result["overall_score"])
    else:
        result["overall_score"] = 0.0

    recommendation = result.get("recommendation", "to_deepen")
    if recommendation not in ("go", "no_go", "to_deepen"):
        recommendation = "to_deepen"
    result["recommendation"] = recommendation

    result["generated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info(
        "generate_candidate_summary_done",
        candidate_name=candidate.get("name"),
        overall_score=result["overall_score"],
        recommendation=result["recommendation"],
    )

    return result
