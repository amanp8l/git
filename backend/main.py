from fastapi import FastAPI, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
import httpx
from typing import Optional, List
import os
import random
import hashlib
from datetime import datetime, timedelta
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from bson import ObjectId
from routes import call_routes
from routes import video_call
from routes import metamask
# Load environment variables (put these in .env file)
SMS_API_KEY = os.getenv("SMS_API_KEY", "")
MONGO_URI = os.getenv("MONGO_URI", "")

app = FastAPI()
app.include_router(call_routes.router, prefix="")
app.include_router(video_call.router, prefix="")
app.include_router(metamask.router, prefix="")
origins = [
    "http://localhost",
    "http://127.0.0.1:5500",  # Example for React frontend
    "https://your-frontend-domain.com"  # Add your specific frontend domains
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows specified domains
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods
    allow_headers=["*"],  # Allows all headers
)


SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")  # Change in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: str

class LoginRequest(BaseModel):
    phone: str
    password: str

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise credentials_exception
    user["_id"] = str(user["_id"])  # Convert ObjectId to string
    return user

# MongoDB Connection
client = AsyncIOMotorClient(MONGO_URI)
db = client.user_database

# In-memory OTP store (replace with Redis in production)
otp_store = {}

# Models
class PhoneNumber(BaseModel):
    phone: str

class OTPVerify(BaseModel):
    phone: str
    otp: str

class UserCreate(BaseModel):
    name: str
    phone: str
    user_type: str  # developer/customer
    password: str

class UserUpdate(BaseModel):
    rate: Optional[float] = None
    live_status: Optional[bool] = None
    wallet_balance: Optional[float] = None
    description: Optional[str] = None
    skills: Optional[List[str]] = None
    
    class Config:
        extra = "forbid"

# Helper functions
async def get_user_by_phone(phone: str):
    return await db.users.find_one({"phone": phone})

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# Routes
@app.get("/")
async def read_root():
    return {"message": "Hello World"}

@app.post("/send-otp")
async def send_otp(phone_data: PhoneNumber):
    # Generate 6-digit OTP
    otp = str(random.randint(100000, 999999))
    
    # Store OTP with expiration
    otp_store[phone_data.phone] = {
        "otp": otp,
        "expires": datetime.now() + timedelta(minutes=5)
    }
    
    # Send OTP via SMS
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://www.fast2sms.com/dev/bulkV2",
                headers={
                    "authorization": SMS_API_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "route": "otp",
                    "variables_values": otp,
                    "numbers": phone_data.phone
                }
            )
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to send OTP")
        except Exception as e:
            raise HTTPException(status_code=500, detail="SMS service error")
    
    return {"message": "OTP sent successfully"}

@app.post("/verify-otp")
async def verify_otp(verify_data: OTPVerify):
    stored_data = otp_store.get(verify_data.phone)
    if not stored_data:
        raise HTTPException(status_code=400, detail="No OTP found for this number")
    
    if datetime.now() > stored_data["expires"]:
        del otp_store[verify_data.phone]
        raise HTTPException(status_code=400, detail="OTP expired")
    
    if stored_data["otp"] != verify_data.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    
    # Clear OTP after successful verification
    del otp_store[verify_data.phone]
    return {"message": "OTP verified successfully"}

@app.post("/register")
async def register_user(user_data: UserCreate):
    # Check if user already exists
    existing_user = await get_user_by_phone(user_data.phone)
    if existing_user:
        raise HTTPException(status_code=400, detail="Phone number already registered")
    
    # Create user document
    user = {
        "name": user_data.name,
        "phone": user_data.phone,
        "user_type": user_data.user_type,
        "password": hash_password(user_data.password),
        "phone_verified": True,
        "created_at": datetime.now(),
        "wallet_balance": 0,
        "live_status": False
    }
    
    result = await db.users.insert_one(user)
    return {"message": "User registered successfully", "user_id": str(result.inserted_id)}

# @app.put("/users/{user_id}")
# async def update_user(user_id: str, user_update: UserUpdate):
#     update_data = user_update.dict(exclude_unset=True)
#     result = await db.users.update_one(
#         {"_id": user_id},
#         {"$set": update_data}
#     )
    
#     if result.modified_count == 0:
#         raise HTTPException(status_code=404, detail="User not found")
    
#     return {"message": "User updated successfully"}

# @app.get("/users/{user_id}")
# async def get_user_profile(user_id: str):
#     user = await db.users.find_one({"_id": user_id})
#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")
    
#     # Convert ObjectId to string for JSON serialization
#     user["_id"] = str(user["_id"])
#     return user


@app.post("/login", response_model=TokenResponse)
async def login(login_data: LoginRequest):
    # Find user by phone
    user = await db.users.find_one({"phone": login_data.phone})
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid phone number or password"
        )
    
    # Verify password
    hashed_password = hash_password(login_data.password)
    if user["password"] != hashed_password:
        raise HTTPException(
            status_code=401,
            detail="Invalid phone number or password"
        )
    
    # Create access token
    access_token = create_access_token(
        data={"sub": str(user["_id"]), "phone": user["phone"]}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": str(user["_id"])
    }

# Example protected route
@app.get("/protected")
async def protected_route(current_user: dict = Depends(get_current_user)):
    return {"message": "This is a protected route", "user": current_user["phone"]}


@app.get("/users/me")
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    return current_user

@app.put("/users/me")
async def update_my_profile(
    user_update: UserUpdate,
    current_user: dict = Depends(get_current_user)
):
    update_data = user_update.dict(exclude_unset=True)
    
    # Update user in database
    result = await db.users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$set": update_data}
    )
        
    if result.modified_count == 0:
        raise HTTPException(status_code=400, detail="Update failed")
    
    # Get updated user data
    updated_user = await db.users.find_one({"_id": ObjectId(current_user["_id"])})
    updated_user["_id"] = str(updated_user["_id"])
    
    return updated_user


@app.get("/developers")
async def get_developers():
    # Find all developers (users with user_type = "developer")
    cursor = db.users.find({"user_type": "developer"})
    developers = []
    
    async for dev in cursor:
        try:
            # Convert ObjectId to string for JSON serialization
            dev_id = str(dev["_id"])
            
            # Create developer object with default values for missing fields
            developer = {
                "id": dev_id,
                "name": dev.get("name", "Anonymous Developer"),  # Default name if missing
                "skills": dev.get("skills", []),  # Empty list if skills missing
                "live_status": dev.get("live_status", False),  # Offline by default
                "rate": dev.get("rate", 0),  # 0 if rate is missing
                "description": dev.get("description", "No description available"),  # Default description
                "phone": dev.get("phone", ""),  # Empty string if phone missing
            }
            
            developers.append(developer)
            
        except Exception as e:
            print(f"Error processing developer {dev.get('_id', 'unknown')}: {str(e)}")
            continue  # Skip this developer and continue with others
    
    return developers