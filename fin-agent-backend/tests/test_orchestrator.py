"""
Orkestratörün (route/run/_run_agents) testleri. LLM çağrıları mock'lanır —
bkz. test_agents.py'deki mock_llm deseni; burada aynı desen tekrarlanır
çünkü orchestrator.py kendi `llm` referansını (app.core.llm.llm) kullanır.
"""

import pytest

from app.agents.orchestrator import Orchestrator, AgentType
from app.core import llm as llm_module


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    """route()'un LLM çağrısını sahte, hızlı bir yanıtla değiştirir."""
    async def fake_chat(user_message, system=None, temperature=0.3, max_tokens=1500):
        return "Sahte LLM yanıtı (test)."
    monkeypatch.setattr(llm_module.llm, "chat", fake_chat)
    yield


@pytest.fixture
def orchestrator():
    # Modül seviyesindeki tekil `orchestrator` yerine her testte taze bir
    # örnek — testler arasında paylaşılan durum olmasın diye.
    return Orchestrator()


class TestRoute:
    @pytest.mark.asyncio
    async def test_valid_json_response_is_parsed(self, orchestrator, monkeypatch):
        async def fake_chat(user_message, system=None, temperature=0.3, max_tokens=1500):
            return '{"intent": "rapor iste", "agents": ["report"], "priority": "high", "reasoning": "kullanıcı PDF istedi"}'
        monkeypatch.setattr(llm_module.llm, "chat", fake_chat)

        result = await orchestrator.route("PDF rapor oluştur")
        assert result["agents"] == ["report"]
        assert result["intent"] == "rapor iste"

    @pytest.mark.asyncio
    async def test_json_wrapped_in_code_fence_is_parsed(self, orchestrator, monkeypatch):
        async def fake_chat(user_message, system=None, temperature=0.3, max_tokens=1500):
            return '```json\n{"intent": "analiz", "agents": ["analysis"], "priority": "medium", "reasoning": "x"}\n```'
        monkeypatch.setattr(llm_module.llm, "chat", fake_chat)

        result = await orchestrator.route("portföyümü analiz et")
        assert result["agents"] == ["analysis"]

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back_to_default_agents(self, orchestrator, monkeypatch):
        async def fake_chat(user_message, system=None, temperature=0.3, max_tokens=1500):
            return "bu geçerli bir JSON değil, düz metin"
        monkeypatch.setattr(llm_module.llm, "chat", fake_chat)

        result = await orchestrator.route("herhangi bir şey")
        assert result["agents"] == [AgentType.ANALYSIS, AgentType.EXPLANATION]
        assert "intent" in result
        assert "reasoning" in result


class TestRun:
    @pytest.mark.asyncio
    async def test_force_agents_skips_routing(self, orchestrator, monkeypatch):
        route_called = {"value": False}

        async def spy_route(self, user_message, context=None):
            route_called["value"] = True
            return {"agents": []}
        monkeypatch.setattr(Orchestrator, "route", spy_route)

        result = await orchestrator.run("mesaj", force_agents=[AgentType.EXPLANATION])

        assert route_called["value"] is False
        assert result["routing"]["agents"] == [AgentType.EXPLANATION]
        assert "explanation" in result["agent_results"]

    @pytest.mark.asyncio
    async def test_no_force_agents_uses_routing_result(self, orchestrator, monkeypatch):
        async def fake_chat(user_message, system=None, temperature=0.3, max_tokens=1500):
            return '{"intent": "x", "agents": ["explanation"], "priority": "low", "reasoning": "y"}'
        monkeypatch.setattr(llm_module.llm, "chat", fake_chat)

        result = await orchestrator.run("bir soru")

        assert result["routing"]["agents"] == ["explanation"]
        assert "explanation" in result["agent_results"]


class TestRunAgentsParallel:
    @pytest.mark.asyncio
    async def test_runs_multiple_agents_concurrently(self, orchestrator):
        # explanation (LLM mock'lu) ve alert (portföysüz, deterministik) —
        # ikisi de context'e ihtiyaç duymadan çalışabilir.
        result = await orchestrator._run_agents(
            [AgentType.EXPLANATION, AgentType.ALERT], "test mesajı", None
        )
        assert "response" in result["explanation"]
        assert "alerts" in result["alert"]

    @pytest.mark.asyncio
    async def test_exception_in_one_agent_does_not_break_others(self, orchestrator, monkeypatch):
        from app.agents import analysis_agent

        async def broken_run(message, context=None):
            raise RuntimeError("kasıtlı test hatası")
        monkeypatch.setattr(analysis_agent, "run", broken_run)

        result = await orchestrator._run_agents(
            [AgentType.ANALYSIS, AgentType.EXPLANATION], "test", None
        )

        assert "error" in result["analysis"]
        assert "response" in result["explanation"]

    @pytest.mark.asyncio
    async def test_unknown_agent_name_is_silently_skipped(self, orchestrator):
        result = await orchestrator._run_agents(["bilinmeyen_ajan"], "test", None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_agent_list_returns_empty_dict(self, orchestrator):
        result = await orchestrator._run_agents([], "test", None)
        assert result == {}
