import asyncio

class SSEManager:

    def __init__(self):

        self.clients = []

    async def connect(
        self,
        stations: set[str] | None = None
    ):

        queue = asyncio.Queue()

        self.clients.append({

            "queue": queue,

            "stations": stations

        })

        print("connect self.clients:", self.clients)
        return queue

    def disconnect(
        self,
        queue
    ):
        print("desconectando...")
        print("self.clients:", self.clients)
        self.clients = [

            client

            for client in self.clients

            if client["queue"] != queue

        ]

    async def broadcast(
        self,
        station_code: str,
        data
    ):
        print("self.clients:", self.clients)
        print("station_code:", station_code)

        for client in self.clients:

            subscriptions = client["stations"]

            if (
                subscriptions is None or
                station_code in subscriptions
            ):

                await client["queue"].put(data)


sse_manager = SSEManager()

