import pytest

from app.assistant.chat.memory import InMemoryConversationStore
from app.assistant.chat.service import ChatService, StationNotFoundError
from app.assistant.config import get_settings
from app.assistant.llm.base import LLMChunk
from tests.assistant.conftest import NOW, ScriptedLLM, tool_call

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_service(llm, repo, memory=None):
    memory = memory or InMemoryConversationStore(max_turns=4, ttl_seconds=60, max_sessions=10)
    return ChatService(get_settings(), llm, repo, memory, clock=lambda: NOW)


async def collect(service, question, station="EST001-PALTAS", session="s1"):
    return [e async for e in service.ask_stream(station, question, "user@test", session)]


async def test_tool_flow_executes_against_requested_station(repo):
    llm = ScriptedLLM(
        [
            tool_call("estadisticas_sensor", sensor="temperatura_ambiente", periodo="ayer"),
            LLMChunk(text="Ayer la máxima fue 28.0 °C a las 01:00."),
        ]
    )
    result = await make_service(llm, repo).ask("EST002-PALTAS", "¿Qué datos tiene la estación?", "user@test", "s1")

    assert result.answer == "Ayer la máxima fue 28.0 °C a las 01:00."
    assert [t.name for t in result.tools] == ["estadisticas_sensor"]
    assert {sid for _, sid in repo.calls} == {2}
    # El resultado de la herramienta se envió al modelo en la segunda llamada.
    tool_msg = llm.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "ESTACIÓN 2" in tool_msg["content"]


async def test_system_prompt_is_bound_to_station(repo):
    llm = ScriptedLLM([LLMChunk(text="Solo puedo informar sobre ESTACIÓN 1.")])
    await make_service(llm, repo).ask("EST001-PALTAS", "hola", "u", "s")
    system = llm.requests[0]["messages"][0]["content"]
    assert "ESTACIÓN 1" in system and "2026-09-25 15:30" in system


async def test_streams_final_answer_after_tools(repo):
    # "¿Clima?" lo planifica el código: la lectura actual se consulta antes de llamar al modelo.
    llm = ScriptedLLM([LLMChunk(text="Hace 20.0 °C.")])
    events = await collect(make_service(llm, repo), "¿Clima?")
    types = [e.type for e in events]
    assert types == ["tool", "delta", "delta", "done"]
    assert "".join(e.text for e in events if e.type == "delta") == "Hace 20.0 °C."


async def test_ungrounded_numbers_trigger_one_retry(repo):
    llm = ScriptedLLM(
        [
            LLMChunk(text="La temperatura es 30 °C."),  # inventado, sin herramienta
            tool_call("lecturas_actuales"),
            LLMChunk(text="La temperatura es 20.0 °C."),
        ]
    )
    events = await collect(make_service(llm, repo), "¿Qué datos tiene la estación?")
    deltas = "".join(e.text for e in events if e.type == "delta")
    assert "30 °C" not in deltas
    assert events[-1].result.answer == "La temperatura es 20.0 °C."


async def test_refusal_without_tools_is_returned(repo):
    llm = ScriptedLLM([LLMChunk(text="Solo asesoro sobre el cultivo de palta con los datos de ESTACIÓN 1.")])
    result = await make_service(llm, repo).ask("EST001-PALTAS", "¿Quién ganó el mundial?", "u", "s")
    assert result.tools == []
    assert repo.calls == []


async def test_tool_rounds_are_capped(repo):
    rounds = get_settings().chat_max_tool_rounds
    llm = ScriptedLLM([tool_call("lecturas_actuales")] * rounds + [LLMChunk(text="Resumen final.")])
    result = await make_service(llm, repo).ask("EST001-PALTAS", "¿Qué datos tiene la estación?", "u", "s")
    assert result.answer == "Resumen final."
    assert llm.requests[-1]["tools"] is None  # la última ronda ya no ofrece herramientas


async def test_history_is_kept_per_session(repo):
    memory = InMemoryConversationStore(max_turns=4, ttl_seconds=60, max_sessions=10)
    llm = ScriptedLLM([LLMChunk(text="Primera."), LLMChunk(text="Segunda.")])
    service = make_service(llm, repo, memory)
    await service.ask("EST001-PALTAS", "¿qué mide la estación?", "u", "s")
    await service.ask("EST001-PALTAS", "¿qué datos guarda la estación?", "u", "s")
    sent = [m["content"] for m in llm.requests[1]["messages"][1:]]
    assert sent == ["¿qué mide la estación?", "Primera.", "¿qué datos guarda la estación?"]


