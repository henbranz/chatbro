import os
from datetime import datetime
from typing import Generator

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker


SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./messages.db")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(150), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    messages = relationship(
        "Message",
        back_populates="sender",
        cascade="all, delete-orphan",
        foreign_keys="Message.sender_id",
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    conversation_key = Column(String(100), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    participants = relationship(
        "ConversationParticipant",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_conversation_participant"),)

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    conversation = relationship("Conversation", back_populates="participants")
    user = relationship("User")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(32), default="user", nullable=False, index=True)
    content = Column(Text, nullable=False)
    message_content = Column(Text, nullable=True)
    conversation_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    sender = relationship("User", back_populates="messages", foreign_keys=[sender_id])


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_existing_schema()


def migrate_existing_schema() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    with engine.begin() as connection:
        if "users" in table_names:
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            if "password" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN password VARCHAR(255)"))
            if "updated_at" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN updated_at DATETIME"))
                connection.execute(text("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL"))

        if "messages" in table_names:
            message_columns = {column["name"] for column in inspector.get_columns("messages")}
            if "user_id" not in message_columns:
                connection.execute(text("ALTER TABLE messages ADD COLUMN user_id INTEGER"))
                connection.execute(text("UPDATE messages SET user_id = sender_id WHERE user_id IS NULL"))
            if "role" not in message_columns:
                connection.execute(text("ALTER TABLE messages ADD COLUMN role VARCHAR(32) DEFAULT 'user'"))
                connection.execute(
                    text(
                        """
                        UPDATE messages
                        SET role = CASE
                            WHEN sender_id IN (SELECT id FROM users WHERE username = 'simplebot') THEN 'assistant'
                            ELSE 'user'
                        END
                        WHERE role IS NULL OR role = ''
                        """
                    )
                )
            if "message_content" not in message_columns:
                connection.execute(text("ALTER TABLE messages ADD COLUMN message_content TEXT"))
                connection.execute(
                    text("UPDATE messages SET message_content = content WHERE message_content IS NULL")
                )
            if "conversation_id" not in message_columns:
                connection.execute(text("ALTER TABLE messages ADD COLUMN conversation_id VARCHAR(100)"))
                connection.execute(
                    text(
                        """
                        UPDATE messages
                        SET conversation_id = 'default-' || CAST(user_id AS TEXT)
                        WHERE conversation_id IS NULL
                        """
                    )
                )

        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_user_id ON messages (user_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_role ON messages (role)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages (conversation_id)"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_conversation_participants_user_id ON conversation_participants (user_id)")
        )


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
