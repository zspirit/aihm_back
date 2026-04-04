import json
import logging
from typing import Any, Dict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

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
