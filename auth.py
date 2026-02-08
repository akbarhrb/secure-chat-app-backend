import bcrypt
from jose import jwt

SECRET_KEY = "CHANGE_THIS_SECRET"
ALGORITHM = "HS256"

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_token(user_id: int):
    return jwt.encode({"user_id": user_id}, SECRET_KEY, algorithm=ALGORITHM)
