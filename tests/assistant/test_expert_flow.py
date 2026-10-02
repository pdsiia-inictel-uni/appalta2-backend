"""Flujo del asistente experto: ventana anclada al último dato, diagnóstico,
contexto entre preguntas y respuestas en texto plano."""

from datetime import date, datetime

import pytest

from app.assistant.chat.memory import InMemoryConversationStore, QueryContext
from app.assistant.chat.service import ChatService
from app.assistant.config import get_settings
from app.assistant.data.repository import Reading, SensorStats
from app.assistant.domain.dates import extract_date_range
from app.assistant.llm.base import LLMChunk
from app.assistant.tools.station_tools import StationToolbox
from tests.assistant.conftest import LIMA, NOW, STATIONS, FakeRepository, ScriptedLLM

pytestmark = pytest.mark.anyio

LAST = datetime(2026, 9, 18, 13, 56, tzinfo=LIMA)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class StoppedStationRepo(FakeRepository):
    """Estación que dejó de enviar datos el 18/09 13:56 (como EST002 en las capturas)."""

    def sensor_stats(self, station_id, sensor, start_ts, end_ts):
        self.calls.append(("sensor_stats", station_id))
        if start_ts > int(LAST.timestamp()):
            return SensorStats(count=0, discarded=0, zeros=0)
        return super().sensor_stats(station_id, sensor, start_ts, end_ts)

    def last_reading(self, station_id, sensor):
        return Reading(sensor.db_code, 21.8, int(LAST.timestamp()))


def toolbox(repo, question=None):
    return StationToolbox(repo, STATIONS["EST002-PALTAS"], "America/Lima", clock=lambda: NOW, question=question)


def make_service(llm, repo, memory=None):
    memory = memory or InMemoryConversationStore(max_turns=4, ttl_seconds=60, max_sessions=10)
    return ChatService(get_settings(), llm, repo, memory, clock=lambda: NOW)


def test_month_typos_are_understood():
    today = date(2026, 9, 30)
    assert extract_date_range("promedio del mes de setimbe", today) == (date(2026, 9, 1), date(2026, 9, 30))
    assert extract_date_range("ph maximo de septimbre", today) == (date(2026, 9, 1), date(2026, 9, 30))
    assert extract_date_range("mi nombre es Juan", today) is None


def test_last_week_without_data_uses_last_recorded_week():
    result = toolbox(StoppedStationRepo()).execute("estadisticas_sensor", {"sensor": "humedad_suelo", "periodo": "ultimos_7_dias"})
    assert "respuesta_directa" not in result
    assert result["desde"] == "2026-09-11 13:57" and result["hasta"] == "2026-09-18 13:57"
    assert result["periodo_ajustado"].startswith(
        "La estación no tiene datos de los últimos 7 días: su último registro es del 18 de setiembre de 2026 a las 13:56."
    )
    assert "alertas_palta" not in result  # 24.5 % es normal: sin recomendación


def test_explicit_month_is_never_shifted():
    result = toolbox(StoppedStationRepo()).execute(
        "estadisticas_sensor", {"sensor": "humedad_suelo", "periodo": "rango", "fecha_inicio": "2026-09-20", "fecha_fin": "2026-09-24"}
    )
    assert result["sin_datos"] and "periodo_ajustado" not in result


def test_diagnosis_covers_all_sensors_with_evaluation(repo):
    result = toolbox(repo).execute("diagnostico_palta", {"periodo": "ultimos_7_dias"})
    assert len(result["sensores"]) == 6
    assert result["etapa_fenologica"].startswith("floración y cuaje")
    assert result["dpv"].startswith("DPV medio aprox.")
    assert {sid for _, sid in repo.calls} == {2}


def test_diagnosis_for_today_falls_back_to_last_24_hours():
    result = toolbox(StoppedStationRepo()).execute("diagnostico_palta", {"periodo": "hoy"})
    assert "sin_datos" not in result
    assert "Se usan los datos de las últimas 24 horas hasta ese registro" in result["periodo_ajustado"]


async def test_follow_up_question_uses_previous_sensor_and_period(repo):
    memory = InMemoryConversationStore(max_turns=4, ttl_seconds=60, max_sessions=10)
    llm = ScriptedLLM([LLMChunk(text="El promedio fue 24.5 °C."), LLMChunk(text="El mínimo fue 21.0 °C.")])
    service = make_service(llm, repo, memory)
    first = await service.ask("EST002-PALTAS", "promedio de temperatura del suelo en septiembre", "u", "s")
    second = await service.ask("EST002-PALTAS", "¿y el mínimo?", "u", "s")

    assert first.tools[0].arguments == {
        "sensor": "temperatura_suelo", "periodo": "rango", "fecha_inicio": "2026-09-01", "fecha_fin": "2026-09-30"
    }  # fmt: skip
    # "¿y el mínimo?" sin sensor ni periodo: los mismos de la pregunta anterior
    assert second.tools[0].arguments == {
        "sensor": "temperatura_suelo", "periodo": "rango", "fecha_inicio": "2026-09-01", "fecha_fin": "2026-09-25"
    }  # fmt: skip
    # El prompt del sistema del segundo turno describe la consulta anterior
    assert "la última consulta de datos fue temperatura del suelo" in llm.requests[1]["messages"][0]["content"]
    assert memory.get_context("u:EST002-PALTAS:s").sensors == ("temperatura_suelo",)


