from fastapi import APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import sqlite3
import datetime

router = APIRouter()



# Database initialization
def init_db():
    conn = sqlite3.connect('calls.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_address TEXT NOT NULL,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP,
            duration REAL,
            payment REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

class CallStart(BaseModel):
    user_address: str = Field(..., min_length=42, max_length=42)

class CallEnd(BaseModel):
    user_address: str = Field(..., min_length=42, max_length=42)
    duration: float = Field(..., ge=0)
    payment: float = Field(..., ge=0)

@router.get("/")
async def root():
    return {"message": "Video calling backend is running"}

@router.post("/reset-user-calls")
async def reset_user_calls(call_data: CallStart):
    try:
        conn = sqlite3.connect('calls.db')
        c = conn.cursor()
        
        # End any ongoing calls for this user
        c.execute('''
            UPDATE calls 
            SET end_time = ?,
                duration = 0,
                payment = 0
            WHERE user_address = ? 
            AND end_time IS NULL
        ''', (datetime.datetime.now(), call_data.user_address))
        
        conn.commit()
        return {"status": "success", "message": "User calls reset successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/start-call")
async def start_call(call_data: CallStart):
    try:
        conn = sqlite3.connect('calls.db')
        c = conn.cursor()
        
        # Check for active calls
        c.execute('''
            SELECT id FROM calls 
            WHERE user_address = ? AND end_time IS NULL
        ''', (call_data.user_address,))
        
        if c.fetchone():
            raise HTTPException(status_code=400, detail="User already has an ongoing call")
        
        # Start new call
        c.execute('''
            INSERT INTO calls (user_address, start_time)
            VALUES (?, ?)
        ''', (call_data.user_address, datetime.datetime.now()))
        
        conn.commit()
        return {"status": "success", "message": "Call started successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/end-call")
async def end_call(call_data: CallEnd):
    try:
        conn = sqlite3.connect('calls.db')
        c = conn.cursor()
        
        c.execute('''
            UPDATE calls 
            SET end_time = ?,
                duration = ?,
                payment = ?
            WHERE user_address = ? 
            AND end_time IS NULL
        ''', (
            datetime.datetime.now(),
            call_data.duration,
            call_data.payment,
            call_data.user_address
        ))
        
        if c.rowcount == 0:
            raise HTTPException(status_code=404, detail="No active call found for this user")
        
        conn.commit()
        return {"status": "success", "message": "Call ended successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)