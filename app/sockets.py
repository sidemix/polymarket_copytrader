# app/sockets.py
from fastapi import APIRouter
from app.events import manager

# app/sockets.py — FINAL WORKING VERSION
from fastapi import WebSocket   # ← THIS WAS MISSING
from app.events import manager

@manager.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except:
        manager.disconnect(websocket)

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except:
        manager.disconnect(websocket)