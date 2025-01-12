from fastapi import APIRouter, HTTPException, WebSocket, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import Optional, List
import uuid
from datetime import datetime
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VideoGrant
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

router = APIRouter()



# MongoDB configuration
MONGO_URL = os.getenv("MONGO_URL")
client = AsyncIOMotorClient(MONGO_URL)
db = client.video_call_app

# Twilio configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_API_KEY = os.getenv("TWILIO_API_KEY")
TWILIO_API_SECRET = os.getenv("TWILIO_API_SECRET")

# Models
class User(BaseModel):
    id: str
    name: str
    email: str
    created_at: datetime = datetime.now()

class Room(BaseModel):
    id: str
    name: str
    created_by: str
    participants: List[str] = []
    created_at: datetime = datetime.now()

class Message(BaseModel):
    id: str
    room_id: str
    sender_id: str
    content: str
    type: str  # 'text' or 'file'
    file_url: Optional[str]
    created_at: datetime = datetime.now()

# Database operations
async def get_user(email: str):
    return await db.users.find_one({"email": email})

async def create_user(user: User):
    user_dict = user.dict()
    await db.users.insert_one(user_dict)
    return user_dict

async def get_room(room_id: str):
    return await db.rooms.find_one({"id": room_id})

async def create_room(room: Room):
    room_dict = room.dict()
    await db.rooms.insert_one(room_dict)
    return room_dict
async def add_participant(room_id: str, user_id: str):
    await db.rooms.update_one(
        {"id": room_id},
        {"$addToSet": {"participants": user_id}}
    )

async def remove_participant(room_id: str, user_id: str):
    await db.rooms.update_one(
        {"id": room_id},
        {"$pull": {"participants": user_id}}
    )

async def save_message(message: Message):
    message_dict = message.dict()
    await db.messages.insert_one(message_dict)
    return message_dict

async def get_room_messages(room_id: str, limit: int = 50):
    messages = await db.messages.find(
        {"room_id": room_id}
    ).sort("created_at", -1).limit(limit).to_list(length=limit)
    return messages

# Dependencies
async def get_current_user(token: str):
    # In a real application, implement proper JWT validation
    # This is a simplified version
    user = await get_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid authentication")
    return user

# Routes
@router.post("/api/users")
async def register_user(user: User):
    existing_user = await get_user(user.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    return await create_user(user)

@router.post("/api/rooms")
async def create_new_room(room: Room, current_user: User = Depends(get_current_user)):
    room.created_by = current_user["id"]
    room.participants.append(current_user["id"])
    return await create_room(room)

@router.get("/api/rooms/{room_id}")
async def get_room_details(room_id: str, current_user: User = Depends(get_current_user)):
    room = await get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room

@router.post("/api/rooms/{room_id}/join")
async def join_room(room_id: str, current_user: User = Depends(get_current_user)):
    room = await get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    await add_participant(room_id, current_user["id"])
    return {"message": "Joined room successfully"}

@router.post("/api/rooms/{room_id}/leave")
async def leave_room(room_id: str, current_user: User = Depends(get_current_user)):
    await remove_participant(room_id, current_user["id"])
    return {"message": "Left room successfully"}

@router.get("/api/token")
async def generate_token(request: Request, room_id: str):
    temp_user_id = str(uuid.uuid4())
    
    token = AccessToken(
        TWILIO_ACCOUNT_SID,
        TWILIO_API_KEY,
        TWILIO_API_SECRET,
        identity=temp_user_id
    )
    
    video_grant = VideoGrant(room=room_id)
    token.add_grant(video_grant)
    
    return {
        "token": token.to_jwt(),
        "roomName": room_id,
        "userId": temp_user_id
    }


@router.get("/api/rooms/{room_id}/messages")
async def get_messages(
    room_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    messages = await get_room_messages(room_id, limit)
    return messages

@router.post("/api/rooms/{room_id}/messages")
async def send_message(
    room_id: str,
    message: Message,
    current_user: User = Depends(get_current_user)
):
    message.sender_id = current_user["id"]
    message.room_id = room_id
    return await save_message(message)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_name: str):
        await websocket.accept()
        if room_name not in self.active_connections:
            self.active_connections[room_name] = set()
        self.active_connections[room_name].add(websocket)

    def disconnect(self, websocket: WebSocket, room_name: str):
        if room_name in self.active_connections:
            self.active_connections[room_name].discard(websocket)

    async def broadcast(self, message: dict, room_name: str):
        if room_name in self.active_connections:
            for connection in self.active_connections[room_name]:
                await connection.send_json(message)

manager = ConnectionManager()

@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await manager.connect(websocket, room_id)
    try:
        while True:
            data = await websocket.receive_json()
            await manager.broadcast(data, room_id)
    except Exception as e:
        manager.disconnect(websocket, room_id)

@router.websocket("/ws/{room_name}")
async def websocket_endpoint(websocket: WebSocket, room_name: str):
    await manager.connect(websocket, room_name)
    try:
        while True:
            data = await websocket.receive_json()
            await manager.broadcast(data, room_name)
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)