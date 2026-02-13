import json

import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(name="analysis.analyze", bind=True, max_retries=3)
def analyze_interview(self, interview_id: str):
    logger.info("analysis_start", interview_id=interview_id)

    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from uuid import UUID

        from sqlalchemy import select

        from app.models.analysis import Analysis
        from app.models.candidate import Candidate
        from app.models.interview import Interview
        from app.models.position import Position
        from app.models.transcription import Transcription

        interview = session.get(Interview, UUID(interview_id))
        if not interview:
            return

        trans_result = session.execute(
            select(Transcription).where(Transcription.interview_id == interview.id)
        )
        transcription = trans_result.scalar_one_or_none()
        if not transcription:
            logger.warning("analysis_skip_no_transcription", interview_id=interview_id)
            return

        candidate = session.get(Candidate, interview.candidate_id)
        position = session.get(Position, interview.position_id)

        analysis_result = run_analysis(transcription, position, candidate)

        analysis = Analysis(
            interview_id=interview.id,
            skills_extracted=analysis_result.get("skills_extracted"),
            experience_examples=analysis_result.get("experience_examples"),
            communication_indicators=analysis_result.get("communication_indicators"),
            scores=analysis_result.get("scores"),
            score_explanations=analysis_result.get("score_explanations"),
            skill_scores=analysis_result.get("skill_scores"),
        )
        session.add(analysis)

        candidate.pipeline_status = "evaluated"
        session.commit()

        logger.info("analysis_done", interview_id=interview_id)

        # Trigger report generation
        from app.workers.report_generation import generate_report

        generate_report.delay(interview_id)

    except Exception as e:
        session.rollback()
        logger.error("analysis_error", interview_id=interview_id, error=str(e))
        raise self.retry(exc=e, countdown=30)
    finally:
        session.close()


def _format_skills_for_prompt(required_skills: list | None) -> str:
    """Normalize required_skills to a prompt-friendly format.

    Handles both legacy list[str] and new list[{name, level_required, weight, category}].
    """
    if not required_skills:
        return "Aucune competence specifique listee."

    lines = []
    for skill in required_skills:
        if isinstance(skill, str):
            lines.append(f"- {skill}: niveau requis 3/5, poids 2, categorie technique")
        elif isinstance(skill, dict):
            name = skill.get("name", str(skill))
            level = skill.get("level_required", 3)
            weight = skill.get("weight", 2)
            cat = skill.get("category", "technique")
            lines.append(f"- {name}: niveau requis {level}/5, poids {weight}, categorie {cat}")
        else:
            lines.append(f"- {skill}: niveau requis 3/5, poids 2, categorie technique")
    return "\n".join(lines)


def _build_skill_scores_schema(required_skills: list | None) -> str:
    """Build the JSON schema example for skill_scores based on actual required skills."""
    if not required_skills:
        return "[]"

    examples = []
    for skill in required_skills[:2]:  # Show 2 examples max
        if isinstance(skill, str):
            name, level, cat = skill, 3, "technique"
        elif isinstance(skill, dict):
            name = skill.get("name", str(skill))
            level = skill.get("level_required", 3)
            cat = skill.get("category", "technique")
        else:
            name, level, cat = str(skill), 3, "technique"
        examples.append(
            f'        {{"skill": "{name}", "category": "{cat}", '
            f'"level_required": {level}, "demonstrated": 0, "motivation": 0, '
            f'"evidence": "...", "gap_analysis": "..."}}'
        )
    return "[\n" + ",\n".join(examples) + "\n    ]"


