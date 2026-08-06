import os
import datetime
import bcrypt
import jwt
from typing import Optional

# Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "vendra_jwt_secret_9988112233_superkey_length_32")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def check_password(password: str, hashed: str) -> bool:
    """Check a password against its hash using bcrypt."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def create_jwt_token(customer_id: str) -> str:
    """Create a stateless JWT token with 24h expiry."""
    payload = {
        "customer_id": customer_id,
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_jwt_token(token: str) -> Optional[str]:
    """Decode a stateless JWT token and return customer_id if valid."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload.get("customer_id")
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
