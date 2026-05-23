import os
import time
from datetime import datetime

import requests
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import Message, SessionLocal, User, get_db, init_db


app = FastAPI(title="Chat Bro API")
BOT_USERNAME = "chatbro"
BOT_PASSWORD_HASH = "bot-account-cannot-login"


def load_local_env_value(name: str) -> str:
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        return ""

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    return ""


# Gemini configuration:
# Set the key in your shell or local .env file as GEMINI_API_KEY.
# Example PowerShell: $env:GEMINI_API_KEY="your-key-here"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip() or load_local_env_value("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip() or load_local_env_value("GEMINI_MODEL") or "gemini-2.5-flash"
USER_GEMINI_ERRORS: dict[int, str] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str


class MessageCreateRequest(BaseModel):
    sender_id: int
    content: str
    conversation_id: str | None = None


class MessageResponse(BaseModel):
    id: int
    user_id: int
    sender_id: int
    sender_username: str
    role: str
    content: str
    message_content: str
    conversation_id: str
    created_at: datetime


class GeminiSettingsRequest(BaseModel):
    user_id: int
    api_key: str
    model: str = GEMINI_MODEL


class GeminiSettingsResponse(BaseModel):
    configured: bool
    model: str
    source: str
    last_error: str | None = None


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        get_or_create_bot_user(db)
    finally:
        db.close()


def normalize_username(username: str) -> str:
    return username.strip().lower()


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_context.verify(password, password_hash)


def default_conversation_id(user_id: int) -> str:
    return f"default-{user_id}"


def get_or_create_bot_user(db: Session) -> User:
    bot = db.query(User).filter(User.username == BOT_USERNAME).first()
    if bot:
        return bot

    bot = User(username=BOT_USERNAME, password_hash=BOT_PASSWORD_HASH)
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return bot


def message_to_response(message: Message) -> MessageResponse:
    content = message.message_content or message.content
    return MessageResponse(
        id=message.id,
        user_id=message.user_id or message.sender_id,
        sender_id=message.sender_id,
        sender_username=message.sender.username,
        role=message.role or "user",
        content=content,
        message_content=content,
        conversation_id=message.conversation_id or default_conversation_id(message.user_id or message.sender_id),
        created_at=message.created_at,
    )


