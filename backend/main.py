import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

import requests
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .database import (
    Conversation,
    ConversationParticipant,
    GroupChat,
    GroupInvitation,
    GroupMember,
    GroupMessage,
    GroupTypingStatus,
    Message,
    SessionLocal,
    User,
    get_db,
    init_db,
)


app = FastAPI(title="Chat Bro API")
BOT_USERNAME = "chatbro"
LEGACY_BOT_USERNAME = "simplebot"
BOT_USERNAMES = {BOT_USERNAME, LEGACY_BOT_USERNAME}
BOT_PASSWORD_HASH = "bot-account-cannot-login"
PRODUCT_BOT_DISPLAY_NAME = "Chat Bro"


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
    email: str | None = None


class UserUpdateRequest(BaseModel):
    username: str | None = None
    email: str | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str | None = None
    success: bool = True
    message: str | None = None
    user_id: int | None = None


class MessageCreateRequest(BaseModel):
    sender_id: int
    content: str
    conversation_id: str | None = None


class ConversationMessageCreateRequest(BaseModel):
    sender_id: int
    content: str


class ConversationCreateRequest(BaseModel):
    user_id: int
    title: str | None = None


class GroupCreateRequest(BaseModel):
    user_id: int
    name: str


class GroupInviteRequest(BaseModel):
    inviter_user_id: int
    invited_email: str | None = None
    invited_username: str | None = None
    invited_user_id: int | None = None


class InvitationActionRequest(BaseModel):
    user_id: int


class GroupMessageCreateRequest(BaseModel):
    sender_id: int
    content: str


class GroupTypingRequest(BaseModel):
    user_id: int
    is_typing: bool = True


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


class ConversationResponse(BaseModel):
    id: int
    title: str
    conversation_id: str
    last_message: str | None = None
    updated_at: datetime


class ConversationMessageResponse(BaseModel):
    id: int
    conversation_id: int
    conversation_key: str
    sender_id: int
    sender_username: str
    role: str
    content: str
    message_content: str
    created_at: datetime


class GroupResponse(BaseModel):
    id: int
    name: str
    created_by_user_id: int
    created_by_username: str
    role: str
    member_count: int
    last_message: str | None = None
    created_at: datetime
    updated_at: datetime


class GroupInvitationResponse(BaseModel):
    id: int
    group_id: int
    group_name: str
    invited_user_id: int
    invited_username: str
    invited_email: str | None = None
    invited_by_user_id: int
    invited_by_username: str
    status: str
    created_at: datetime
    responded_at: datetime | None = None


class GroupMessageResponse(BaseModel):
    id: int
    group_id: int
    sender_type: str
    sender_user_id: int | None = None
    sender_display_name: str
    role: str
    content: str
    created_at: datetime


class GroupMessageCreateResponse(BaseModel):
    messages: list[GroupMessageResponse]
    bot_pending: bool = True


class GroupTypingResponse(BaseModel):
    user_id: int
    username: str
    updated_at: datetime


class SearchMessageResponse(BaseModel):
    id: int
    conversation_id: int
    conversation_key: str
    conversation_title: str
    sender_id: int
    sender_username: str
    role: str
    content: str
    message_content: str
    created_at: datetime


class SearchGroupMessageResponse(BaseModel):
    id: int
    group_id: int
    group_name: str
    sender_type: str
    sender_user_id: int | None = None
    sender_display_name: str
    role: str
    content: str
    created_at: datetime


class SearchGroupMemberResponse(BaseModel):
    group_id: int
    group_name: str
    user_id: int
    username: str
    email: str | None = None
    role: str
    joined_at: datetime


class SearchResponse(BaseModel):
    conversations: list[ConversationResponse]
    messages: list[SearchMessageResponse]
    groups: list[GroupResponse] = []
    group_messages: list[SearchGroupMessageResponse] = []
    group_members: list[SearchGroupMemberResponse] = []


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
        sync_conversations_from_messages(db)
        ensure_default_conversations_for_users(db)
    finally:
        db.close()


def normalize_username(username: str) -> str:
    return username.strip().lower()


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_context.verify(password, password_hash)
    except ValueError:
        return password == password_hash


def verify_user_password(user: User, password: str) -> bool:
    if user.password is not None:
        return password == user.password
    return verify_password(password, user.password_hash)


def default_conversation_id(user_id: int) -> str:
    return f"default-{user_id}"


def conversation_title_for_key(conversation_key: str) -> str:
    if conversation_key.startswith("default-"):
        return "Chat Bro"
    return conversation_key.replace("-", " ").replace("_", " ").title() or "Conversation"


