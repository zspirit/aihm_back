"""Service de calcul du profil intrinseque d'un candidat.

Ce module appelle Claude pour extraire les competences, calculer un score
intrinseque (pas lie a un poste), et produire des suggestions d'amelioration CV.

Regles guardrails AIHM :
- PAS d'inference de personnalite ou de traits psychologiques
- PAS de recommandation d'embauche
- Evaluation basee UNIQUEMENT sur des elements factuels du CV
- Scores explicables et traces
"""

import json
import re

import structlog
from anthropic import Anthropic

from app.core.config import get_settings

logger = structlog.get_logger()


PROFILE_PROMPT_TEMPLATE = """Tu es un assistant specialise en analyse de CV. Tu dois analyser les donnees extraites d'un CV et produire une evaluation structuree et factuelle.

REGLES STRICTES :
- Base ton analyse UNIQUEMENT sur des elements factuels presents dans le CV
- PAS d'inference de personnalite, caracteristiques psychologiques ou traits de caractere
- PAS de recommandation d'embauche ou de rejet
- Chaque score doit etre explique avec des elements concrets et tracables
- Les niveaux de competences doivent etre justifies par des preuves tangibles (annees d'experience, projets, roles)
- En cas de donnees insuffisantes, indiquer clairement les lacunes sans speculer

DONNEES DU CV :
{cv_data_json}

Produis une evaluation complete au format JSON strict (sans markdown, juste le JSON brut) :

{{
  "competencies": {{
    "technical": [
      {{
        "name": "nom de la competence",
        "level": 1-5,
        "normalized": "nom_normalise_minuscules",
        "demonstrated": true,
        "evidence": "justification factuelle : projet X, role Y, duree Z"
      }}
    ],
    "experience": [
      {{
        "title": "intitule du poste",
        "company": "entreprise",
        "duration_months": 0,
        "responsibilities": ["responsabilite 1", "responsabilite 2"],
        "key_achievements": ["realisation concrete 1 avec chiffres si disponibles"]
      }}
    ],
    "education": [
      {{
        "degree": "diplome",
        "field": "domaine",
        "institution": "etablissement",
        "year": 0
      }}
    ],
    "languages": [
      {{
        "name": "langue",
        "level": "natif | courant | professionnel | scolaire"
      }}
    ],
    "soft_skills": ["competence comportementale observable 1", "competence comportementale observable 2"]
  }},
  "profile_score": 0,
  "score_explanation": {{
    "overall": "synthese factuelle du profil en 2-3 phrases",
    "breakdown": {{
      "technical_depth": {{
        "score": 0,
        "detail": "justification factuelle du score technique"
      }},
      "experience_quality": {{
        "score": 0,
        "detail": "justification factuelle de la qualite de l'experience"
      }},
      "education_relevance": {{
        "score": 0,
        "detail": "justification factuelle de la pertinence de la formation"
      }},
      "cv_completeness": {{
        "score": 0,
        "detail": "evaluation de la completude et structure du CV"
      }}
    }}
  }},
  "suggestions": [
    {{
      "category": "impact | skills | structure | education | languages | missing_info",
      "priority": "high | medium | low",
      "suggestion": "recommandation concrete et actionnable pour ameliorer le CV"
    }}
  ],
  "cv_quality_score": 0,
  "cv_quality_details": {{
    "completeness": 0,
    "clarity": 0,
    "impact": 0,
    "consistency": 0
  }}
}}

Notes pour le calcul des scores (tous de 0 a 100) :
- profile_score : score global intrinseque du profil (moyenne ponderee des 4 dimensions)
  - technical_depth (40%) : profondeur et diversite des competences techniques demontrees
  - experience_quality (35%) : progression de carriere, duree, responsabilites, realisations chiffrees
  - education_relevance (15%) : adequation de la formation au domaine professionnel
  - cv_completeness (10%) : completude, clarte et structure du document

- cv_quality_score : qualite du document CV lui-meme (independante du profil)
  - completeness : presence de toutes les sections importantes
  - clarity : clarte de la redaction et de la mise en forme
  - impact : presence de chiffres, resultats concrets
  - consistency : coherence chronologique et de presentation

Pour les niveaux de competences techniques (1-5) :
1 = Notions de base / expose uniquement
2 = Pratique supervisee (< 1 an)
3 = Autonomie partielle (1-3 ans)
4 = Maitrise (3-5 ans ou expertise reconnue)
5 = Expert confirmé (5+ ans, formation/publication/architecture)

Reponds UNIQUEMENT avec le JSON brut, sans texte avant ou apres."""


def compute_candidate_profile(cv_parsed_data: dict) -> dict:
    """Calcule le profil intrinseque d'un candidat a partir de son CV parse.

    Appel SYNCHRONE a Claude - a wrapper dans run_in_threadpool pour FastAPI async.

    Args:
        cv_parsed_data: Donnees extraites du CV (skills, experience, education, languages, summary)

    Returns:
        dict avec competencies, profile_score, score_explanation, suggestions,
        cv_quality_score, cv_quality_details

    Raises:
        ValueError: Si la reponse Claude n'est pas du JSON valide
        Exception: Si l'appel Claude echoue
    """
    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Formater les donnees CV proprement pour le prompt
    cv_data_formatted = {
        "summary": cv_parsed_data.get("summary", ""),
        "skills": cv_parsed_data.get("skills", []),
        "experience_years": cv_parsed_data.get("experience_years"),
        "experience": cv_parsed_data.get("experience", []),
        "education": cv_parsed_data.get("education", []),
        "languages": cv_parsed_data.get("languages", []),
        "certifications": cv_parsed_data.get("certifications", []),
        "location": cv_parsed_data.get("location", ""),
    }

    prompt = PROFILE_PROMPT_TEMPLATE.format(
        cv_data_json=json.dumps(cv_data_formatted, ensure_ascii=False, indent=2)
    )

    logger.info("compute_candidate_profile_start", skills_count=len(cv_data_formatted["skills"]))

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=4000,
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

    # Si le contenu commence par du texte avant le JSON, extraire le JSON
    json_match = re.search(r'\{[\s\S]*\}', text_content)
    if json_match:
        text_content = json_match.group(0)

    try:
        result = json.loads(text_content)
    except json.JSONDecodeError as e:
        logger.error(
            "compute_candidate_profile_json_error",
            error=str(e),
            raw_response=text_content[:500],
        )
        raise ValueError(f"Reponse Claude non parseable: {e}") from e

    # Validation basique de la structure
    required_keys = ["competencies", "profile_score", "score_explanation", "suggestions"]
    for key in required_keys:
        if key not in result:
            logger.warning("compute_candidate_profile_missing_key", key=key)

    # Assurer que profile_score est un float
    if "profile_score" in result:
        result["profile_score"] = float(result["profile_score"])

    # Assurer que cv_quality_score est un float
    if "cv_quality_score" in result:
        result["cv_quality_score"] = float(result["cv_quality_score"])

    logger.info(
        "compute_candidate_profile_done",
        profile_score=result.get("profile_score"),
        technical_count=len(result.get("competencies", {}).get("technical", [])),
        suggestions_count=len(result.get("suggestions", [])),
    )

    return result