async def test_which_sensor_question_is_answered_without_the_model(repo):
    memory = InMemoryConversationStore(max_turns=4, ttl_seconds=60, max_sessions=10)
    memory.append("u:EST002-PALTAS:s", "máxima de septiembre", "Fue 35.6 °C.", QueryContext("estadisticas_sensor", ("temperatura_ambiente",), "2026-09-01", "2026-09-25"))
    llm = ScriptedLLM([])
    result = await make_service(llm, repo, memory).ask("EST002-PALTAS", "¿La temperatura presentada es ambiental o de suelo?", "u", "s")
    assert result.answer.startswith("El dato que te di corresponde a la temperatura ambiente")
    assert llm.requests == [] and result.tools == []


async def test_no_data_claim_without_query_is_retried(repo):
    llm = ScriptedLLM(
        [
            LLMChunk(text="No hay datos disponibles para ese periodo."),  # inventado, sin consultar
            LLMChunk(text="Solo asesoro sobre la palta con datos de ESTACIÓN 2."),
        ]
    )
    result = await make_service(llm, repo).ask("EST002-PALTAS", "¿Qué datos tiene la estación?", "u", "s")
    assert "No hay datos" not in result.answer
    assert "No inventes valores" in llm.requests[1]["messages"][-1]["content"]


async def test_adjusted_period_note_goes_first_and_markdown_is_removed():
    llm = ScriptedLLM([LLMChunk(text="**Depende**: la humedad del suelo promedio fue 24.5 %.")])
    result = await make_service(llm, StoppedStationRepo()).ask("EST002-PALTAS", "¿Debo regar hoy?", "u", "s")
    assert result.answer.startswith("La estación no tiene datos de hoy (25 de setiembre de 2026)")
    assert "\n\nDepende: la humedad del suelo promedio fue 24.5 %." in result.answer
    assert "*" not in result.answer


async def test_answer_always_names_the_full_sensor(repo):
    llm = ScriptedLLM([LLMChunk(text="La temperatura máxima registrada en septiembre fue de 28.0 °C, el 25 de septiembre.")])
    events = [e async for e in make_service(llm, repo).ask_stream("EST002-PALTAS", "cual fue la temperatura ambiente maxima de septiembre", "u", "s")]
    answer = events[-1].result.answer
    assert answer.startswith("La temperatura ambiente máxima registrada en septiembre fue de 28.0 °C")
    # Lo transmitido coincide con la respuesta final
    assert "".join(e.text for e in events if e.type == "delta") == answer


async def test_wrong_sensor_name_is_corrected(repo):
    llm = ScriptedLLM([LLMChunk(text="La humedad del suelo promedio de septiembre fue 24.5 %.")])
    result = await make_service(llm, repo).ask("EST002-PALTAS", "cual es la humedad ambiente promedio de setimbe", "u", "s")
    assert result.tools[0].arguments["sensor"] == "humedad_ambiente"
    assert result.answer.startswith("La humedad ambiente promedio de septiembre fue 24.5 %.")


@pytest.mark.parametrize(
    "question, sensor, expected",
    [
        ("esta temperatura yes de ambiente o de suelo?", "temperatura_ambiente", "temperatura ambiente"),
        ("esa humedad yes de suelo u ambiente?", "humedad_ambiente", "humedad ambiente"),
    ],
)
async def test_screenshot_clarifications_use_context_without_new_queries(repo, question, sensor, expected):
    memory = InMemoryConversationStore(max_turns=4, ttl_seconds=60, max_sessions=10)
    memory.append("u:EST002-PALTAS:s", "pregunta", "respuesta", QueryContext("estadisticas_sensor", (sensor,), "2026-09-01", "2026-09-25"))
    llm = ScriptedLLM([])
    result = await make_service(llm, repo, memory).ask("EST002-PALTAS", question, "u", "s")
    assert result.answer.startswith(f"El dato que te di corresponde a la {expected}")
    assert result.tools == [] and llm.requests == []


def test_count_question_gives_exact_numbers_for_the_month_asked(repo):
    # En octubre, "todo el mes de setiembre" debe contar setiembre aunque el modelo pida "este_mes"
    tb = StationToolbox(
        repo, STATIONS["EST002-PALTAS"], "America/Lima", clock=lambda: datetime(2026, 10, 1, 9, 0, tzinfo=LIMA),
        question="Cuantas lecturas se dio en Todo el mesa de septiembre ?",
    )
    result = tb.execute("conteo_lecturas", {"periodo": "este_mes"})
    assert result["periodo"] == "rango" and result["desde"] == "2026-09-01 00:00"
    assert result["respuesta_directa"].startswith(
        "Lecturas de setiembre de 2026 en ESTACIÓN 2: 10 envíos de la estación, cada uno con los 6 sensores "
        "(60 lecturas en total)."
    )


