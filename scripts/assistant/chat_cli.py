"""Chat interactivo en consola contra una estación, sin HTTP ni autenticación.

Uso:  python -m scripts.assistant.chat_cli --station EST001-PALTAS
"""

import argparse
import asyncio
import logging
import uuid

from app.assistant.config import get_settings
from app.assistant.container import AssistantContainer


async def main(station: str) -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.WARNING)
    container = AssistantContainer(settings)
    service = container.chat_service
    session = uuid.uuid4().hex
    if not await service.station_exists(station):
        print(f"La estación {station} no existe.")
        return

    print(f"AgriSense · {station} · modelo {settings.llm_model}")
    print("Escribe 'salir' para terminar, 'nuevo' para reiniciar la conversación.\n")
    try:
        while True:
            try:
                question = input("Tú: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question:
                continue
            if question.lower() == "salir":
                break
            if question.lower() == "nuevo":
                session = uuid.uuid4().hex
                print("(conversación reiniciada)\n")
                continue

            print("AgriSense: ", end="", flush=True)
            async for event in service.ask_stream(station, question, "cli", session):
                if event.type == "delta":
                    print(event.text, end="", flush=True)
                elif event.type == "reset":
                    print("\rAgriSense: ", end="", flush=True)
                elif event.type == "tool":
                    print(f"[consultando {event.tool}] ", end="", flush=True)
                elif event.type == "done":
                    r = event.result
                    tools = ", ".join(f"{t.name}{t.arguments}" for t in r.tools) or "ninguna"
                    print(f"\n  ↳ {r.duration_ms / 1000:.1f} s · herramientas: {tools}\n")
    finally:
        await container.aclose()


if __name__ == "__main__":
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station", default="EST001-PALTAS")
    asyncio.run(main(parser.parse_args().station))