async def test_unknown_station(repo):
    with pytest.raises(StationNotFoundError):
        await make_service(ScriptedLLM([]), repo).ask("NOPE", "hola", "u", "s")


async def test_unsupported_value_after_tool_is_regenerated(repo):
    # lecturas_actuales del FakeRepository devuelve 20.0, 21.0, ... → 18.5 °C no está en los datos
    llm = ScriptedLLM(
        [
            tool_call("lecturas_actuales"),
            LLMChunk(text="La temperatura es 18.5 °C."),
            LLMChunk(text="La temperatura es 20.0 °C."),
        ]
    )
    events = await collect(make_service(llm, repo), "¿Qué datos tiene la estación?")
    types = [e.type for e in events]
    assert types == ["tool", "delta", "delta", "reset", "delta", "delta", "done"]
    assert events[-1].result.answer == "La temperatura es 20.0 °C."
    correction = llm.requests[-1]["messages"][-1]["content"]
    assert "18.5 °C" in correction


async def test_correction_happens_only_once(repo):
    llm = ScriptedLLM(
        [tool_call("lecturas_actuales"), LLMChunk(text="Son 18.5 °C."), LLMChunk(text="Son 19.5 °C.")]
    )
    result = await make_service(llm, repo).ask("EST001-PALTAS", "¿Qué datos tiene la estación?", "u", "s")
    assert result.answer == "Son 19.5 °C."  # se entrega (y se registra en el log) tras un intento
    assert len(llm.requests) == 3


async def test_quality_warning_is_appended_when_model_omits_it():
    from tests.assistant.conftest import FakeRepository

    repo = FakeRepository(zeros=4)
    llm = ScriptedLLM(
        [tool_call("estadisticas_sensor", sensor="humedad_suelo", periodo="ayer"), LLMChunk(text="El promedio fue 24.5 %.")]
    )
    events = await collect(make_service(llm, repo), "¿Humedad del suelo de ayer?")
    answer = events[-1].result.answer
    assert answer.startswith("El promedio fue 24.5 %.\n\nAviso: 4 de 10 lecturas marcan exactamente 0 %")
    deltas = [e.text for e in events if e.type == "delta"]
    assert deltas[-1].startswith("\n\nAviso:")  # el aviso llega como fragmento aparte, al final


async def test_quality_warning_not_duplicated_when_mentioned():
    from tests.assistant.conftest import FakeRepository

    llm = ScriptedLLM(
        [
            tool_call("estadisticas_sensor", sensor="humedad_suelo", periodo="ayer"),
            LLMChunk(text="Promedio 24.5 %; varias lecturas en 0 %, posible sensor desconectado."),
        ]
    )
    result = await make_service(llm, FakeRepository(zeros=4)).ask("EST001-PALTAS", "¿Qué datos tiene la estación?", "u", "s")
    assert "Aviso:" not in result.answer


async def test_direct_answer_skips_second_model_call():
    from tests.assistant.conftest import FakeRepository

    llm = ScriptedLLM([])
    events = await collect(make_service(llm, FakeRepository(has_data=False)), "¿Temperatura ambiente máxima de hoy?")
    assert [e.type for e in events] == ["tool", "delta", "done"]
    assert events[-1].result.answer.startswith("No hay reporte de temperatura ambiente de hoy (25 de setiembre de 2026).")
    assert llm.requests == []  # consulta planificada y respuesta directa: el modelo no se llama


async def test_advice_question_gets_diagnosis_before_the_model(repo):
    llm = ScriptedLLM([LLMChunk(text="Sí, conviene regar: la humedad del suelo promedio fue 24.5 %.")])
    result = await make_service(llm, repo).ask("EST001-PALTAS", "¿Debo regar hoy?", "u", "s")
    assert [t.name for t in result.tools] == ["diagnostico_palta"]
    assert result.answer.startswith("Sí, conviene regar")
    # El modelo recibe el diagnóstico ya consultado y el rol de experto
    first = llm.requests[0]["messages"]
    assert "experto en palta Hass" in first[0]["content"]
    assert first[-1]["role"] == "tool" and "alertas_palta" in first[-1]["content"]
