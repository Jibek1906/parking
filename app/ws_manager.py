from fastapi import WebSocket
from typing import List

class ScreenWebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.last_payment_plate: str = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        import asyncio
        to_remove = []
        async def send_safe(connection):
            try:
                await connection.send_json(message)
            except Exception:
                to_remove.append(connection)
        await asyncio.gather(*(send_safe(conn) for conn in self.active_connections))
        for conn in to_remove:
            self.disconnect(conn)

screen_ws_manager = ScreenWebSocketManager()
