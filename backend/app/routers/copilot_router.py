import json
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from openai import AsyncOpenAI

from backend.app.core.db import get_db
from backend.app.dependencies import get_current_user, require_admin
from backend.app.models.user import User
from backend.app.config import settings
from backend.app.services.copilot_service import build_copilot_context_async
from backend.app.core.copilot_cache import cache_metrics

logger = logging.getLogger("akriti.copilot.router")

router = APIRouter(prefix="/copilot", tags=["copilot"])

class ChatRequest(BaseModel):
    message: str

# In-memory store for rate limiting: { "user_id": [datetime1, datetime2] }
user_chat_timestamps = {}

@router.post("/chat")
async def chat_with_copilot(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Stream a response from the PathLab AI Copilot using Redis-first cache-aside,
    deterministic backend verification, and LLM presentation.
    """
    global user_chat_timestamps
    t_start = time.time()

    # --- Role-based Rate Limiting ---
    role_str = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    limit = 15 if role_str == "admin" else 5
    user_id = str(current_user.id)
    now = datetime.now()

    # Clean up old inactive users from memory dictionary periodically to prevent memory leaks
    if len(user_chat_timestamps) > 500:
        cutoff = now.timestamp() - 3600
        user_chat_timestamps = {
            uid: [t for t in ts if t.timestamp() > cutoff]
            for uid, ts in user_chat_timestamps.items()
            if any(t.timestamp() > cutoff for t in ts)
        }

    history = user_chat_timestamps.get(user_id, [])
    history = [t for t in history if (now - t).total_seconds() < 60]

    if len(history) >= limit:
        async def rate_limit_stream():
            yield f"data: {json.dumps(f'⚠️ RATE LIMIT: Aap 1 minute me max {limit} messages bhej sakte hain. Kripya thodi der rukiye.')}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(rate_limit_stream(), media_type="text/event-stream")

    history.append(now)
    user_chat_timestamps[user_id] = history
    # --------------------------------

    # Step 1: Deterministic Backend Retrieval with Redis-first Cache-Aside
    system_prompt, direct_response, lookup_result = await build_copilot_context_async(
        request.message, current_user, db
    )

    # Step 2: Authoritative terminal status (not_found, invalid_input, forbidden, service_unavailable)
    # Stream the verified authoritative answer directly to the client.
    # Zero LLM call, zero latency, zero tokens wasted, 100% zero hallucination guarantee!
    if direct_response:
        t_total = (time.time() - t_start) * 1000
        logger.info(
            f"Copilot direct response: status={getattr(lookup_result, 'status', 'direct')} | "
            f"cached={getattr(lookup_result, 'is_cached', False)} | latency={t_total:.2f}ms"
        )
        async def direct_stream():
            yield f"data: {json.dumps(direct_response)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(direct_stream(), media_type="text/event-stream")

    # Step 3: LLM Natural Language Presentation of Verified Facts
    api_key = settings.effective_llm_api_key
    base_url = settings.effective_llm_base_url
    model_name = settings.effective_llm_model

    if not api_key:
        async def missing_key_stream():
            yield f"data: {json.dumps('⚠️ AI API Key configure nahi hai. Kripya .env file me NVIDIA_API_KEY ya GROQ_API_KEY set karein.')}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(missing_key_stream(), media_type="text/event-stream")

    # Initialize OpenAI-compatible Client (NVIDIA, Groq, OpenAI, etc.)
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=api_key
    )

    async def event_generator():
        try:
            create_kwargs: Dict[str, Any] = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": request.message}
                ],
                "temperature": 0.6,
                "top_p": 0.95,
                "max_tokens": 2048,
                "stream": True,
            }

            # For NVIDIA nemotron, disable internal thinking to keep replies fast, direct, and clean
            if "nvidia" in base_url.lower() and "nemotron" in model_name.lower():
                create_kwargs["extra_body"] = {
                    "chat_template_kwargs": {"enable_thinking": False}
                }

            response = await client.chat.completions.create(**create_kwargs)

            # Stream ONLY the final clean response content
            async for chunk in response:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if content is not None:
                    clean_content = content.replace("<think>", "").replace("</think>", "")
                    if clean_content:
                        yield f"data: {json.dumps(clean_content)}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Copilot LLM Error with model '{model_name}': {e}", exc_info=True)
            yield f"data: {json.dumps(f'[Error from AI: {str(e)}]')}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/metrics")
def get_copilot_metrics(current_user=Depends(require_admin)):
    """Admin-only performance metrics for Copilot cache and retrieval."""
    total_lookups = cache_metrics["hits"] + cache_metrics["misses"]
    hit_ratio = (cache_metrics["hits"] / total_lookups * 100.0) if total_lookups > 0 else 0.0
    return {
        "cache_hits": cache_metrics["hits"],
        "cache_misses": cache_metrics["misses"],
        "negative_cache_hits": cache_metrics["negative_hits"],
        "cache_writes": cache_metrics["writes"],
        "cache_invalidations": cache_metrics["invalidations"],
        "cache_errors": cache_metrics["errors"],
        "hit_ratio_percent": round(hit_ratio, 2),
        "active_provider": settings.LLM_PROVIDER,
        "active_model": settings.effective_llm_model,
        "redis_enabled": settings.REDIS_ENABLED
    }
