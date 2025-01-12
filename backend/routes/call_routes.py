# call_routes.py
from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from typing import Dict, Set
import json
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
import os
from bson import ObjectId
router = APIRouter()

MONGO_URI = os.getenv("MONGO_URI", "")
client = AsyncIOMotorClient(MONGO_URI)
db = client.user_database
class CallRequest(BaseModel):
    caller_id: str
    receiver_id: str
class CallConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.active_calls: Dict[str, dict] = {}  # Add this to track calls
    
    def add_active_call(self, call_id: str, caller_id: str, receiver_id: str):
        self.active_calls[call_id] = {
            "caller_id": caller_id,
            "receiver_id": receiver_id,
            "status": "pending"
        }
    
    def remove_active_call(self, call_id: str):
        if call_id in self.active_calls:
            del self.active_calls[call_id]
    async def send_message(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)
    def __init__(self):
        # Store active connections: user_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # Store ongoing calls: call_id -> {caller_id, receiver_id, status}
        self.active_calls: Dict[str] = {}
        
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        
    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            
    async def send_call_request(self, caller_id: str, receiver_id: str, call_id: str):
        if receiver_id in self.active_connections:
            message = {
                "type": "call_request",
                "call_id": call_id,
                "caller_id": caller_id,
                "caller_name": await self.get_user_name(caller_id)
            }
            await self.active_connections[receiver_id].send_json(message)
            
    async def send_call_accepted(self, call_id: str, caller_id: str):
        if caller_id in self.active_connections:
            message = {
                "type": "call_accepted",
                "call_id": call_id,
                "room_url": f"/call-room/{call_id}"
            }
            await self.active_connections[caller_id].send_json(message)
            
    async def get_user_name(self, user_id: str):
        # Get user name from database
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        return user.get("name", "Unknown User")

manager = CallConnectionManager()

@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_json()
            print(f"Received message from {user_id}: {data}")
            
            if data["type"] == "call_request":
                # Handle incoming call request
                await manager.send_message(
                    data["receiver_id"],
                    {
                        "type": "call_request",
                        "call_id": str(ObjectId()),
                        "caller_id": user_id,
                        "caller_name": data.get("caller_name", "Unknown User")
                    }
                )
            
            elif data["type"] == "call_accepted":
                # Handle call acceptance
                await manager.send_message(
                    data["caller_id"],
                    {
                        "type": "call_accepted",
                        "call_id": data["call_id"],
                        "room_url": f"/call-room/?id={data['call_id']}"
                    }
                )
            
            elif data["type"] == "call_declined":
                # Handle call decline
                call_id = data["call_id"]
                # Find the original caller and send them the decline message
                # You might need to store call information in a database to track this
                # For now, we'll broadcast to all connections
                for connection_id in manager.active_connections:
                    if connection_id != user_id:
                        await manager.send_message(
                            connection_id,
                            {
                                "type": "call_declined",
                                "call_id": call_id,
                                "caller_id": user_id
                            }
                        )
                
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        print(f"Error in websocket connection for user {user_id}: {str(e)}")
        manager.disconnect(user_id)

@router.post("/api/initiate-call")
async def initiate_call(request: CallRequest):
    try:
        caller = await db.users.find_one({"_id": ObjectId(request.caller_id)})
        caller_name = caller.get("name", "Unknown User") if caller else "Unknown User"
        
        call_id = str(ObjectId())
        
        # Track the call
        manager.add_active_call(call_id, request.caller_id, request.receiver_id)
        
        await manager.send_message(
            request.receiver_id,
            {
                "type": "call_request",
                "call_id": call_id,
                "caller_id": request.caller_id,
                "caller_name": caller_name
            }
        )
        return {"call_id": call_id, "status": "success"}
    except Exception as e:
        print(f"Error initiating call: {str(e)}")
        return {"status": "error", "message": str(e)}