def title_from_message(content: str) -> str:
    compact = " ".join(content.split())
    if not compact:
        return "Conversation"
    return compact[:48].rstrip(" ,.;:!?") or "Conversation"


def is_auto_conversation_title(conversation: Conversation) -> bool:
    return (
        conversation.title == conversation_title_for_key(conversation.conversation_key)
        or conversation.title.startswith("Chat ")
        or conversation.title == "New Chat"
    )


def first_user_message_title(db: Session, conversation: Conversation, user_id: int) -> str | None:
    first_message = (
        db.query(Message)
        .filter(
            Message.user_id == user_id,
            Message.conversation_id == conversation.conversation_key,
            Message.role == "user",
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .first()
    )
    if not first_message:
        return None
    return title_from_message(first_message.message_content or first_message.content)


def refresh_conversation_title(db: Session, conversation: Conversation, user_id: int, content: str | None = None) -> None:
    if not is_auto_conversation_title(conversation):
        return
    conversation.title = title_from_message(content) if content else first_user_message_title(db, conversation, user_id) or conversation.title


@dataclass
class BotHistoryMessage:
    role: str
    content: str
    message_content: str


def get_regular_user(db: Session, user_id: int, *, detail: str = "User not found.") -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail=detail)
    return user


def find_regular_user_by_username(db: Session, username: str) -> User:
    normalized = normalize_username(username)
    user = db.query(User).filter(User.username == normalized).first()
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail="Invited user not found.")
    return user


def find_regular_user_by_email(db: Session, email: str) -> User:
    normalized = normalize_email(email)
    user = db.query(User).filter(User.email == normalized).first()
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail="Invited email not found.")
    return user


