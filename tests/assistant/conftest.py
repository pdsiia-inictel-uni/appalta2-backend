# Los tests del asistente usan dobles falsos: no tocan la BD ni Ollama.
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.assistant.data.repository import DailyStats, Reading, SensorStats, Station
from app.assistant.llm.base import LLMChunk, ToolCall

LIMA = ZoneInfo("America/Lima")
NOW = datetime(2026, 9, 25, 15, 30, tzinfo=LIMA)

STATIONS = {
    "EST001-PALTAS": Station(1, "EST001-PALTAS", "ESTACIÓN 1"),
    "EST002-PALTAS": Station(2, "EST002-PALTAS", "ESTACIÓN 2"),
}


class FakeRepository:
    """Registra cada llamada para verificar el filtro por estación."""

    def __init__(
        self,
        has_data: bool = True,
        discarded: int = 0,
        zeros: int = 0,
        latest_value: float | None = None,
        alkaline_ph: bool = False,
    ):
        """Por defecto los valores son normales para la palta (sin alertas); alkaline_ph=True genera
        un pH en exceso para probar las alertas."""
        self.has_data = has_data
        self.alkaline_ph = alkaline_ph
        self.discarded = discarded
        self.zeros = zeros
        self.latest_value = latest_value
        self.calls: list[tuple[str, int]] = []

    def get_station(self, code):
        return STATIONS.get(code)

    def latest_readings(self, station_id, sensors):
        self.calls.append(("latest_readings", station_id))
        ts = int(NOW.timestamp()) - 600
        if not self.has_data:
            return []
        return [
            Reading(s.db_code, self._latest(s, i), ts)
            for i, s in enumerate(sensors)
        ]

    def _latest(self, sensor, i):
        if self.latest_value is not None:
            return self.latest_value
        return 6.2 if sensor.db_code == "soil_ph" and not self.alkaline_ph else 20.0 + i

    def sensor_stats(self, station_id, sensor, start_ts, end_ts):
        self.calls.append(("sensor_stats", station_id))
        if not self.has_data:
            return SensorStats(count=0, discarded=self.discarded, zeros=0)
        if sensor.db_code == "soil_ph" and not self.alkaline_ph:
            return SensorStats(
                10, self.discarded, self.zeros,
                6.12, 5.9, start_ts + 60, 6.3, start_ts + 3600, 6.0, start_ts, 6.2, end_ts - 60,
            )  # fmt: skip
        return SensorStats(
            10, self.discarded, self.zeros,
            24.456, 21.0, start_ts + 60, 28.04, start_ts + 3600, 22.0, start_ts, 25.0, end_ts - 60,
        )  # fmt: skip

    def daily_stats(self, station_id, sensor, start_ts, end_ts, tz):
        self.calls.append(("daily_stats", station_id))
        return [DailyStats(datetime.fromtimestamp(start_ts, LIMA).date(), 24.0, 21.0, 28.0)]

    def last_reading(self, station_id, sensor):
        self.calls.append(("last_reading", station_id))
        return Reading(sensor.db_code, 31.94, int(datetime(2026, 9, 18, 13, 56, tzinfo=LIMA).timestamp()))

    def count_measurements(self, station_id, start_ts, end_ts):
        self.calls.append(("count_measurements", station_id))
        return 10 if self.has_data else 0


class ScriptedLLM:
    """LLM falso: devuelve respuestas predefinidas y guarda los mensajes recibidos."""

    def __init__(self, script: list[LLMChunk]):
        self.script = list(script)
        self.requests: list[dict] = []

    async def stream_chat(self, messages, tools=None):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools})
        chunk = self.script.pop(0)
        # Simula streaming partiendo el texto en dos fragmentos.
        if chunk.text and not chunk.tool_calls:
            mid = len(chunk.text) // 2
            yield LLMChunk(text=chunk.text[:mid])
            yield LLMChunk(text=chunk.text[mid:])
        else:
            yield chunk

    async def is_ready(self):
        return True

    async def aclose(self):
        pass


def tool_call(name: str, **arguments) -> LLMChunk:
    return LLMChunk(tool_calls=[ToolCall(name, arguments)])


@pytest.fixture
def repo():
    return FakeRepository()
