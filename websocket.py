from fastapi import WebSocket

active_connections = {}

async def connect(user_id: int, websocket: WebSocket):
    await websocket.accept()
    active_connections[user_id] = websocket

def disconnect(user_id: int):
    active_connections.pop(user_id, None)

async def send_message(receiver_id: int, message: dict):
    ws = active_connections.get(receiver_id)
    if ws:
        await ws.send_json(message)
