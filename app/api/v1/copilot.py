import json
import logging
from typing import List

from anthropic import Anthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_tenant_id
from app.core.rate_limit import limiter
from app.models.user import User
from app.services.copilot import (
    COPILOT_SYSTEM_PROMPT,
    COPILOT_TOOLS,
    execute_tool,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/copilot", tags=["copilot"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_length=1)


@router.post("/chat")
@limiter.limit("10/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()

    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Claude API non configuree",
        )

    async def generate():
        try:
            client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

            messages = [{"role": m.role, "content": m.content} for m in body.messages]

            for turn in range(5):
                logger.info(f"Copilot turn {turn + 1}, user={current_user.email}")

                response = client.messages.create(
                    model=settings.ANTHROPIC_MODEL,
                    max_tokens=4096,
                    system=COPILOT_SYSTEM_PROMPT,
                    tools=COPILOT_TOOLS,
                    messages=messages,
                )

                if response.stop_reason == "end_turn":
                    for block in response.content:
                        if block.type == "text":
                            yield f"data: {json.dumps({'text': block.text})}\n\n"
                    break

                if response.stop_reason == "tool_use":
                    messages.append({
                        "role": "assistant",
                        "content": [
                            {"type": b.type, **({"text": b.text} if b.type == "text" else {"id": b.id, "name": b.name, "input": b.input})}
                            for b in response.content
                        ],
                    })

                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            logger.info(f"Executing tool: {block.name}")
                            result = await execute_tool(
                                tool_name=block.name,
                                tool_input=block.input,
                                db=db,
                                tenant_id=tenant_id,
                            )
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            })

                    messages.append({"role": "user", "content": tool_results})
                    continue

                break

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Copilot error: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