def run_analysis(transcription, position, candidate) -> dict:
    from anthropic import Anthropic

    from app.core.config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    cv_data = candidate.cv_parsed_data or {}
    segments = transcription.segments or {}

    # Format required skills with levels, weights, categories
    skills_prompt = _format_skills_for_prompt(position.required_skills)
    skill_scores_schema = _build_skill_scores_schema(position.required_skills)

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=4000,
        messages=[
            {
                "role": "user",
                "content": f"""Analyse cet entretien telephonique. Reponds UNIQUEMENT en JSON.

FICHE DE POSTE:
- Titre: {position.title}
- Niveau: {position.seniority_level}

Competences requises pour le poste:
{skills_prompt}

CV DU CANDIDAT:
{json.dumps(cv_data, ensure_ascii=False)[:1000]}

TRANSCRIPTION DE L'ENTRETIEN:
{transcription.full_text[:3000]}

SEGMENTS PAR QUESTION:
{json.dumps(segments, ensure_ascii=False)[:2000]}

INSTRUCTIONS D'ANALYSE:

1. COMPETENCES — Distingue clairement:
   - "Competences declarees" : le candidat affirme maitriser X mais sans donner d'exemple concret
   - "Competences demontrees" : le candidat fournit un exemple precis, une situation vecue, ou une explication technique qui prouve la maitrise
   Dans le champ "evidence", indique si c'est "declare" ou "demontre" avec la citation correspondante.

2. SCORING PAR COMPETENCE (DUAL-AXIS):
   Pour chaque competence requise listee ci-dessus, evalue DEUX axes:
   - "demonstrated" (1-5): Niveau reellement demontre dans la conversation, base sur des preuves concretes
   - "motivation" (1-5): Interet et volonte d'apprentissage/approfondissement detectes dans les reponses

   IMPORTANT:
   - Le score "demonstrated" doit etre justifie par des elements factuels de la transcription
   - Le score "motivation" se base sur: enthousiasme quand le sujet est aborde, projets personnels mentionnes, formation en cours, questions posees par le candidat
   - Si une competence n'a pas ete abordee, indiquer demonstrated=0 et motivation=0 avec evidence="Non aborde dans l'entretien"
   - NE PAS inferer la motivation a partir du ton de voix ou de l'attitude (pas observable dans une transcription)

3. EXEMPLES D'EXPERIENCE — Utilise la methode STAR:
   - Situation : quel etait le contexte ?
   - Task : quelle etait la responsabilite du candidat ?
   - Action : qu'a-t-il concretement fait ?
   - Result : quel a ete le resultat mesurable ?
   Si le candidat ne fournit pas tous les elements STAR, note explicitement les elements manquants.

4. COMMUNICATION — Evalue sur ces criteres UNIQUEMENT:
   - Completude des reponses : le candidat repond-il a la question posee de maniere complete ?
   - Exemples pertinents : fournit-il des exemples concrets et en lien avec la question ?
   - Clarte d'expression : les reponses sont-elles comprehensibles et bien structurees ?
   NE PAS evaluer : l'accent, la qualite vocale, le style de parole, la vitesse d'elocution.

5. QUESTIONS SANS REPONSE:
   Si une question n'a pas recu de reponse, ou si la reponse est trop breve/hors-sujet, note-le EXPLICITEMENT
   dans score_explanations plutot que de simplement attribuer un score bas sans explication.

REGLES STRICTES (GUARDRAILS):
- Analyse basee UNIQUEMENT sur les signaux observables dans les reponses
- PAS d'inference de personnalite, d'emotion ou de motivation subjective
- PAS de recommandation d'embauche (l'IA assiste, l'humain decide)
- PAS d'inference d'attributs proteges (genre, age, origine, etc.)
- Chaque score DOIT etre justifie par des elements factuels de la transcription
- Les indicateurs de communication mesurent: clarte, structure, fluidite (PAS les emotions)

Format JSON:
{{
    "skill_scores": {skill_scores_schema},
    "skills_extracted": [
        {{"skill": "nom", "evidence": "citation ou element de la transcription", "level": "debutant|intermediaire|avance", "type": "declare|demontre"}}
    ],
    "experience_examples": [
        {{"situation": "contexte decrit", "task": "responsabilite", "action": "ce que le candidat a fait", "result": "resultat mentionne", "missing_star_elements": ["element manquant si applicable"]}}
    ],
    "communication_indicators": {{
        "clarity": {{"score": 75, "evidence": "..."}},
        "structure": {{"score": 70, "evidence": "..."}},
        "fluency": {{"score": 80, "evidence": "..."}}
    }},
    "scores": {{
        "technical": 70,
        "experience": 75,
        "communication": 75,
        "global": 73
    }},
    "score_explanations": {{
        "technical": "justification basee sur les reponses...",
        "experience": "justification...",
        "communication": "justification...",
        "global": "moyenne ponderee expliquee...",
        "unanswered_questions": ["question X: pas de reponse fournie"]
    }}
}}

IMPORTANT: Le champ "skill_scores" doit contenir une entree pour CHAQUE competence requise listee ci-dessus, avec les champs:
- "skill": nom de la competence (identique a celui de la liste ci-dessus)
- "category": categorie (technique, soft_skills, outils, etc.)
- "level_required": le niveau requis tel qu'indique
- "demonstrated": niveau demontre (0-5, 0 = non aborde)
- "motivation": motivation detectee (0-5, 0 = non aborde)
- "evidence": preuves concretes extraites de la transcription
- "gap_analysis": analyse de l'ecart entre requis et demontre""",
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
        return {
            "scores": {"technical": 0, "experience": 0, "communication": 0, "global": 0},
            "score_explanations": {"error": "Analysis failed"},
        }
