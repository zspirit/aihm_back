import json

import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(name="report.generate", bind=True, max_retries=3)
def generate_report(self, interview_id: str):
    logger.info("report_generation_start", interview_id=interview_id)

    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from uuid import UUID

        from sqlalchemy import select

        from app.models.analysis import Analysis
        from app.models.candidate import Candidate
        from app.models.interview import Interview
        from app.models.position import Position
        from app.models.report import Report
        from app.models.transcription import Transcription

        interview = session.get(Interview, UUID(interview_id))
        if not interview:
            return

        candidate = session.get(Candidate, interview.candidate_id)
        position = session.get(Position, interview.position_id)

        analysis_result = session.execute(
            select(Analysis).where(Analysis.interview_id == interview.id)
        )
        analysis = analysis_result.scalar_one_or_none()

        trans_result = session.execute(
            select(Transcription).where(Transcription.interview_id == interview.id)
        )
        transcription = trans_result.scalar_one_or_none()

        report_content = build_report(candidate, position, interview, analysis, transcription)

        pdf_path = _generate_and_upload_pdf(report_content, interview_id)

        report = Report(
            candidate_id=candidate.id,
            interview_id=interview.id,
            content=report_content,
            pdf_file_path=pdf_path,
        )
        session.add(report)
        session.commit()

        logger.info("report_generation_done", interview_id=interview_id, pdf_path=pdf_path)

        # Trigger report-ready email notification
        try:
            from app.workers.notifications import send_report_ready

            send_report_ready.delay(str(interview.id))
            logger.info("report_ready_email_triggered", interview_id=interview_id)
        except Exception as e:
            logger.warning("report_ready_email_trigger_failed", interview_id=interview_id, error=str(e))

        # Cleanup audio file from MinIO (no longer needed after report is generated)
        _cleanup_audio(interview)

    except Exception as e:
        session.rollback()
        logger.error("report_generation_error", interview_id=interview_id, error=str(e))
        raise self.retry(exc=e, countdown=30)
    finally:
        session.close()


def _generate_and_upload_pdf(content: dict, interview_id: str) -> str | None:
    """Generate PDF and upload to MinIO. Returns the file path or None on error."""
    try:
        from app.core.config import get_settings
        from app.services.pdf_report import generate_pdf
        from app.services.storage import ensure_bucket, s3_client

        settings = get_settings()
        pdf_bytes = generate_pdf(content)

        bucket = settings.S3_BUCKET_REPORTS
        ensure_bucket(bucket)
        key = f"{interview_id}.pdf"
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        logger.info("pdf_uploaded", bucket=bucket, key=key, size=len(pdf_bytes))
        return f"{bucket}/{key}"
    except Exception as e:
        logger.warning("pdf_generation_failed", interview_id=interview_id, error=str(e))
        return None


def _cleanup_audio(interview):
    """Delete audio file from MinIO after report generation is complete."""
    if not interview.audio_file_path:
        return
    try:
        from app.services.storage import delete_file

        delete_file(interview.audio_file_path)
        logger.info("audio_file_cleaned_up", audio_path=interview.audio_file_path)
    except Exception as e:
        # Non-critical: log warning but don't fail the pipeline
        logger.warning("audio_cleanup_failed", audio_path=interview.audio_file_path, error=str(e))


def _compute_matching_score(skill_scores: list, required_skills: list | None) -> int:
    """Compute weighted matching score: sum(min(demonstrated/required, 1) * weight) / sum(weight) * 100.

    Handles both legacy list[str] and new list[{name, level_required, weight, category}].
    Returns an integer 0-100.
    """
    if not skill_scores:
        return 0

    # Build weight lookup from required_skills
    weight_lookup = {}
    for skill in (required_skills or []):
        if isinstance(skill, dict):
            name = skill.get("name", "")
            weight_lookup[name.lower()] = skill.get("weight", 2)

    total_weighted = 0.0
    total_weight = 0.0
    for ss in skill_scores:
        required = ss.get("level_required", 3)
        demonstrated = ss.get("demonstrated", 0)
        skill_name = ss.get("skill", "")
        weight = weight_lookup.get(skill_name.lower(), 2)

        if required > 0:
            ratio = min(demonstrated / required, 1.0)
        else:
            ratio = 1.0 if demonstrated > 0 else 0.0

        total_weighted += ratio * weight
        total_weight += weight

    if total_weight == 0:
        return 0
    return round(total_weighted / total_weight * 100)


