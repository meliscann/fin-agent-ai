"""
Ajan Orkestratörü — FinAgent'ın beyni.

Kullanıcı isteğini alır → hangi ajanların çalışacağına karar verir
→ ajanları (gerekirse paralel) çalıştırır → yanıtları birleştirir.
"""

import asyncio
from enum import Enum
from app.core.llm import llm


class AgentType(str, Enum):
    ANALYSIS    = "analysis"
    RECOMMEND   = "recommendation"
    EXPLANATION = "explanation"
    REPORT      = "report"
    ALERT       = "alert"


ORCHESTRATOR_SYSTEM = """Sen FinAgent'ın ajan orkestratörüsün.
Kullanıcının isteğini analiz et ve hangi uzman ajanların çalışması gerektiğine karar ver.

Yanıtını SADECE JSON formatında ver, başka hiçbir şey ekleme:
{
  "intent": "kısa niyet açıklaması",
  "agents": ["ajan1", "ajan2"],
  "priority": "high|medium|low",
  "reasoning": "neden bu ajanlar seçildi"
}

Kullanılabilir ajanlar: analysis, recommendation, explanation, report, alert
"""


class Orchestrator:
    async def route(self, user_message: str, context: dict | None = None) -> dict:
        """
        Kullanıcı mesajını analiz eder, hangi ajanların tetikleneceğine karar verir.
        """
        prompt = f"Kullanıcı isteği: {user_message}"
        if context:
            prompt += f"\n\nBağlam: {context}"

        raw = await llm.chat(user_message=prompt, system=ORCHESTRATOR_SYSTEM, temperature=0.1)

        try:
            import json
            # JSON bloğunu temizle
            clean = raw.strip().lstrip("```json").rstrip("```").strip()
            return json.loads(clean)
        except Exception:
            # Fallback: varsayılan ajanlar
            return {
                "intent": "genel portföy analizi",
                "agents": [AgentType.ANALYSIS, AgentType.EXPLANATION],
                "priority": "medium",
                "reasoning": "Niyet belirlenemedi, varsayılan analiz akışı kullanılıyor.",
            }

    async def run(
        self,
        user_message: str,
        context: dict | None = None,
        force_agents: list[AgentType] | None = None,
    ) -> dict:
        """
        Tam ajan çalıştırma döngüsü.
        force_agents verilirse routing atlanır, doğrudan o ajanlar çalışır.
        """
        if force_agents:
            agents_to_run = force_agents
            routing = {"intent": "zorunlu ajan çalıştırma", "agents": agents_to_run}
        else:
            routing = await self.route(user_message, context)
            agents_to_run = routing.get("agents", [])

        results = await self._run_agents(agents_to_run, user_message, context)

        return {
            "routing": routing,
            "agent_results": results,
            "message": user_message,
        }

    async def _run_agents(
        self,
        agent_names: list[str],
        message: str,
        context: dict | None,
    ) -> dict:
        """Seçilen ajanları paralel çalıştırır."""
        from app.agents import (
            analysis_agent,
            recommendation_agent,
            explanation_agent,
            report_agent,
            alert_agent,
        )

        agent_map = {
            AgentType.ANALYSIS:    analysis_agent.run,
            AgentType.RECOMMEND:   recommendation_agent.run,
            AgentType.EXPLANATION: explanation_agent.run,
            AgentType.REPORT:      report_agent.run,
            AgentType.ALERT:       alert_agent.run,
        }

        tasks = {}
        for name in agent_names:
            fn = agent_map.get(name)
            if fn:
                tasks[name] = fn(message, context)

        if not tasks:
            return {}

        results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)

        return {
            name: (result if not isinstance(result, Exception) else {"error": str(result)})
            for name, result in zip(tasks.keys(), results_list)
        }


orchestrator = Orchestrator()
