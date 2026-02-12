from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi import Query
from sqlalchemy import ( func, or_, and_)
from sqlalchemy.orm import Session
from datetime import datetime
from auth import hash_password, verify_password, create_token
import os
import json
from sqlalchemy.orm import joinedload
from typing import Union, Optional, Any
import shutil

# --- Import database and models ---
from database import Base, engine, get_db
from models import User, Message

# --- Create tables ---
Base.metadata.create_all(bind=engine)


# ----------------- Schemas -----------------

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    public_key: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    public_id: str
    username: str
    email: str
    public_key: Optional[str] = None
    last_message: Any | None = None
    last_message_at: datetime | None = None

    class Config:
        from_attributes = True


class MessageRequest(BaseModel):
    sender_public_id: str
    receiver_public_id: str
    message: Union[str, dict]


class MessageResponse(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    message: Any | None = None
    file_url: str | None = None
    encrypted_key: str | None = None   # ADD THIS
    iv: str | None = None              # ADD THIS
    message_type: str
    created_at: datetime

    class Config:
        from_attributes = True

# --------- ADMIN RESPONSE MODELS ---------

class AdminUserResponse(BaseModel):
    id: int
    public_id: str            
    username: str
    email: str
    password_hash: str
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AdminMessageResponse(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    message_type: str
    file_url: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ----------------- App -----------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Upload Setup -----------------

UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ----------------- AUTH ROUTES -----------------

@app.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):

    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        public_key=data.public_key,
        is_admin=False
    )

    db.add(user)
    db.commit()

    return {"message": "User registered successfully"}


@app.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):

    user = db.query(User).filter(
        or_(User.email == data.email, User.username == data.email)
    ).first()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user.id)

    return {
        "token": token,
        "public_id": user.public_id,
        "is_admin": user.is_admin
    }

# ----------------- CHAT ROUTES -----------------

@app.get("/users", response_model=list[UserResponse])
def get_users(exclude_user_public_id: str = Query(...), db: Session = Depends(get_db)):
    # Convert UUID to internal numeric ID
    exclude_user = db.query(User).filter(User.public_id == exclude_user_public_id).first()
    if not exclude_user:
        raise HTTPException(status_code=404, detail="User not found")

    users = db.query(User).filter(User.id != exclude_user.id).all()
    response = []

    for user in users:
        last_msg = db.query(Message).filter(
            or_(
                and_(Message.sender_id == exclude_user.id, Message.receiver_id == user.id),
                and_(Message.sender_id == user.id, Message.receiver_id == exclude_user.id)
            )
        ).order_by(Message.created_at.desc()).first()

        display_msg = None
        if last_msg and last_msg.message:
            try:
                if last_msg.message.startswith('{'):
                    display_msg = json.loads(last_msg.message)
                else:
                    display_msg = last_msg.message
            except:
                display_msg = last_msg.message

        response.append({
            "public_id": user.public_id,
            "username": user.username,
            "email": user.email,
            "public_key": user.public_key,
            "last_message": display_msg,
            "last_message_at": last_msg.created_at if last_msg else None
        })

    response.sort(
        key=lambda x: x["last_message_at"].timestamp() if x["last_message_at"] else 0,
        reverse=True
    )

    return response

@app.get("/messages", response_model=list[dict])
def get_messages(
    user_public_id: str,
    contact_public_id: str,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.public_id == user_public_id).first()
    contact = db.query(User).filter(User.public_id == contact_public_id).first()

    if not user or not contact:
        raise HTTPException(status_code=404, detail="User not found")

    msgs = db.query(Message).filter(
        ((Message.sender_id == user.id) & (Message.receiver_id == contact.id)) |
        ((Message.sender_id == contact.id) & (Message.receiver_id == user.id))
    ).order_by(Message.created_at).all()

    result = []
    for m in msgs:
        msg_content = m.message
        if msg_content and isinstance(msg_content, str) and msg_content.startswith('{'):
            try:
                msg_content = json.loads(msg_content)
            except:
                pass

        result.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "receiver_id": m.receiver_id,
            "sender_public_id": db.query(User.public_id).filter(User.id == m.sender_id).scalar(),
            "receiver_public_id": db.query(User.public_id).filter(User.id == m.receiver_id).scalar(),
            "message": msg_content,
            "file_url": m.file_url,
            "encrypted_key": m.encrypted_key,
            "iv": m.iv,
            "message_type": m.message_type,
            "created_at": m.created_at
        })

    return result

@app.post("/messages")
def send_message(data: MessageRequest, db: Session = Depends(get_db)):

    # Convert UUIDs to internal IDs
    sender = db.query(User).filter(User.public_id == data.sender_public_id).first()
    receiver = db.query(User).filter(User.public_id == data.receiver_public_id).first()

    if not sender or not receiver:
        raise HTTPException(status_code=404, detail="Sender or receiver not found")

    # Store message: dict → JSON string, string → as-is
    stored_message = json.dumps(data.message) if isinstance(data.message, dict) else data.message

    msg = Message(
        sender_id=sender.id,
        receiver_id=receiver.id,
        message=stored_message,
        message_type="text"
    )

    db.add(msg)
    db.commit()

    return {"status": "ok"}

@app.post("/upload")
async def upload_file(
    sender_public_id: str = Form(...),
    receiver_public_id: str = Form(...),
    message_type: str = Form(...),  # "image" or "file"
    encrypted_key: str = Form(...), # RSA-encrypted AES key
    iv: str = Form(...),            # AES IV
    file: UploadFile = File(...),   # Frontend sends already encrypted file
    db: Session = Depends(get_db)
):

    # Convert UUIDs to internal IDs
    sender = db.query(User).filter(User.public_id == sender_public_id).first()
    receiver = db.query(User).filter(User.public_id == receiver_public_id).first()

    if not sender or not receiver:
        raise HTTPException(status_code=404, detail="Sender or receiver not found")

    # Save encrypted file
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    safe_filename = f"{timestamp}_{file.filename.replace(' ', '_')}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_url = f"http://localhost:8000/uploads/{safe_filename}"

    # Save message in DB
    new_msg = Message(
        sender_id=sender.id,
        receiver_id=receiver.id,
        file_url=file_url,
        encrypted_key=encrypted_key,
        iv=iv,
        message_type=message_type
    )

    db.add(new_msg)
    db.commit()

    return {
        "status": "ok",
        "url": file_url
    }

# ----------------- ADMIN ROUTES -----------------

@app.get("/admin/users", response_model=list[AdminUserResponse])
def admin_get_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.id.desc()).all()


@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, db: Session = Depends(get_db)):

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.query(Message).filter(
        (Message.sender_id == user_id) | (Message.receiver_id == user_id)
    ).delete()

    db.delete(user)
    db.commit()

    return {"status": "User deleted"}


@app.get("/admin/messages", response_model=list[AdminMessageResponse])
def admin_get_messages(db: Session = Depends(get_db)):
    return db.query(Message).order_by(Message.created_at.desc()).all()


@app.delete("/admin/messages/{message_id}")
def admin_delete_message(message_id: int, db: Session = Depends(get_db)):

    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    db.delete(msg)
    db.commit()

    return {"status": "Message deleted"}


@app.get("/admin/stats")
def admin_stats(db: Session = Depends(get_db)):

    return {
        "total_users": db.query(func.count(User.id)).scalar(),
        "total_messages": db.query(func.count(Message.id)).scalar(),
        "messages_today": db.query(func.count(Message.id)).filter(
            func.date(Message.created_at) == datetime.utcnow().date()
        ).scalar()
    }