def test_count_for_one_sensor():
    result = toolbox(FakeRepository(zeros=2)).execute("conteo_lecturas", {"periodo": "ultimos_7_dias", "sensor": "humedad_suelo"})
    assert result["respuesta_directa"].startswith(
        "Lecturas de los últimos 7 días en ESTACIÓN 2: 10 lecturas válidas de humedad del suelo (2 en 0 %)."
    )


def test_count_without_data():
    result = toolbox(FakeRepository(has_data=False)).execute("conteo_lecturas", {"periodo": "hoy"})
    assert result["respuesta_directa"].startswith("No hay lecturas de hoy (25 de setiembre de 2026) en ESTACIÓN 2.")


def test_wrong_place_a_few_words_later_is_fixed():
    from app.assistant.chat.service import name_sensor

    assert name_sensor("La humedad promedio del suelo fue 75.8 %.", "humedad ambiente") == "La humedad ambiente promedio fue 75.8 %."
    assert name_sensor("La humedad promedio del suelo fue 36.7 %.", "humedad del suelo") == "La humedad promedio del suelo fue 36.7 %."


@pytest.mark.parametrize(
    "question",
    ["como estuvo El partido ayer", "que dias es manana", "que pelicula se estrena Este mes", "dame eso"],
)
async def test_off_topic_or_unclear_questions_get_a_clarifying_question(repo, question):
    """Imagen 005: antes se respondía con datos de pH de la consulta anterior."""
    memory = InMemoryConversationStore(max_turns=4, ttl_seconds=60, max_sessions=10)
    memory.append("u:EST002-PALTAS:s", "ph de ayer", "Fue 7.7.", QueryContext("estadisticas_sensor", ("ph_suelo",), "2026-09-24", "2026-09-24"))
    llm = ScriptedLLM([])
    result = await make_service(llm, repo, memory).ask("EST002-PALTAS", question, "u", "s")
    assert result.answer.startswith("No entendí tu consulta o no está relacionada con la estación.")
    assert "¿Qué dato quieres consultar y de qué periodo?" in result.answer
    assert result.tools == [] and llm.requests == [] and repo.calls == []


async def test_real_follow_ups_still_use_context(repo):
    memory = InMemoryConversationStore(max_turns=4, ttl_seconds=60, max_sessions=10)
    memory.append("u:EST002-PALTAS:s", "ph de ayer", "Fue 7.7.", QueryContext("estadisticas_sensor", ("ph_suelo",), "2026-09-24", "2026-09-24"))
    llm = ScriptedLLM([LLMChunk(text="El pH del suelo mínimo fue 21.0.")])
    result = await make_service(llm, repo, memory).ask("EST002-PALTAS", "¿y el mínimo?", "u", "s")
    assert result.tools[0].arguments["sensor"] == "ph_suelo"


async def test_ambiguous_question_then_reply_answers_the_original(repo):
    memory = InMemoryConversationStore(max_turns=4, ttl_seconds=60, max_sessions=10)
    llm = ScriptedLLM([LLMChunk(text="La temperatura del suelo máxima de ayer fue 28.0 °C.")])
    service = make_service(llm, repo, memory)

    first = await service.ask("EST002-PALTAS", "cual fue la temperatura maxima de ayer", "u", "s")
    assert first.answer.startswith("¿Te refieres a la temperatura ambiente (del aire) o a la temperatura del suelo?")
    assert first.tools == [] and llm.requests == []

    second = await service.ask("EST002-PALTAS", "del suelo", "u", "s")
    assert [(t.name, t.arguments["sensor"], t.arguments["periodo"]) for t in second.tools] == [
        ("estadisticas_sensor", "temperatura_suelo", "ayer")
    ]
    assert second.answer == "La temperatura del suelo máxima de ayer fue 28.0 °C."
    # Ya respondida, la repregunta no queda pendiente
    assert memory.get_context("u:EST002-PALTAS:s").pending_question is None


async def test_alert_is_added_when_the_model_omits_it(repo):
    # pH promedio 24.46 → muy alcalino (alerta)
    llm = ScriptedLLM([LLMChunk(text="El promedio del pH del suelo fue de 24.46.")])
    events = [e async for e in make_service(llm, FakeRepository(alkaline_ph=True)).ask_stream("EST002-PALTAS", "promedio de ph de septiembre", "u", "s")]
    answer = events[-1].result.answer
    assert answer.startswith("El promedio del pH del suelo fue de 24.46.\n\n• pH promedio de 24.5: muy alcalino")
    assert "".join(e.text for e in events if e.type == "delta") == answer


async def test_alert_not_duplicated_when_model_recommends(repo):
    llm = ScriptedLLM([LLMChunk(text="El pH promedio fue 24.46; se recomienda acidificar el agua de riego.")])
    result = await make_service(llm, FakeRepository(alkaline_ph=True)).ask("EST002-PALTAS", "promedio de ph de septiembre", "u", "s")
    assert "•" not in result.answer
