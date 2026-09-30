"""
Ajan endpoint'leri.

POST /api/agents/chat       → Açıklama ajanı (NL soru-cevap)
POST /api/agents/orchestrate → Orkestratör (tam ajan zinciri)
GET  /api/agents/health     → Ajan sağlık kontrolü
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.models.portfolio import ChatRequest, PortfolioRequest
from app.agents.orchestrator import orchestrator
from app.core.llm import llm

router = APIRouter(prefix="/agents", tags=["agents"])


class OrchestrateRequest(BaseModel):
    message: str
    portfolio: PortfolioRequest | None = None
    run_agents: list[str] | None = None  # None → orkestratör karar verir
    thresholds: dict[str, float] | None = None  # örn. uyarı ajanı için {"ips_floor": 75}


@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Türkçe NL soru-cevap — açıklama ajanı.
    Portföy bağlamıyla veya bağlaçsız çalışır.

    Örnek:
    {
      "message": "Altın mı dolar mı daha mantıklı bu ortamda?",
      "history": [],
      "portfolio_context": {...}
    }
    """
    context = {}
    if request.portfolio_context:
        context["portfolio"] = request.portfolio_context

    from app.agents import explanation_agent
    result = await explanation_agent.run(request.message, context)

    return {
        "response": result.get("response", ""),
        "message": request.message,
    }


@router.post("/orchestrate")
async def orchestrate(request: OrchestrateRequest):
    """
    Tam ajan orkestrasyon döngüsü.
    İstek niyete göre otomatik ajan seçimi veya zorunlu ajan listesiyle çalışır.
    """
    context = {}
    if request.portfolio:
        context["portfolio"] = request.portfolio
    if request.thresholds:
        context["thresholds"] = request.thresholds

    result = await orchestrator.run(
        user_message=request.message,
        context=context if context else None,
        force_agents=request.run_agents,
    )

    return result


@router.get("/health")
async def agent_health():
    """LLM bağlantısı ve ajan sağlık kontrolü."""
    from app.config import settings

    try:
        test_response = await llm.chat(
            "Merhaba, çalışıyor musun? Tek kelimeyle yanıtla.",
            max_tokens=10,
        )
        llm_ok = bool(test_response)
    except Exception as e:
        return {
            "status": "error",
            "llm_provider": settings.llm_provider,
            "error": str(e),
        }

    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "model": settings.groq_model if settings.llm_provider == "groq" else settings.gemini_model,
        "agents": ["analysis", "recommendation", "explanation", "report", "alert"],
        "llm_response_sample": test_response[:50],
    }