def get_recent_conversation(
    db: Session,
    user_id: int,
    conversation_id: str,
    limit: int = 12,
) -> list[Message]:
    return (
        db.query(Message)
        .filter(Message.user_id == user_id, Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )[::-1]


def build_rule_based_reply(username: str, content: str, history: list[Message]) -> str:
    lowered = content.lower()
    compact = lowered.replace(" ", "")
    is_hebrew = any("\u0590" <= character <= "\u05ff" for character in content)
    recent_assistant_texts = [
        (message.message_content or message.content)
        for message in history
        if message.role == "assistant"
    ][-3:]

    if "ספרד" in content and any(word in content for word in ["בירה", "עיר הבירה"]):
        reply = "עיר הבירה של ספרד היא מדריד."
    elif "ישראל" in content and any(word in content for word in ["בירה", "עיר הבירה"]):
        reply = "עיר הבירה של ישראל היא ירושלים."
    elif "צרפת" in content and any(word in content for word in ["בירה", "עיר הבירה"]):
        reply = "עיר הבירה של צרפת היא פריז."
    elif "איטליה" in content and any(word in content for word in ["בירה", "עיר הבירה"]):
        reply = "עיר הבירה של איטליה היא רומא."
    elif "גרמניה" in content and any(word in content for word in ["בירה", "עיר הבירה"]):
        reply = "עיר הבירה של גרמניה היא ברלין."
    elif "hi" in lowered and any(phrase in compact for phrase in ["מההואאומר", "מהזהאומר", "מההמשמעות"]):
        reply = 'המילה "hi" באנגלית היא ברכת שלום, כמו "היי" או "שלום".'
    elif any(word in lowered for word in ["hello", "hi", "hey", "shalom"]):
        reply = "היי, אני כאן. במה תרצה שאעזור?" if is_hebrew else "Hey, I am here. What are we building or fixing today?"
    elif any(word in lowered for word in ["build", "code", "python", "fastapi", "streamlit", "sqlite"]):
        reply = (
            "Nice. Give me the feature goal and the current behavior, and I will help you shape the next step."
        )
    elif "?" in content:
        reply = (
            "שאלה טובה. אם תרצה, אפשר לנסח אותה עם עוד קצת הקשר ואענה בצורה מדויקת יותר."
            if is_hebrew
            else "Good question. If I miss something, try rephrasing it with a little more context."
        )
    elif any(word in lowered for word in ["thanks", "thank you", "thank"]):
        reply = "You got it."
    elif any(word in lowered for word in ["help", "stuck", "error", "bug"]):
        reply = "Send me the exact error and what you tried. I will help narrow it down."
    elif any(word in lowered for word in ["what can you do", "capabilities"]):
        reply = (
            "I can keep this chat session separate per user, store the conversation, and respond with basic guidance. "
            "The backend owner controls the shared Gemini connection."
        )
    else:
        reply = (
            "אני איתך. ספר לי מה המטרה, ואעזור לך להתקדם אליה."
            if is_hebrew
            else "I am with you. Tell me the outcome you want, and I will help you move toward it."
        )

    if reply in recent_assistant_texts:
        return "Let me take that from a different angle. What result would make this feel solved for you?"
    return reply


def should_send_to_gemini_history(message: Message) -> bool:
    text = (message.message_content or message.content or "").lower()
    blocked_fragments = [
        "gemini_api_key",
        "api key",
        "מפתח api",
        "יכולות שלי מוגבלות",
        "built-in mode",
        "backend owner",
    ]
    return not any(fragment in text for fragment in blocked_fragments)


def build_gemini_payload(username: str, content: str, history: list[Message]) -> dict:
    instruction = (
        "You are Chat Bro, a friendly, concise chatbot inside a multi-user chat product. "
        "Respond directly to the current user, keep context for this session, avoid repeating yourself, "
        "do not ask for details the user already provided, and ask follow-up questions only when useful. "
        "Answer in the same language as the user. If the user writes Hebrew, answer in natural Hebrew. "
        "For Hebrew replies, write right-to-left friendly Hebrew without mixing English unless needed. "
        "Never mention API keys, backend configuration, Gemini configuration, or implementation details. "
        "If a question is simple factual knowledge, answer it directly."
    )
    contents = [
        {
            "role": "user",
            "parts": [{"text": f"System instruction: {instruction}\nCurrent username: {username}"}],
        }
    ]

    clean_history = [message for message in history[-16:] if should_send_to_gemini_history(message)][-10:]
    for message in clean_history:
        role = "model" if message.role == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": message.message_content or message.content}]})

    contents.append({"role": "user", "parts": [{"text": content}]})
    return {"contents": contents}


def get_gemini_settings(user_id: int | None = None) -> tuple[str, str, str]:
    return GEMINI_API_KEY, GEMINI_MODEL, "server"


def generate_gemini_reply(
    user_id: int,
    username: str,
    content: str,
    history: list[Message],
) -> str | None:
    api_key, model, _source = get_gemini_settings(user_id)
    if not api_key:
        return None

    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json=build_gemini_payload(username, content, history),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text_parts = [part.get("text", "") for part in parts if part.get("text")]
        reply = "\n".join(text_parts).strip()
        USER_GEMINI_ERRORS.pop(user_id, None)
        return reply or None
    except requests.RequestException as exc:
        USER_GEMINI_ERRORS[user_id] = str(exc)
        return None


def generate_bot_reply(user_id: int, username: str, content: str, history: list[Message]) -> str:
    gemini_reply = generate_gemini_reply(user_id, username, content, history)
    if gemini_reply:
        return gemini_reply
    return build_rule_based_reply(username, content, history)


def save_message(
    db: Session,
    user_id: int,
    sender_id: int,
    content: str,
    role: str,
    conversation_id: str,
) -> Message:
    message = Message(
        user_id=user_id,
        sender_id=sender_id,
        role=role,
        content=content,
        message_content=content,
        conversation_id=conversation_id,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def create_background_bot_reply(
    user_id: int,
    username: str,
    content: str,
    conversation_id: str,
) -> None:
    time.sleep(0.8)
    db = SessionLocal()
    try:
        bot = get_or_create_bot_user(db)
        history = get_recent_conversation(db, user_id, conversation_id)
        reply = generate_bot_reply(user_id, username, content, history)
        save_message(db, user_id, bot.id, reply, "assistant", conversation_id)
    finally:
        db.close()


@app.get("/")
def health() -> dict[str, str | bool]:
    _api_key, model, _source = get_gemini_settings()
    return {
        "status": "ok",
        "service": "Chat Bro API",
        "gemini_configured": bool(GEMINI_API_KEY),
        "gemini_model": model,
    }


@app.get("/settings/gemini", response_model=GeminiSettingsResponse)
def get_gemini_status(
    user_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> GeminiSettingsResponse:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.username == BOT_USERNAME:
        raise HTTPException(status_code=404, detail="User not found.")

    api_key, model, source = get_gemini_settings(user_id)
    return GeminiSettingsResponse(
        configured=bool(api_key),
        model=model,
        source=source,
        last_error=USER_GEMINI_ERRORS.get(user_id),
    )


@app.post("/settings/gemini", response_model=GeminiSettingsResponse)
def save_gemini_settings(
    payload: GeminiSettingsRequest,
    db: Session = Depends(get_db),
) -> GeminiSettingsResponse:
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user or user.username == BOT_USERNAME:
        raise HTTPException(status_code=404, detail="User not found.")

    raise HTTPException(
        status_code=403,
        detail="Gemini is configured server-wide by the Chat Bro backend owner.",
    )


@app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: AuthRequest, db: Session = Depends(get_db)) -> User:
    username = normalize_username(payload.username)
    password = payload.password

    if not username:
        raise HTTPException(status_code=400, detail="Username is required.")
    if not password:
        raise HTTPException(status_code=400, detail="Password is required.")
    if username == BOT_USERNAME:
        raise HTTPException(status_code=400, detail="This username is reserved.")

    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists.")

    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/login", response_model=UserResponse)
def login(payload: AuthRequest, db: Session = Depends(get_db)) -> User:
    username = normalize_username(payload.username)
    user = db.query(User).filter(User.username == username).first()

    if not user or user.username == BOT_USERNAME or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    return user


@app.post("/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def create_message(
    payload: MessageCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MessageResponse:
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")

    sender = db.query(User).filter(User.id == payload.sender_id).first()
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found.")
    if sender.username == BOT_USERNAME:
        raise HTTPException(status_code=400, detail="Bot messages are generated by the backend.")

    conversation_id = payload.conversation_id or default_conversation_id(sender.id)
    message = save_message(db, sender.id, sender.id, content, "user", conversation_id)
    background_tasks.add_task(create_background_bot_reply, sender.id, sender.username, content, conversation_id)
    return message_to_response(message)


@app.get("/messages", response_model=list[MessageResponse])
def get_messages(
    user_id: int = Query(..., ge=1),
    conversation_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[MessageResponse]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.username == BOT_USERNAME:
        raise HTTPException(status_code=404, detail="User not found.")

    resolved_conversation_id = conversation_id or default_conversation_id(user_id)
    messages = (
        db.query(Message)
        .filter(Message.user_id == user_id, Message.conversation_id == resolved_conversation_id)
        .join(User, Message.sender_id == User.id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .limit(limit)
        .all()
    )

    return [message_to_response(message) for message in messages]
