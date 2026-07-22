import asyncio
class SSEManager:
    def __init__(self):
        self.clients = []

    async def connet(self):
        queue = asyncio.Queue()
        self.clients.append(queue)
        return queue

    def disconnect(self, queue):
        if queue in self.clients:
            self.clients.remove(queue)

    async def broadcast(self, data):

        for client in self.clients:
            await client.put(data)

sse_manager = SSEManager()