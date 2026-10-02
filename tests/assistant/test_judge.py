import json

import httpx
import pytest

from scripts.assistant.judge import CALIBRATION, JUDGE_SCHEMA, Judge

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def judge_replying(scores: dict, captured: list | None = None) -> Judge:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if captured is not None:
            captured.append(body)
        return httpx.Response(200, json={"message": {"content": json.dumps(scores)}})

    return Judge("http://ollama", "juez", transport=httpx.MockTransport(handler))


async def test_verdict_is_computed_by_code_from_scores():
    judge = judge_replying({"motivo": "ok", "fidelidad": 5, "pertinencia": 4, "alcance": 5, "claridad": 2})
    verdict = await judge.evaluate("¿Máxima?", [{"maximo": {"valor": 35.6}}], "Fue 35.6 °C.")
    assert verdict.aprobado is True  # la claridad baja no bloquea
    await judge.aclose()


@pytest.mark.parametrize("criterion", ["fidelidad", "pertinencia", "alcance"])
async def test_low_blocking_score_rejects(criterion):
    scores = {"motivo": "x", "fidelidad": 5, "pertinencia": 5, "alcance": 5, "claridad": 5} | {criterion: 3}
    verdict = await judge_replying(scores).evaluate("q", [], "a")
    assert verdict.aprobado is False


async def test_scores_are_clamped_and_request_uses_schema():
    captured: list = []
    judge = judge_replying({"motivo": "x", "fidelidad": 9, "pertinencia": 0, "alcance": 5, "claridad": 5}, captured)
    verdict = await judge.evaluate("¿Clima?", [], "Solo puedo informar sobre ESTACIÓN 2.")
    assert (verdict.fidelidad, verdict.pertinencia) == (5, 1)
    request = captured[0]
    assert request["format"] == JUDGE_SCHEMA and request["options"]["temperature"] == 0
    assert "(no consultó datos)" in request["messages"][1]["content"]


def test_calibration_set_has_good_and_bad_examples():
    assert {c["should_pass"] for c in CALIBRATION} == {True, False}
