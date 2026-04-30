import json
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from anthropic import Anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.copilot_prompts import COPILOT_SYSTEM_PROMPT, COPILOT_TOOLS
from app.services.copilot_parser import (
    handle_search_candidates,
    handle_list_positions,
    handle_get_position_details,
    handle_get_candidate_details,
    handle_get_analytics_overview,
    handle_aggregate_scores,
    handle_get_pipeline_breakdown,
    handle_export_data,
)

logger = logging.getLogger(__name__)


def call_claude_json(
    prompt: str,
    max_tokens: int = 2000,
    model: Optional[str] = None,
    system: Optional[str] = None,
) -> Dict[str, Any]:
    """Helper synchrone : envoie un prompt à Claude et parse la réponse en JSON.

    Reuse pattern de `services/position_import.py`. Utilisé par les parsers IA
    (import-text candidat, etc.).

    Lève les exceptions Anthropic en cas d'échec API.
    Lève `json.JSONDecodeError` si la réponse n'est pas du JSON valide.

    NOTE async/sync : appelé en sync depuis un endpoint async, ça bloque l'event loop
    le temps de l'appel Anthropic (~1-3 s). À déplacer dans un worker Celery
    si l'usage devient fréquent (cf. V1_BACKLOG section 2 / scaling).
    """
    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    create_kwargs: Dict[str, Any] = {
        "model": model or settings.ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        create_kwargs["system"] = system

    response = client.messages.create(**create_kwargs)
    text = response.content[0].text

    # Strip markdown fences si Claude en met (parfois oui, parfois non)
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]

    return json.loads(text.strip())


async def execute_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    db: AsyncSession,
    tenant_id: UUID
) -> str:
    logger.info(f"Copilot tool execution: {tool_name} with params {tool_input}")

    try:
        if tool_name == "search_candidates":
            return await handle_search_candidates(db, tenant_id, tool_input)

        elif tool_name == "list_positions":
            return await handle_list_positions(db, tenant_id, tool_input)

        elif tool_name == "get_position_details":
            return await handle_get_position_details(db, tenant_id, tool_input)

        elif tool_name == "get_candidate_details":
            return await handle_get_candidate_details(db, tenant_id, tool_input)

        elif tool_name == "get_analytics_overview":
            return await handle_get_analytics_overview(db, tenant_id, tool_input)

        elif tool_name == "aggregate_scores":
            return await handle_aggregate_scores(db, tenant_id, tool_input)

        elif tool_name == "get_pipeline_breakdown":
            return await handle_get_pipeline_breakdown(db, tenant_id, tool_input)

        elif tool_name == "export_data":
            return await handle_export_data(db, tenant_id, tool_input)

        else:
            return json.dumps({
                "error": f"Outil inconnu : {tool_name}"
            }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
        return json.dumps({
            "error": f"Erreur lors de l'exécution de l'outil : {str(e)}"
        }, ensure_ascii=False)