def _build_skill_matrix_for_prompt(skill_scores: list | None) -> str:
    """Format skill_scores into a readable section for the report prompt."""
    if not skill_scores:
        return "Aucune donnee de scoring par competence disponible."

    lines = ["MATRICE DE COMPETENCES (issue de l'analyse):"]
    for ss in skill_scores:
        skill = ss.get("skill", "?")
        cat = ss.get("category", "?")
        req = ss.get("level_required", "?")
        dem = ss.get("demonstrated", "?")
        mot = ss.get("motivation", "?")
        ev = ss.get("evidence", "")
        lines.append(
            f"- {skill} [{cat}]: requis={req}/5, demontre={dem}/5, "
            f"motivation={mot}/5 | {ev[:80]}"
        )
    return "\n".join(lines)


def build_report(candidate, position, interview, analysis, transcription) -> dict:
    from anthropic import Anthropic

    from app.core.config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    analysis_data = {}
    skill_scores = None
    if analysis:
        analysis_data = {
            "scores": analysis.scores,
            "score_explanations": analysis.score_explanations,
            "skills_extracted": analysis.skills_extracted,
            "experience_examples": analysis.experience_examples,
            "communication_indicators": analysis.communication_indicators,
        }
        skill_scores = getattr(analysis, "skill_scores", None)

    # Compute matching_score from skill_scores if available
    matching_score = _compute_matching_score(skill_scores, position.required_skills) if skill_scores else None

    # Build skill matrix section for prompt
    skill_matrix_prompt = _build_skill_matrix_for_prompt(skill_scores)

    # Build skill_matrix JSON schema hint
    skill_matrix_schema = ""
    if skill_scores:
        skill_matrix_schema = """
    "skill_matrix": [
        {"skill": "...", "category": "...", "required": 4, "demonstrated": 3, "motivation": 4, "evidence": "resume court de la preuve"}
    ],
    "matching_score": """ + str(matching_score) + ","
    else:
        skill_matrix_schema = ""

    transcription_text = ""
    if transcription and transcription.full_text:
        transcription_text = transcription.full_text[:2000]

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=3000,
        messages=[
            {
                "role": "user",
                "content": f"""Genere un rapport d'evaluation structure pour ce candidat.
Le rapport doit etre professionnel, factuel, et imprimable.

CANDIDAT: {candidate.name}
POSTE: {position.title} ({position.seniority_level})
DUREE ENTRETIEN: {interview.duration_seconds or 0} secondes
DATE: {interview.ended_at or interview.created_at}

ANALYSE:
{json.dumps(analysis_data, ensure_ascii=False)[:2500]}

{skill_matrix_prompt}

TRANSCRIPTION (extraits):
{transcription_text}

INSTRUCTIONS DE REDACTION:

1. SYNTHESE: Redige un resume de 3-4 phrases qu'un recruteur presse peut scanner en 10 secondes.
   Le resume doit contenir: le score global, le matching_score (si disponible), les 1-2 points forts principaux, et le point d'attention principal.

2. MATRICE DE COMPETENCES: Si des donnees de scoring par competence sont disponibles ci-dessus,
   inclus le champ "skill_matrix" dans le JSON de sortie. Chaque entree doit contenir:
   - skill, category, required (niveau requis), demonstrated (niveau demontre), motivation, evidence (resume court)
   Le champ "matching_score" est pre-calcule a {matching_score if matching_score is not None else "N/A"} — utilise cette valeur directement.

3. POINTS FORTS: Chaque point fort DOIT referencer un moment precis de l'entretien.
   Mauvais exemple: "Bonne maitrise de Python"
   Bon exemple: "Maitrise de Python demontree en expliquant la mise en place d'un pipeline de donnees avec pandas et SQLAlchemy pour son ancien employeur"

4. POINTS A APPROFONDIR: Formule-les comme des questions pour un entretien de suivi, PAS comme des faiblesses.
   Mauvais exemple: "Faible en gestion de projet"
   Bon exemple: "Comment gerez-vous la priorisation quand plusieurs projets ont des deadlines concurrentes ?"

5. VERBATIMS: Inclus 2-3 citations cles directement extraites de la transcription qui representent le mieux les reponses du candidat.
   Choisis des citations qui illustrent des competences ou experiences concretes.

REGLES STRICTES:
- Aucune recommandation d'embauche (PAS de "nous recommandons", "ce candidat devrait etre...")
- Base uniquement sur des signaux observables
- PAS d'inference de personnalite ou d'emotion
- Le rapport INFORME, le recruteur DECIDE

Format JSON:
{{
    "title": "Rapport d'evaluation - [Nom candidat]",
    "position": "{position.title}",
    "date": "...",
    "summary": "Resume en 3-4 phrases des points cles, factuel",{skill_matrix_schema}
    "scores": {{
        "global": 0,
        "technical": 0,
        "experience": 0,
        "communication": 0
    }},
    "strengths": [
        "Point fort 1 avec evidence specifique de l'entretien",
        "Point fort 2 avec evidence specifique de l'entretien"
    ],
    "areas_to_explore": [
        "Question de suivi 1 formulee comme question",
        "Question de suivi 2 formulee comme question"
    ],
    "skills_assessment": [
        {{"skill": "...", "level": "...", "evidence": "..."}}
    ],
    "key_quotes": [
        "Citation verbatim 1 extraite de la transcription",
        "Citation verbatim 2 extraite de la transcription",
        "Citation verbatim 3 extraite de la transcription"
    ],
    "metadata": {{
        "interview_duration": "{interview.duration_seconds or 0}s",
        "questions_count": {len(interview.questions_asked or [])},
        "generated_by": "AIHM AI Assistant",
        "disclaimer": "Ce rapport est genere par IA a titre informatif. Il ne constitue pas une recommandation d'embauche."
    }}
}}""",
            }
        ],
    )

    try:
        text_content = response.content[0].text
        if "```json" in text_content:
            text_content = text_content.split("```json")[1].split("```")[0]
        elif "```" in text_content:
            text_content = text_content.split("```")[1].split("```")[0]
        report = json.loads(text_content.strip())

        # Ensure matching_score is set from our computation (not LLM hallucination)
        if matching_score is not None:
            report["matching_score"] = matching_score

        # Ensure skill_matrix is populated from analysis skill_scores if LLM missed it
        if skill_scores and "skill_matrix" not in report:
            report["skill_matrix"] = [
                {
                    "skill": ss.get("skill", ""),
                    "category": ss.get("category", "technique"),
                    "required": ss.get("level_required", 3),
                    "demonstrated": ss.get("demonstrated", 0),
                    "motivation": ss.get("motivation", 0),
                    "evidence": ss.get("evidence", "")[:100],
                }
                for ss in skill_scores
            ]

        return report
    except (json.JSONDecodeError, IndexError):
        result = {
            "title": f"Rapport - {candidate.name}",
            "position": position.title,
            "summary": "Erreur lors de la generation du rapport",
            "scores": analysis.scores if analysis else {},
            "metadata": {"generated_by": "AIHM", "error": True},
        }
        # Still include skill_matrix from analysis even if LLM report fails
        if skill_scores:
            result["matching_score"] = matching_score
            result["skill_matrix"] = [
                {
                    "skill": ss.get("skill", ""),
                    "category": ss.get("category", "technique"),
                    "required": ss.get("level_required", 3),
                    "demonstrated": ss.get("demonstrated", 0),
                    "motivation": ss.get("motivation", 0),
                    "evidence": ss.get("evidence", "")[:100],
                }
                for ss in skill_scores
            ]
        return result
