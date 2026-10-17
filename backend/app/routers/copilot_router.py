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
    history: Optional[list] = []

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
    deterministic backend verification, conversation session memory, and LLM presentation.
    """
    global user_chat_timestamps
    t_start = time.time()

    # --- Role-based Rate Limiting (Admin: 10 msg/min, Staff: 5 msg/min) ---
    role_str = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    admin_limit = getattr(settings, 'COPILOT_LIMIT_ADMIN', 10)
    staff_limit = getattr(settings, 'COPILOT_LIMIT_STAFF', 5)
    limit = admin_limit if role_str.lower() == "admin" else staff_limit
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
            yield f"data: {json.dumps(f'Rate Limit Reached: You can send a maximum of {limit} messages per minute ({role_str.capitalize()} limit: {limit}/min). Please wait a moment before sending another message.')}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(rate_limit_stream(), media_type="text/event-stream")

    history.append(now)
    user_chat_timestamps[user_id] = history
    # --------------------------------

    # Step 1: Deterministic Backend Retrieval with Redis-first Cache-Aside & Conversation Memory
    system_prompt, direct_response, lookup_result = await build_copilot_context_async(
        request.message, current_user, db, history=request.history
    )

    # Step 2: Authoritative terminal status (not_found, invalid_input, forbidden, service_unavailable)
    # Stream the verified authoritative answer directly to the client.
    # Zero LLM call, zero latency, zero tokens wasted, 100% zero hallucination guarantee!
    if direct_response:
        t_total = (time.time() - t_start) * 1000
        source_label = getattr(lookup_result, 'cache_source', 'none') if lookup_result else 'direct'
        logger.info(
            f"Copilot direct response: status={getattr(lookup_result, 'status', 'direct')} | "
            f"source={source_label} | cached={getattr(lookup_result, 'is_cached', False)} | latency={t_total:.2f}ms"
        )
        async def direct_stream():
            yield f"data: {json.dumps(direct_response)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(direct_stream(), media_type="text/event-stream")

    # Step 3: High-Speed LLM Stream with Automatic Provider Fallback (Groq Primary -> NVIDIA Fallback)
    providers = []
    
    # 1. Groq (Ultra-low latency, sub-second response)
    if settings.GROQ_API_KEY:
        providers.append({
            "name": "Groq",
            "base_url": settings.GROQ_BASE_URL or "https://api.groq.com/openai/v1",
            "api_key": settings.GROQ_API_KEY,
            "model": settings.GROQ_MODEL or "qwen/qwen3.8-27b",
            "extra_body": None,
            "timeout": 10.0,
        })
        
    # 2. NVIDIA (Secondary fallback)
    if settings.NVIDIA_API_KEY:
        providers.append({
            "name": "NVIDIA",
            "base_url": settings.NVIDIA_BASE_URL or "https://integrate.api.nvidia.com/v1",
            "api_key": settings.NVIDIA_API_KEY,
            "model": settings.NVIDIA_MODEL or "nvidia/nemotron-3.5-lightning-30b-a3b",
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
            "timeout": 20.0,
        })

    # If user explicitly configured LLM_PROVIDER as nvidia, place it first
    if (settings.LLM_PROVIDER or "").lower() == "nvidia":
        providers.reverse()

    if not providers:
        async def missing_key_stream():
            yield f"data: {json.dumps('⚠️ AI API Key configure nahi hai. Kripya .env file me GROQ_API_KEY ya NVIDIA_API_KEY set karein.')}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(missing_key_stream(), media_type="text/event-stream")

    async def event_generator():
        last_error = None
        for prov in providers:
            try:
                client = AsyncOpenAI(
                    base_url=prov["base_url"],
                    api_key=prov["api_key"],
                    timeout=prov["timeout"]
                )
                # Assemble token-optimized messages: System + compressed recent history (max 5) + User
                llm_messages = [{"role": "system", "content": system_prompt}]
                if request.history:
                    for h in request.history[-5:]:
                        h_role = h.get("role", "user")
                        h_content = str(h.get("content", ""))
                        if not h_content:
                            continue
                        # If content is a raw JSON patient card, compress it to save prompt tokens
                        if '{"__card": "patient"' in h_content or '"__card":"patient"' in h_content:
                            try:
                                c_data = json.loads(h_content)
                                tests_str = ", ".join(c_data.get("tests", []))[:80]
                                h_content = (
                                    f"[Patient Card: {c_data.get('code', 'PAT')} - {c_data.get('name', '')}, "
                                    f"Age: {c_data.get('age')}/{c_data.get('gender')}, Tests: {tests_str}, "
                                    f"Due: Rs {c_data.get('due', 0)}]"
                                )
                            except Exception:
                                h_content = h_content[:200]
                        elif len(h_content) > 300:
                            h_content = h_content[:300] + "..."
                        llm_messages.append({"role": h_role, "content": h_content})
                llm_messages.append({"role": "user", "content": request.message})

                create_kwargs: Dict[str, Any] = {
                    "model": prov["model"],
                    "messages": llm_messages,
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "max_tokens": min(getattr(settings, "LLM_MAX_TOKENS", 500), 500),
                    "stream": True,
                }
                if prov.get("extra_body"):
                    create_kwargs["extra_body"] = prov["extra_body"]

                response = await client.chat.completions.create(**create_kwargs)
                has_yielded = False
                in_think_block = False

                async for chunk in response:
                    if not chunk.choices:
                        continue
                    delta_content = chunk.choices[0].delta.content
                    if delta_content is None:
                        continue

                    # Filter out think tags if generated
                    if "<think>" in delta_content:
                        in_think_block = True
                        delta_content = delta_content.replace("<think>", "")
                    if "</think>" in delta_content:
                        in_think_block = False
                        delta_content = delta_content.replace("</think>", "")
                    
                    if not in_think_block and delta_content:
                        has_yielded = True
                        yield f"data: {json.dumps(delta_content)}\n\n"

                if has_yielded:
                    yield "data: [DONE]\n\n"
                    return
            except Exception as e:
                logger.warning(f"Copilot provider '{prov['name']}' failed ({e}). Attempting next provider...")
                last_error = e
                continue

        logger.error(f"All Copilot LLM providers failed. Last error: {last_error}", exc_info=True)
        yield f"data: {json.dumps(f'[AI response error: {str(last_error)}]')}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/metrics")
def get_copilot_metrics(current_user=Depends(require_admin)):
    """Admin-only performance metrics for Copilot cache and retrieval."""
    total_lookups = cache_metrics["hits"] + cache_metrics["misses"]
    hit_ratio = (cache_metrics["hits"] / total_lookups * 100.0) if total_lookups > 0 else 0.0
    return {
        "cache_hits": cache_metrics["hits"],
        "l1_hits": cache_metrics.get("l1_hits", 0),
        "redis_hits": cache_metrics.get("redis_hits", 0),
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
