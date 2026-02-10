from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy import select, or_, and_, desc, func
from datetime import datetime
from auth import hash_password, verify_password, create_token  # your existing auth utils
from fastapi.staticfiles import StaticFiles
import os
import shutil

# ----------------- Database -----------------
DATABASE_URL = "sqlite:///./chat.db"  # Use SQLite for simplicity
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ----------------- Models -----------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)  # New Column
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    public_key = Column(String)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"))
    receiver_id = Column(Integer, ForeignKey("users.id"))
    message = Column(String, nullable=True) # Text content
    file_url = Column(String, nullable=True) # URL to the uploaded file/image
    message_type = Column(String, default="text") # "text", "image", or "file"
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ----------------- Schemas -----------------
class RegisterRequest(BaseModel):
    username: str  # Added
    email: str
    password: str
    public_key: str

class LoginRequest(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str  # Added
    email: str
    last_message: str | None = None
    last_message_at: datetime | None = None

    class Config:
        from_attributes = True

class MessageRequest(BaseModel):
    sender_id: int
    receiver_id: int
    message: str

class MessageResponse(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    message: str | None = None
    file_url: str | None = None
    message_type: str
    created_at: datetime
    class Config:
        orm_mode = True

# ----------------- App -----------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for development only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Create the physical folder
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# 2. Tell FastAPI to "serve" this folder at the /uploads URL
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ----------------- Routes -----------------
@app.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    # Check if email exists
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Check if username exists
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        public_key=data.public_key
    )
    db.add(user)
    db.commit()
    return {"message": "User registered successfully"}

@app.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    # Look for the user where the input matches either email OR username
    user = db.query(User).filter(
        or_(User.email == data.email, User.username == data.email)
    ).first()
    
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user.id)
    return {"token": token, "user_id": user.id}

@app.get("/users", response_model=list[UserResponse])
def get_users(exclude_user_id: int, db: Session = Depends(get_db)):
    users = db.query(User).filter(User.id != exclude_user_id).all()
    
    response = []
    for user in users:
        last_msg = db.query(Message).filter(
            or_(
                and_(Message.sender_id == exclude_user_id, Message.receiver_id == user.id),
                and_(Message.sender_id == user.id, Message.receiver_id == exclude_user_id)
            )
        ).order_by(Message.created_at.desc()).first()
        
        response.append({
            "id": user.id,
            "username": user.username,  # Added
            "email": user.email,
            "last_message": last_msg.message if last_msg else None,
            "last_message_at": last_msg.created_at if last_msg else None
        })
    
    response.sort(
        key=lambda x: x["last_message_at"].timestamp() if x["last_message_at"] else 0, 
        reverse=True
    )
    return response

@app.get("/public-key/{user_id}")
def get_public_key(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"public_key": user.public_key}

@app.get("/messages", response_model=list[MessageResponse])
def get_messages(user_id: int, contact_id: int, db: Session = Depends(get_db)):
    msgs = db.query(Message).filter(
        ((Message.sender_id == user_id) & (Message.receiver_id == contact_id)) |
        ((Message.sender_id == contact_id) & (Message.receiver_id == user_id))
    ).order_by(Message.created_at).all()
    return msgs

@app.post("/messages")
def send_message_api(data: MessageRequest, db: Session = Depends(get_db)):
    msg = Message(
        sender_id=data.sender_id,
        receiver_id=data.receiver_id,
        message=data.message
    )
    db.add(msg)
    db.commit()
    return {"status": "ok"}

@app.post("/upload")
async def upload_file(
    sender_id: int = Form(...),
    receiver_id: int = Form(...),
    message_type: str = Form(...), # "image" or "file"
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # 1. Create a unique filename to avoid overwriting (timestamp + original name)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    safe_filename = f"{timestamp}_{file.filename.replace(' ', '_')}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    file_url = f"http://localhost:8000/uploads/{safe_filename}"
    
    # 4. Save the message to the database
    new_msg = Message(
        sender_id=sender_id,
        receiver_id=receiver_id,
        message=None,           # No text content for a pure file upload
        file_url=file_url,
        message_type=message_type
    )
    
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    
    return {"status": "ok", "message_id": new_msg.id, "url": file_url}