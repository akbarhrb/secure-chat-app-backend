from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import Base, engine, SessionLocal
from models import User
from auth import hash_password, verify_password, create_token
from pydantic import BaseModel
from fastapi import WebSocket, WebSocketDisconnect
from websocket import connect, disconnect, send_message
from fastapi.middleware.cors import CORSMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI()

origins = ["*"]  # For development only, allow all origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Schemas ----------

class RegisterRequest(BaseModel):
    email: str
    password: str
    public_key: str

class LoginRequest(BaseModel):
    email: str
    password: str
    
class UserResponse(BaseModel):
    id: int
    email: str

    class Config:
        orm_mode = True


# ---------- Routes ----------

@app.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="User exists")

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        public_key=data.public_key
    )
    db.add(user)
    db.commit()
    return {"message": "User registered"}

@app.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user.id)
    return {"token": token, "user_id": user.id}

@app.get("/public-key/{user_id}")
def get_public_key(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"public_key": user.public_key}

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            receiver_id = data["receiver_id"]
            await send_message(receiver_id, data)
    except WebSocketDisconnect:
        disconnect(user_id)
@app.get("/users", response_model=list[UserResponse])
def get_users(
    exclude_user_id: int | None = None,
    db: Session = Depends(get_db)
):
    query = db.query(User)

    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)

    users = query.all()
    return users