def is_valid_email(email: str) -> bool:
    local, separator, domain = email.partition("@")
    return bool(local and separator and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def get_group(db: Session, group_id: int) -> GroupChat:
    group = db.query(GroupChat).filter(GroupChat.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group chat not found.")
    return group


def get_group_membership(db: Session, group_id: int, user_id: int) -> GroupMember | None:
    return (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .first()
    )


def require_group_member(db: Session, group_id: int, user_id: int) -> GroupMember:
    membership = get_group_membership(db, group_id, user_id)
    if not membership:
        raise HTTPException(status_code=403, detail="User is not a member of this group.")
    return membership


def group_message_to_response(message: GroupMessage) -> GroupMessageResponse:
    return GroupMessageResponse(
        id=message.id,
        group_id=message.group_id,
        sender_type=message.sender_type,
        sender_user_id=message.sender_user_id,
        sender_display_name=message.sender_display_name,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
    )


def group_to_response(db: Session, group: GroupChat, user_id: int) -> GroupResponse:
    membership = get_group_membership(db, group.id, user_id)
    if not membership:
        raise HTTPException(status_code=403, detail="User is not a member of this group.")

    member_count = db.query(GroupMember).filter(GroupMember.group_id == group.id).count()
    last_message = (
        db.query(GroupMessage)
        .filter(GroupMessage.group_id == group.id)
        .order_by(GroupMessage.created_at.desc(), GroupMessage.id.desc())
        .first()
    )
    return GroupResponse(
        id=group.id,
        name=group.name,
        created_by_user_id=group.created_by_user_id,
        created_by_username=group.creator.username,
        role=membership.role,
        member_count=member_count,
        last_message=last_message.content if last_message else None,
        created_at=group.created_at,
        updated_at=last_message.created_at if last_message else group.updated_at,
    )


def invitation_to_response(invitation: GroupInvitation) -> GroupInvitationResponse:
    return GroupInvitationResponse(
        id=invitation.id,
        group_id=invitation.group_id,
        group_name=invitation.group.name,
        invited_user_id=invitation.invited_user_id,
        invited_username=invitation.invited_user.username,
        invited_email=invitation.invited_user.email,
        invited_by_user_id=invitation.invited_by_user_id,
        invited_by_username=invitation.invited_by_user.username,
        status=invitation.status,
        created_at=invitation.created_at,
        responded_at=invitation.responded_at,
    )


def touch_group(group: GroupChat) -> None:
    group.updated_at = datetime.utcnow()


def save_group_message(
    db: Session,
    group: GroupChat,
    content: str,
    *,
    sender_type: str,
    role: str,
    sender_display_name: str,
    sender_user_id: int | None = None,
) -> GroupMessage:
    touch_group(group)
    message = GroupMessage(
        group_id=group.id,
        sender_type=sender_type,
        sender_user_id=sender_user_id,
        sender_display_name=sender_display_name,
        role=role,
        content=content,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_recent_group_history(db: Session, group_id: int, limit: int = 12) -> list[BotHistoryMessage]:
    messages = (
        db.query(GroupMessage)
        .filter(GroupMessage.group_id == group_id, GroupMessage.sender_type.in_(["user", "bot"]))
        .order_by(GroupMessage.created_at.desc(), GroupMessage.id.desc())
        .limit(limit)
        .all()
    )[::-1]
    return [
        BotHistoryMessage(
            role="assistant" if message.sender_type == "bot" else "user",
            content=message.content,
            message_content=message.content,
        )
        for message in messages
    ]


def get_or_create_bot_user(db: Session) -> User:
    bot = db.query(User).filter(User.username == BOT_USERNAME).first()
    if bot:
        return bot

    bot = User(username=BOT_USERNAME, password_hash=BOT_PASSWORD_HASH)
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return bot


def get_or_create_conversation(
    db: Session,
    user_id: int,
    conversation_key: str | None = None,
    title: str | None = None,
) -> Conversation:
    resolved_key = conversation_key or default_conversation_id(user_id)
    conversation = db.query(Conversation).filter(Conversation.conversation_key == resolved_key).first()
    if not conversation:
        conversation = Conversation(
            title=title or conversation_title_for_key(resolved_key),
            conversation_key=resolved_key,
        )
        db.add(conversation)
        db.flush()
    elif title and conversation.title != title:
        conversation.title = title

    participant = (
        db.query(ConversationParticipant)
        .filter(
            ConversationParticipant.conversation_id == conversation.id,
            ConversationParticipant.user_id == user_id,
        )
        .first()
    )
    if not participant:
        db.add(ConversationParticipant(conversation_id=conversation.id, user_id=user_id))
        db.flush()

    return conversation


def ensure_default_conversations_for_users(db: Session) -> None:
    users = db.query(User).filter(~User.username.in_(BOT_USERNAMES)).all()
    for user in users:
        get_or_create_conversation(db, user.id)
    db.commit()


def sync_conversations_from_messages(db: Session) -> None:
    conversation_rows = (
        db.query(
            Message.user_id,
            Message.conversation_id,
            func.min(Message.created_at),
            func.max(Message.created_at),
        )
        .filter(Message.user_id.isnot(None), Message.conversation_id.isnot(None))
        .group_by(Message.user_id, Message.conversation_id)
        .all()
    )

    for user_id, conversation_key, created_at, updated_at in conversation_rows:
        if not user_id or not conversation_key:
            continue
        conversation = get_or_create_conversation(db, user_id, conversation_key)
        if created_at and created_at < conversation.created_at:
            conversation.created_at = created_at
        if updated_at:
            conversation.updated_at = updated_at

    db.commit()


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


def conversation_message_to_response(message: Message, conversation: Conversation) -> ConversationMessageResponse:
    content = message.message_content or message.content
    return ConversationMessageResponse(
        id=message.id,
        conversation_id=conversation.id,
        conversation_key=conversation.conversation_key,
        sender_id=message.sender_id,
        sender_username=message.sender.username,
        role=message.role or "user",
        content=content,
        message_content=content,
        created_at=message.created_at,
    )


def conversation_to_response(db: Session, conversation: Conversation, user_id: int) -> ConversationResponse:
    last_message = (
        db.query(Message)
        .filter(Message.user_id == user_id, Message.conversation_id == conversation.conversation_key)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .first()
    )
    last_content = (last_message.message_content or last_message.content) if last_message else None
    updated_at = last_message.created_at if last_message else conversation.updated_at
    title = conversation.title
    if is_auto_conversation_title(conversation):
        title = first_user_message_title(db, conversation, user_id) or title
    return ConversationResponse(
        id=conversation.id,
        title=title,
        conversation_id=conversation.conversation_key,
        last_message=last_content,
        updated_at=updated_at,
    )


def get_user_conversation(db: Session, user_id: int, conversation_id: int) -> Conversation:
    conversation = (
        db.query(Conversation)
        .join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id)
        .filter(Conversation.id == conversation_id, ConversationParticipant.user_id == user_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


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


def touch_conversation(conversation: Conversation) -> None:
    conversation.updated_at = datetime.utcnow()


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
        conversation = get_or_create_conversation(db, user_id, conversation_id)
        history = get_recent_conversation(db, user_id, conversation_id)
        reply = generate_bot_reply(user_id, username, content, history)
        touch_conversation(conversation)
        save_message(db, user_id, bot.id, reply, "assistant", conversation_id)
    finally:
        db.close()


def create_background_group_bot_reply(
    group_id: int,
    user_id: int,
    username: str,
    content: str,
) -> None:
    time.sleep(0.8)
    db = SessionLocal()
    try:
        get_or_create_bot_user(db)
        group = get_group(db, group_id)
        history = get_recent_group_history(db, group_id)
        reply = generate_bot_reply(user_id, username, content, history)
        save_group_message(
            db,
            group,
            reply,
            sender_type="bot",
            role="assistant",
            sender_display_name=PRODUCT_BOT_DISPLAY_NAME,
        )
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
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail="User not found.")

    api_key, model, source = get_gemini_settings(user_id)
    return GeminiSettingsResponse(
        configured=bool(api_key),
        model=model,
        source=source,
        last_error=USER_GEMINI_ERRORS.get(user_id),
    )


@app.post("/groups/create", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
def create_group_chat(
    payload: GroupCreateRequest,
    db: Session = Depends(get_db),
) -> GroupResponse:
    creator = get_regular_user(db, payload.user_id, detail="Creator not found.")
    name = " ".join(payload.name.split())
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required.")

    group = GroupChat(name=name[:200], created_by_user_id=creator.id)
    db.add(group)
    db.flush()
    db.add(GroupMember(group_id=group.id, user_id=creator.id, role="owner"))
    db.flush()
    save_group_message(
        db,
        group,
        f"{creator.username} created the group.",
        sender_type="system",
        role="system",
        sender_display_name="System",
    )
    return group_to_response(db, group, creator.id)


@app.get("/groups/my", response_model=list[GroupResponse])
def get_my_groups(
    user_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> list[GroupResponse]:
    user = get_regular_user(db, user_id)
    groups = (
        db.query(GroupChat)
        .join(GroupMember, GroupMember.group_id == GroupChat.id)
        .filter(GroupMember.user_id == user.id)
        .order_by(GroupChat.updated_at.desc(), GroupChat.id.desc())
        .all()
    )
    return [group_to_response(db, group, user.id) for group in groups]


@app.post("/groups/{group_id}/invite", response_model=GroupInvitationResponse, status_code=status.HTTP_201_CREATED)
def invite_user_to_group(
    group_id: int,
    payload: GroupInviteRequest,
    db: Session = Depends(get_db),
) -> GroupInvitationResponse:
    inviter = get_regular_user(db, payload.inviter_user_id, detail="Inviting user not found.")
    group = get_group(db, group_id)
    require_group_member(db, group.id, inviter.id)

    if payload.invited_email:
        invited_user = find_regular_user_by_email(db, payload.invited_email)
    elif payload.invited_user_id is not None:
        invited_user = get_regular_user(db, payload.invited_user_id, detail="Invited user not found.")
    elif payload.invited_username:
        invited_user = find_regular_user_by_username(db, payload.invited_username)
    else:
        raise HTTPException(status_code=400, detail="Invite requires an email, username, or user id.")

    if invited_user.id == inviter.id:
        raise HTTPException(status_code=400, detail="You are already a member of this group.")
    if get_group_membership(db, group.id, invited_user.id):
        raise HTTPException(status_code=400, detail="User is already a member of this group.")

    pending_invitation = (
        db.query(GroupInvitation)
        .filter(
            GroupInvitation.group_id == group.id,
            GroupInvitation.invited_user_id == invited_user.id,
            GroupInvitation.status == "pending",
        )
        .first()
    )
    if pending_invitation:
        raise HTTPException(status_code=409, detail="This user already has a pending invitation.")

    invitation = GroupInvitation(
        group_id=group.id,
        invited_user_id=invited_user.id,
        invited_by_user_id=inviter.id,
        status="pending",
    )
    db.add(invitation)
    db.flush()
    save_group_message(
        db,
        group,
        f"{inviter.username} invited {invited_user.email or invited_user.username}.",
        sender_type="system",
        role="system",
        sender_display_name="System",
    )
    return invitation_to_response(invitation)


@app.get("/invitations/my", response_model=list[GroupInvitationResponse])
def get_my_invitations(
    user_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> list[GroupInvitationResponse]:
    user = get_regular_user(db, user_id)
    invitations = (
        db.query(GroupInvitation)
        .filter(GroupInvitation.invited_user_id == user.id, GroupInvitation.status == "pending")
        .order_by(GroupInvitation.created_at.desc(), GroupInvitation.id.desc())
        .all()
    )
    return [invitation_to_response(invitation) for invitation in invitations]


@app.post("/invitations/{invitation_id}/accept", response_model=GroupInvitationResponse)
def accept_group_invitation(
    invitation_id: int,
    payload: InvitationActionRequest,
    db: Session = Depends(get_db),
) -> GroupInvitationResponse:
    user = get_regular_user(db, payload.user_id)
    invitation = db.query(GroupInvitation).filter(GroupInvitation.id == invitation_id).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if invitation.invited_user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only accept your own invitations.")
    if invitation.status != "pending":
        raise HTTPException(status_code=400, detail=f"Invitation is already {invitation.status}.")

    if not get_group_membership(db, invitation.group_id, user.id):
        db.add(GroupMember(group_id=invitation.group_id, user_id=user.id, role="member"))
        db.flush()

    invitation.status = "accepted"
    invitation.responded_at = datetime.utcnow()
    save_group_message(
        db,
        invitation.group,
        f"{user.username} joined the group.",
        sender_type="system",
        role="system",
        sender_display_name="System",
    )
    return invitation_to_response(invitation)


@app.post("/invitations/{invitation_id}/decline", response_model=GroupInvitationResponse)
def decline_group_invitation(
    invitation_id: int,
    payload: InvitationActionRequest,
    db: Session = Depends(get_db),
) -> GroupInvitationResponse:
    user = get_regular_user(db, payload.user_id)
    invitation = db.query(GroupInvitation).filter(GroupInvitation.id == invitation_id).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if invitation.invited_user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only decline your own invitations.")
    if invitation.status != "pending":
        raise HTTPException(status_code=400, detail=f"Invitation is already {invitation.status}.")

    invitation.status = "declined"
    invitation.responded_at = datetime.utcnow()
    save_group_message(
        db,
        invitation.group,
        f"{user.username} declined the invitation.",
        sender_type="system",
        role="system",
        sender_display_name="System",
    )
    return invitation_to_response(invitation)


@app.get("/groups/{group_id}/messages", response_model=list[GroupMessageResponse])
def get_group_messages(
    group_id: int,
    user_id: int = Query(..., ge=1),
    after_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[GroupMessageResponse]:
    user = get_regular_user(db, user_id)
    group = get_group(db, group_id)
    require_group_member(db, group.id, user.id)

    query = db.query(GroupMessage).filter(GroupMessage.group_id == group.id)
    if after_id is not None:
        query = query.filter(GroupMessage.id > after_id)
    messages = query.order_by(GroupMessage.id.asc()).limit(limit).all()
    return [group_message_to_response(message) for message in messages]


@app.get("/groups/{group_id}/messages/new", response_model=list[GroupMessageResponse])
def get_new_group_messages(
    group_id: int,
    user_id: int = Query(..., ge=1),
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[GroupMessageResponse]:
    return get_group_messages(group_id, user_id=user_id, after_id=after_id, limit=limit, db=db)


@app.get("/groups/{group_id}/typing", response_model=list[GroupTypingResponse])
def get_group_typing_statuses(
    group_id: int,
    user_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> list[GroupTypingResponse]:
    user = get_regular_user(db, user_id)
    group = get_group(db, group_id)
    require_group_member(db, group.id, user.id)

    cutoff = datetime.utcnow() - timedelta(seconds=6)
    db.query(GroupTypingStatus).filter(GroupTypingStatus.updated_at < cutoff).delete(synchronize_session=False)
    statuses = (
        db.query(GroupTypingStatus)
        .join(User, User.id == GroupTypingStatus.user_id)
        .filter(
            GroupTypingStatus.group_id == group.id,
            GroupTypingStatus.user_id != user.id,
            GroupTypingStatus.updated_at >= cutoff,
        )
        .order_by(GroupTypingStatus.updated_at.desc(), GroupTypingStatus.id.desc())
        .all()
    )
    db.commit()
    return [
        GroupTypingResponse(user_id=status.user_id, username=status.user.username, updated_at=status.updated_at)
        for status in statuses
    ]


@app.post("/groups/{group_id}/typing", response_model=dict[str, bool])
def update_group_typing_status(
    group_id: int,
    payload: GroupTypingRequest,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    user = get_regular_user(db, payload.user_id)
    group = get_group(db, group_id)
    require_group_member(db, group.id, user.id)

    status_row = (
        db.query(GroupTypingStatus)
        .filter(GroupTypingStatus.group_id == group.id, GroupTypingStatus.user_id == user.id)
        .first()
    )
    if payload.is_typing:
        if status_row:
            status_row.updated_at = datetime.utcnow()
        else:
            db.add(GroupTypingStatus(group_id=group.id, user_id=user.id))
    elif status_row:
        db.delete(status_row)

    db.commit()
    return {"success": True}


@app.post(
    "/groups/{group_id}/messages",
    response_model=GroupMessageCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_group_message(
    group_id: int,
    payload: GroupMessageCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> GroupMessageCreateResponse:
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")

    sender = get_regular_user(db, payload.sender_id, detail="Sender not found.")
    group = get_group(db, group_id)
    require_group_member(db, group.id, sender.id)

    user_message = save_group_message(
        db,
        group,
        content,
        sender_type="user",
        sender_user_id=sender.id,
        sender_display_name=sender.username,
        role="user",
    )
    db.query(GroupTypingStatus).filter(
        GroupTypingStatus.group_id == group.id,
        GroupTypingStatus.user_id == sender.id,
    ).delete(synchronize_session=False)
    db.commit()
    background_tasks.add_task(create_background_group_bot_reply, group.id, sender.id, sender.username, content)
    return GroupMessageCreateResponse(messages=[group_message_to_response(user_message)], bot_pending=True)


@app.get("/conversations", response_model=list[ConversationResponse])
def get_conversations(
    user_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> list[ConversationResponse]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail="User not found.")

    get_or_create_conversation(db, user.id)
    db.commit()
    conversations = (
        db.query(Conversation)
        .join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id)
        .filter(ConversationParticipant.user_id == user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .all()
    )
    return [conversation_to_response(db, conversation, user.id) for conversation in conversations]


@app.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreateRequest,
    db: Session = Depends(get_db),
) -> ConversationResponse:
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail="User not found.")

    existing_count = (
        db.query(ConversationParticipant)
        .filter(ConversationParticipant.user_id == user.id)
        .count()
    )
    title = (payload.title or "").strip() or f"Chat {existing_count + 1}"
    conversation = Conversation(
        title=title,
        conversation_key=f"chat-{user.id}-{uuid4().hex[:12]}",
    )
    db.add(conversation)
    db.flush()
    db.add(ConversationParticipant(conversation_id=conversation.id, user_id=user.id))
    db.commit()
    db.refresh(conversation)
    return conversation_to_response(db, conversation, user.id)


@app.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageResponse])
def get_conversation_messages(
    conversation_id: int,
    user_id: int = Query(..., ge=1),
    after_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ConversationMessageResponse]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail="User not found.")

    conversation = get_user_conversation(db, user.id, conversation_id)
    query = db.query(Message).filter(
        Message.user_id == user.id,
        Message.conversation_id == conversation.conversation_key,
    )
    if after_id is not None:
        query = query.filter(Message.id > after_id)

    messages = query.order_by(Message.created_at.asc(), Message.id.asc()).limit(limit).all()
    return [conversation_message_to_response(message, conversation) for message in messages]


@app.post(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation_message(
    conversation_id: int,
    payload: ConversationMessageCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ConversationMessageResponse:
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")

    sender = db.query(User).filter(User.id == payload.sender_id).first()
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found.")
    if sender.username in BOT_USERNAMES:
        raise HTTPException(status_code=400, detail="Bot messages are generated by the backend.")

    conversation = get_user_conversation(db, sender.id, conversation_id)
    touch_conversation(conversation)
    refresh_conversation_title(db, conversation, sender.id, content)
    message = save_message(db, sender.id, sender.id, content, "user", conversation.conversation_key)
    background_tasks.add_task(
        create_background_bot_reply,
        sender.id,
        sender.username,
        content,
        conversation.conversation_key,
    )
    return conversation_message_to_response(message, conversation)


@app.get("/messages/search", response_model=list[SearchMessageResponse])
def search_messages(
    user_id: int = Query(..., ge=1),
    q: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[SearchMessageResponse]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail="User not found.")

    search_term = q.strip()
    if not search_term:
        raise HTTPException(status_code=400, detail="Search term cannot be empty.")

    conversations = (
        db.query(Conversation)
        .join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id)
        .filter(ConversationParticipant.user_id == user.id)
        .all()
    )
    conversations_by_key = {conversation.conversation_key: conversation for conversation in conversations}
    like_term = f"%{search_term}%"
    messages = (
        db.query(Message)
        .filter(
            Message.user_id == user.id,
            or_(Message.message_content.ilike(like_term), Message.content.ilike(like_term)),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )

    results: list[SearchMessageResponse] = []
    for message in messages:
        conversation_key = message.conversation_id or default_conversation_id(user.id)
        conversation = conversations_by_key.get(conversation_key)
        if not conversation:
            conversation = get_or_create_conversation(db, user.id, conversation_key)
            conversations_by_key[conversation_key] = conversation

        content = message.message_content or message.content
        results.append(
            SearchMessageResponse(
                id=message.id,
                conversation_id=conversation.id,
                conversation_key=conversation.conversation_key,
                conversation_title=conversation.title,
                sender_id=message.sender_id,
                sender_username=message.sender.username,
                role=message.role or "user",
                content=content,
                message_content=content,
                created_at=message.created_at,
            )
        )

    db.commit()
    return results


@app.get("/search", response_model=SearchResponse)
def search(
    user_id: int = Query(..., ge=1),
    q: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> SearchResponse:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail="User not found.")

    search_term = q.strip()
    if not search_term:
        raise HTTPException(status_code=400, detail="Search term cannot be empty.")

    like_term = f"%{search_term}%"
    conversations = (
        db.query(Conversation)
        .join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id)
        .filter(
            ConversationParticipant.user_id == user.id,
            Conversation.title.ilike(like_term),
        )
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(20)
        .all()
    )

    messages = (
        db.query(Message)
        .filter(
            Message.user_id == user.id,
            or_(Message.message_content.ilike(like_term), Message.content.ilike(like_term)),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )

    accessible_group_ids = [
        row[0]
        for row in db.query(GroupMember.group_id)
        .filter(GroupMember.user_id == user.id)
        .all()
    ]
    groups: list[GroupChat] = []
    group_messages: list[GroupMessage] = []
    group_members: list[GroupMember] = []
    if accessible_group_ids:
        groups = (
            db.query(GroupChat)
            .filter(GroupChat.id.in_(accessible_group_ids), GroupChat.name.ilike(like_term))
            .order_by(GroupChat.updated_at.desc(), GroupChat.id.desc())
            .limit(20)
            .all()
        )
        group_messages = (
            db.query(GroupMessage)
            .filter(
                GroupMessage.group_id.in_(accessible_group_ids),
                or_(
                    GroupMessage.content.ilike(like_term),
                    GroupMessage.sender_display_name.ilike(like_term),
                ),
            )
            .order_by(GroupMessage.created_at.desc(), GroupMessage.id.desc())
            .limit(limit)
            .all()
        )
        group_members = (
            db.query(GroupMember)
            .join(User, User.id == GroupMember.user_id)
            .filter(
                GroupMember.group_id.in_(accessible_group_ids),
                or_(User.email.ilike(like_term), User.username.ilike(like_term)),
            )
            .order_by(GroupMember.joined_at.desc(), GroupMember.id.desc())
            .limit(20)
            .all()
        )

    conversations_by_key = {
        conversation.conversation_key: conversation
        for conversation in (
            db.query(Conversation)
            .join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id)
            .filter(ConversationParticipant.user_id == user.id)
            .all()
        )
    }
    message_results: list[SearchMessageResponse] = []
    for message in messages:
        conversation_key = message.conversation_id or default_conversation_id(user.id)
        conversation = conversations_by_key.get(conversation_key)
        if not conversation:
            conversation = get_or_create_conversation(db, user.id, conversation_key)
            conversations_by_key[conversation_key] = conversation

        content = message.message_content or message.content
        message_results.append(
            SearchMessageResponse(
                id=message.id,
                conversation_id=conversation.id,
                conversation_key=conversation.conversation_key,
                conversation_title=conversation.title,
                sender_id=message.sender_id,
                sender_username=message.sender.username,
                role=message.role or "user",
                content=content,
                message_content=content,
                created_at=message.created_at,
            )
        )

    db.commit()
    return SearchResponse(
        conversations=[conversation_to_response(db, conversation, user.id) for conversation in conversations],
        messages=message_results,
        groups=[group_to_response(db, group, user.id) for group in groups],
        group_messages=[
            SearchGroupMessageResponse(
                id=message.id,
                group_id=message.group_id,
                group_name=message.group.name,
                sender_type=message.sender_type,
                sender_user_id=message.sender_user_id,
                sender_display_name=message.sender_display_name,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
            )
            for message in group_messages
        ],
        group_members=[
            SearchGroupMemberResponse(
                group_id=membership.group_id,
                group_name=membership.group.name,
                user_id=membership.user_id,
                username=membership.user.username,
                email=membership.user.email,
                role=membership.role,
                joined_at=membership.joined_at,
            )
            for membership in group_members
        ],
    )


@app.post("/settings/gemini", response_model=GeminiSettingsResponse)
def save_gemini_settings(
    payload: GeminiSettingsRequest,
    db: Session = Depends(get_db),
) -> GeminiSettingsResponse:
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail="User not found.")

    raise HTTPException(
        status_code=403,
        detail="Gemini is configured server-wide by the Chat Bro backend owner.",
    )


@app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: AuthRequest, db: Session = Depends(get_db)) -> UserResponse:
    username = normalize_username(payload.username)
    email = normalize_email(payload.email)
    password = payload.password

    if not username:
        raise HTTPException(status_code=400, detail="Username is required.")
    if not email or not is_valid_email(email):
        raise HTTPException(status_code=400, detail="A valid email is required.")
    if not password:
        raise HTTPException(status_code=400, detail="Password is required.")
    if username in BOT_USERNAMES:
        raise HTTPException(status_code=400, detail="This username is reserved.")

    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists.")

    existing_email = db.query(User).filter(User.email == email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already exists.")

    user = User(username=username, email=email, password=password, password_hash=password)
    db.add(user)
    db.commit()
    db.refresh(user)
    get_or_create_conversation(db, user.id)
    db.commit()
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        user_id=user.id,
        message="User registered successfully",
    )


@app.post("/login", response_model=UserResponse)
def login(payload: AuthRequest, db: Session = Depends(get_db)) -> UserResponse:
    username = normalize_username(payload.username)
    user = db.query(User).filter(User.username == username).first()

    if not user or user.username in BOT_USERNAMES or not verify_user_password(user, payload.password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    get_or_create_conversation(db, user.id)
    db.commit()
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        user_id=user.id,
        message="Login successful",
    )


@app.get("/users/{user_id}", response_model=UserResponse)
def get_user_profile(user_id: int, db: Session = Depends(get_db)) -> UserResponse:
    user = get_regular_user(db, user_id)
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        user_id=user.id,
        message="User profile loaded",
    )


@app.patch("/users/{user_id}", response_model=UserResponse)
def update_user_profile(
    user_id: int,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
) -> UserResponse:
    user = get_regular_user(db, user_id)

    if payload.username is not None:
        username = normalize_username(payload.username)
        if len(username) < 3:
            raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")
        if username in BOT_USERNAMES:
            raise HTTPException(status_code=400, detail="This username is reserved.")
        existing_username = db.query(User).filter(User.username == username, User.id != user.id).first()
        if existing_username:
            raise HTTPException(status_code=400, detail="Username already exists.")
        user.username = username

    if payload.email is not None:
        email = normalize_email(payload.email)
        if email and not is_valid_email(email):
            raise HTTPException(status_code=400, detail="A valid email is required.")
        existing_email = db.query(User).filter(User.email == email, User.id != user.id).first() if email else None
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already exists.")
        user.email = email or None

    db.commit()
    db.refresh(user)
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        user_id=user.id,
        message="User profile updated",
    )


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
    if sender.username in BOT_USERNAMES:
        raise HTTPException(status_code=400, detail="Bot messages are generated by the backend.")

    conversation_id = payload.conversation_id or default_conversation_id(sender.id)
    conversation = get_or_create_conversation(db, sender.id, conversation_id)
    touch_conversation(conversation)
    refresh_conversation_title(db, conversation, sender.id, content)
    message = save_message(db, sender.id, sender.id, content, "user", conversation_id)
    background_tasks.add_task(create_background_bot_reply, sender.id, sender.username, content, conversation_id)
    return message_to_response(message)


@app.get("/messages", response_model=list[MessageResponse])
def get_messages(
    user_id: int = Query(..., ge=1),
    conversation_id: str | None = None,
    after_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[MessageResponse]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.username in BOT_USERNAMES:
        raise HTTPException(status_code=404, detail="User not found.")

    resolved_conversation_id = conversation_id or default_conversation_id(user_id)
    get_or_create_conversation(db, user_id, resolved_conversation_id)
    db.commit()
    query = db.query(Message).filter(
        Message.user_id == user_id,
        Message.conversation_id == resolved_conversation_id,
    )
    if after_id is not None:
        query = query.filter(Message.id > after_id)

    messages = query.join(User, Message.sender_id == User.id).order_by(Message.created_at.asc(), Message.id.asc()).limit(limit).all()

    return [message_to_response(message) for message in messages]
