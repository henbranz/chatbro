import time
from datetime import datetime
from html import escape
import os
import re
from typing import Any
from zoneinfo import ZoneInfo

import requests
import streamlit as st
import streamlit.components.v1 as components


def get_api_base_url() -> str:
    env_value = os.getenv("API_BASE_URL")
    if env_value:
        return env_value.rstrip("/")

    try:
        secret_value = st.secrets.get("API_BASE_URL")
    except Exception:
        secret_value = None

    return (secret_value or "http://127.0.0.1:8000").rstrip("/")


API_BASE_URL = get_api_base_url()
REQUEST_TIMEOUT = 5
PRODUCT_NAME = "Chat Bro"


st.set_page_config(
    page_title=PRODUCT_NAME,
    layout="wide",
)


def init_session_state() -> None:
    if "user" not in st.session_state:
        st.session_state.user = None
    if "is_authenticated" not in st.session_state:
        st.session_state.is_authenticated = False
    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = None
    if "should_scroll_bottom" not in st.session_state:
        st.session_state.should_scroll_bottom = False


def get_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"API error {response.status_code}: {response.text}"

    detail = payload.get("detail", "Unknown error")
    if isinstance(detail, list):
        return "; ".join(str(item.get("msg", item)) for item in detail if isinstance(item, dict))
    return str(detail)


def api_request(method: str, endpoint: str, **kwargs: Any):
    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{endpoint}",
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to FastAPI. Start the backend server and try again.")
        return None
    except requests.exceptions.Timeout:
        st.error("The API request timed out. Check the backend server.")
        return None
    except requests.exceptions.RequestException as exc:
        st.error(f"API request failed: {exc}")
        return None

    if response.status_code >= 400:
        st.error(get_error_detail(response))
        return None

    return response.json() if response.content else None


def register_user(username: str, password: str):
    return api_request("POST", "/register", json={"username": username, "password": password})


def login_user(username: str, password: str):
    return api_request("POST", "/login", json={"username": username, "password": password})


def authenticate(user: dict[str, Any]) -> None:
    st.session_state.user = user
    st.session_state.is_authenticated = True
    st.session_state.conversation_id = f"default-{user['id']}"
    st.session_state.should_scroll_bottom = True
    st.rerun()


def fetch_messages(user_id: int, conversation_id: str):
    return api_request(
        "GET",
        "/messages",
        params={"user_id": user_id, "conversation_id": conversation_id, "limit": 100},
    )


def send_message(sender_id: int, content: str, conversation_id: str):
    return api_request(
        "POST",
        "/messages",
        json={"sender_id": sender_id, "content": content, "conversation_id": conversation_id},
    )


def fetch_gemini_status(user_id: int):
    return api_request("GET", "/settings/gemini", params={"user_id": user_id})


def format_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        return parsed.astimezone(ZoneInfo("Asia/Jerusalem")).strftime("%H:%M")
    except ValueError:
        return value


def contains_hebrew(value: str) -> bool:
    return any("\u0590" <= character <= "\u05ff" for character in value)


def format_message_content(value: str) -> str:
    lines = [line.rstrip() for line in value.strip().splitlines()]
    parts: list[str] = []
    paragraph: list[str] = []
    list_items: list[tuple[int | None, str]] = []
    list_type: str | None = None
    ordered_start: int | None = None

    def flush_paragraph() -> None:
        if paragraph:
            parts.append(f"<p>{escape(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_type, ordered_start
        if list_items:
            tag = "ol" if list_type == "ol" else "ul"
            start_attr = f' start="{ordered_start}"' if tag == "ol" and ordered_start else ""
            items = "".join(f"<li>{escape(item_text)}</li>" for _number, item_text in list_items)
            parts.append(f"<{tag}{start_attr}>{items}</{tag}>")
            list_items.clear()
            list_type = None
            ordered_start = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue

        ordered_match = re.match(r"^\s*(\d+)[.)]\s+(.+)$", line)
        bullet_match = re.match(r"^\s*[-*•]\s+(.+)$", line)

        if ordered_match:
            flush_paragraph()
            if list_type not in (None, "ol"):
                flush_list()
            list_type = "ol"
            number = int(ordered_match.group(1))
            if ordered_start is None:
                ordered_start = number
            elif list_items:
                previous_number = list_items[-1][0]
                if previous_number is not None and number != previous_number + 1:
                    flush_list()
                    list_type = "ol"
                    ordered_start = number
            list_items.append((number, ordered_match.group(2)))
        elif bullet_match:
            flush_paragraph()
            if list_type not in (None, "ul"):
                flush_list()
            list_type = "ul"
            list_items.append((None, bullet_match.group(1)))
        else:
            flush_list()
            paragraph.append(line)

    flush_paragraph()
    flush_list()
    return "".join(parts) if parts else escape(value)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #f7f4ed;
            --glass: rgba(255, 253, 248, 0.68);
            --glass-strong: rgba(255, 253, 248, 0.86);
            --text: #191814;
            --muted: #5f584f;
            --line: rgba(96, 76, 55, 0.18);
            --accent: #c96442;
            --accent-soft: #f5dfd5;
            --user: #2f2a24;
            --bot: rgba(255, 250, 241, 0.92);
            --shadow: 0 20px 70px rgba(54, 43, 31, 0.12);
        }

        .stApp {
            background:
                radial-gradient(circle at 16% 4%, rgba(201, 100, 66, 0.16), transparent 32%),
                radial-gradient(circle at 88% 12%, rgba(245, 223, 213, 0.85), transparent 30%),
                linear-gradient(180deg, #fbf9f4 0%, var(--bg) 100%);
            color: var(--text);
        }

        .block-container {
            max-width: 1040px;
            padding: 28px 22px 34px;
        }

        #MainMenu, footer, header {
            visibility: hidden;
        }

        button[data-baseweb="tab"] {
            color: var(--text) !important;
            font-weight: 800 !important;
            opacity: 1 !important;
            padding-left: 0 !important;
            padding-right: 18px !important;
        }

        button[data-baseweb="tab"] p {
            color: var(--text) !important;
            opacity: 1 !important;
            font-weight: 800 !important;
        }

        button[data-baseweb="tab"][aria-selected="true"] p {
            color: var(--accent) !important;
        }

        div[data-baseweb="tab-highlight"] {
            background-color: var(--accent) !important;
        }

        div[data-baseweb="tab-border"] {
            background-color: rgba(96,76,55,0.18) !important;
        }

        .auth-hero {
            max-width: 460px;
            margin: 6vh auto 18px;
            padding: 28px 26px;
            text-align: center;
            background: var(--glass);
            border: 1px solid var(--line);
            border-radius: 32px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(22px);
            transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
        }

        .auth-hero:hover {
            transform: translateY(-2px);
            border-color: rgba(201, 100, 66, 0.28);
            box-shadow: 0 24px 80px rgba(54, 43, 31, 0.15);
        }

        .eyebrow {
            display: inline-flex;
            align-items: center;
            padding: 7px 12px;
            border-radius: 999px;
            color: #9f4429;
            background: rgba(245, 223, 213, 0.78);
            border: 1px solid rgba(201,100,66,0.18);
            font-size: 12px;
            font-weight: 800;
            margin-bottom: 14px;
        }

        .title {
            margin: 0;
            color: var(--text);
            font-size: 34px;
            line-height: 1.12;
            font-weight: 820;
            letter-spacing: 0;
        }

        .subtitle {
            max-width: 540px;
            margin: 12px auto 0;
            color: var(--muted);
            font-size: 15px;
            line-height: 1.55;
            font-weight: 520;
        }

        .topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            padding: 12px 18px;
            margin-bottom: 18px;
            background: var(--glass);
            border: 1px solid var(--line);
            border-radius: 999px;
            box-shadow: 0 14px 45px rgba(54,43,31,0.08);
            backdrop-filter: blur(20px);
        }

        .brand {
            position: relative;
            display: inline-flex;
            font-size: 34px;
            font-weight: 900;
            color: var(--text);
            letter-spacing: 0;
            line-height: 1;
            animation: chatbro-float 3.8s ease-in-out infinite;
        }

        .brand span {
            color: var(--accent);
            background: linear-gradient(90deg, var(--accent), #e8a07d, var(--accent));
            background-size: 220% auto;
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: chatbro-shimmer 2.4s linear infinite;
        }

        @keyframes chatbro-shimmer {
            0% { background-position: 0% center; }
            100% { background-position: 220% center; }
        }

        @keyframes chatbro-float {
            0%, 100% { transform: translateY(0) scale(1); }
            50% { transform: translateY(-2px) scale(1.015); }
        }

        .user-pill {
            color: var(--text);
            background: rgba(255,255,255,0.66);
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: 8px 12px;
            font-size: 13px;
            font-weight: 750;
        }

        .settings-note {
            margin: 0 0 10px;
            color: var(--muted);
            font-size: 13px;
            line-height: 1.45;
        }

        .status-chip {
            display: inline-flex;
            align-items: center;
            padding: 6px 10px;
            margin-bottom: 10px;
            border-radius: 999px;
            background: rgba(245, 223, 213, 0.70);
            border: 1px solid rgba(201,100,66,0.20);
            color: #7c361f;
            font-size: 12px;
            font-weight: 800;
        }

        .chat-panel {
            background: var(--glass);
            border: 1px solid var(--line);
            border-radius: 34px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(24px);
            padding: 18px;
        }

        .chat-intro {
            padding: 4px 6px 14px;
            color: var(--muted);
            font-size: 14px;
            line-height: 1.5;
        }

        .messages {
            display: flex;
            flex-direction: column;
            gap: 12px;
            height: min(58vh, 560px);
            min-height: 360px;
            overflow-y: auto;
            scroll-behavior: smooth;
            padding: 12px;
            border-radius: 26px;
            background: rgba(255, 253, 248, 0.34);
            border: 1px solid rgba(96, 76, 55, 0.10);
        }

        .messages::-webkit-scrollbar {
            width: 9px;
        }

        .messages::-webkit-scrollbar-thumb {
            background: rgba(96, 76, 55, 0.20);
            border-radius: 999px;
        }

        .msg-row {
            display: flex;
            width: 100%;
        }

        .msg-row.left {
            justify-content: flex-start;
        }

        .msg-row.right {
            justify-content: flex-end;
        }

        .bubble {
            width: fit-content;
            max-width: min(690px, 78%);
            padding: 12px 15px;
            border-radius: 22px;
            font-size: 15px;
            line-height: 1.52;
            overflow-wrap: anywhere;
            transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
        }

        .bubble:hover {
            transform: translateY(-1px);
            box-shadow: 0 10px 26px rgba(54,43,31,0.08);
        }

        .message-content {
            white-space: normal;
        }

        .message-content p {
            margin: 0 0 0.55rem;
        }

        .message-content p:last-child {
            margin-bottom: 0;
        }

        .bubble[dir="rtl"] .message-content {
            direction: rtl;
            unicode-bidi: isolate;
            text-align: right;
        }

        .message-content ul,
        .message-content ol {
            margin: 0.4rem 0 0.65rem;
            padding-left: 1.2rem;
            padding-right: 1.2rem;
        }

        .message-content li {
            margin: 0.18rem 0;
            line-height: 1.45;
        }

        .bubble[dir="rtl"] ul,
        .bubble[dir="rtl"] ol {
            direction: rtl;
            text-align: right;
            list-style-position: outside;
            padding-right: 1.35rem;
            padding-left: 0;
        }

        .bubble[dir="rtl"] li {
            padding-right: 0.1rem;
            padding-left: 0;
        }

        .bubble.left {
            background: var(--bot);
            color: var(--text);
            border: 1px solid var(--line);
            border-top-left-radius: 9px;
            box-shadow: 0 4px 18px rgba(54,43,31,0.05);
        }

        .bubble.right {
            background: linear-gradient(135deg, #312b24, #171410);
            color: #fffaf1;
            border-top-right-radius: 9px;
            box-shadow: 0 12px 30px rgba(47,42,36,0.16);
        }

        .sender {
            display: none;
        }

        .meta {
            color: inherit;
            font-size: 11px;
            opacity: 0.58;
            margin-top: 7px;
        }

        .typing-bubble {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 13px 16px;
            border-radius: 22px;
            border-top-left-radius: 9px;
            background: var(--bot);
            border: 1px solid var(--line);
            box-shadow: 0 4px 18px rgba(54,43,31,0.05);
        }

        .typing-dot {
            width: 7px;
            height: 7px;
            border-radius: 999px;
            background: var(--accent);
            opacity: 0.35;
            animation: chatbro-pulse 1.1s infinite ease-in-out;
        }

        .typing-dot:nth-child(2) {
            animation-delay: 0.16s;
        }

        .typing-dot:nth-child(3) {
            animation-delay: 0.32s;
        }

        @keyframes chatbro-pulse {
            0%, 80%, 100% { transform: translateY(0); opacity: 0.35; }
            40% { transform: translateY(-4px); opacity: 1; }
        }

        .empty-state {
            padding: 42px 18px;
            text-align: center;
            color: var(--muted);
            background: rgba(255,255,255,0.42);
            border: 1px dashed var(--line);
            border-radius: 24px;
        }

        div[data-testid="stForm"] {
            max-width: 460px;
            margin: 0 auto;
            border: 1px solid var(--line);
            border-radius: 28px;
            background: var(--glass-strong);
            box-shadow: 0 18px 55px rgba(54,43,31,0.08);
            backdrop-filter: blur(20px);
        }

        div[data-testid="stForm"]:has(input[placeholder="Message Chat Bro..."]) {
            max-width: none;
            margin: 14px 0 0;
            border-radius: 999px;
            padding: 6px;
        }

        div[data-testid="stTextInput"] input {
            min-height: 44px;
            border-radius: 999px !important;
            border: 0 !important;
            outline: none !important;
            background: transparent !important;
            color: var(--text) !important;
            -webkit-text-fill-color: var(--text) !important;
            caret-color: var(--text) !important;
            padding: 0.78rem 1rem !important;
            transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
            box-shadow: none !important;
        }

        div[data-testid="stTextInput"] div[data-baseweb="input"] {
            border: 1px solid rgba(96,76,55,0.14) !important;
            border-radius: 999px !important;
            background: rgba(255,255,255,0.68) !important;
            box-shadow: inset 0 1px 2px rgba(54,43,31,0.035), 0 4px 14px rgba(54,43,31,0.035) !important;
            overflow: hidden !important;
            transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
        }

        div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {
            background: rgba(255,255,255,0.92) !important;
            border-color: rgba(201,100,66,0.28) !important;
            box-shadow: 0 0 0 3px rgba(201,100,66,0.08), 0 8px 18px rgba(54,43,31,0.06) !important;
        }

        div[data-testid="stTextInput"] div[data-baseweb="base-input"],
        div[data-testid="stTextInput"] div[data-baseweb="base-input"] > div {
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
        }

        div[data-testid="stTextInput"] input::placeholder {
            color: #6f665d !important;
            opacity: 1 !important;
        }

        div[data-testid="stTextInput"] label p {
            color: var(--text) !important;
            font-weight: 760 !important;
        }

        div[data-testid="stTextInput"] input:focus {
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
        }

        div[data-testid="stTextInput"] input:focus-visible {
            outline: none !important;
        }

        div[data-testid="stTextInput"] button,
        div[data-testid="stTextInput"] button:hover,
        div[data-testid="stTextInput"] button:focus {
            background: rgba(47,42,36,0.08) !important;
            border: 0 !important;
            border-radius: 999px !important;
            box-shadow: none !important;
            color: var(--text) !important;
            margin-right: 3px !important;
        }

        div[data-testid="stTextInput"] input:-webkit-autofill,
        div[data-testid="stTextInput"] input:-webkit-autofill:hover,
        div[data-testid="stTextInput"] input:-webkit-autofill:focus {
            -webkit-text-fill-color: var(--text) !important;
            box-shadow: 0 0 0 1000px #ffffff inset !important;
            transition: background-color 9999s ease-in-out 0s !important;
        }

        .stButton > button,
        div[data-testid="stFormSubmitButton"] button {
            border-radius: 999px !important;
            min-height: 44px !important;
            padding: 0.58rem 1.1rem !important;
            font-weight: 820 !important;
            border: 1px solid rgba(96,76,55,0.24) !important;
            background: rgba(255,253,248,0.82) !important;
            color: var(--text) !important;
            transition: transform 160ms ease, box-shadow 160ms ease, background 160ms ease, border-color 160ms ease;
        }

        .stButton > button:hover {
            transform: translateY(-1px);
            border-color: rgba(201,100,66,0.45) !important;
            background: rgba(255,255,255,0.95) !important;
            color: var(--text) !important;
            box-shadow: 0 12px 26px rgba(54,43,31,0.10) !important;
        }

        div[data-testid="stFormSubmitButton"] button {
            background: linear-gradient(135deg, #312b24, #171410) !important;
            color: #fffaf1 !important;
            border-color: #171410 !important;
            box-shadow: 0 10px 22px rgba(47,42,36,0.16) !important;
        }

        div[data-testid="stFormSubmitButton"] button:hover,
        div[data-testid="stFormSubmitButton"] button:focus {
            transform: translateY(-1px);
            background: #171410 !important;
            color: #fffaf1 !important;
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 4px rgba(201,100,66,0.16), 0 14px 28px rgba(47,42,36,0.18) !important;
        }

        [data-testid="stHorizontalBlock"] {
            align-items: center;
        }

        @media (max-width: 720px) {
            .block-container {
                padding: 12px 10px 22px;
            }

            .auth-hero {
                margin-top: 3vh;
                padding: 22px 18px;
                border-radius: 26px;
            }

            .title {
                font-size: 29px;
            }

            .topbar {
                border-radius: 24px;
                align-items: flex-start;
                flex-direction: column;
            }

            .brand {
                font-size: 29px;
            }

            .chat-panel {
                padding: 10px;
                border-radius: 26px;
            }

            .messages {
                height: 60vh;
                min-height: 340px;
                padding: 10px;
                border-radius: 22px;
            }

            .bubble {
                max-width: 88%;
                font-size: 15px;
            }

            div[data-testid="stForm"]:has(input[placeholder="Message Chat Bro..."]) {
                border-radius: 24px;
            }

            div[data-testid="stFormSubmitButton"] button,
            .stButton > button {
                min-height: 48px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def message_bubble_html(message: dict[str, Any], current_user_id: int) -> str:
    is_current_user = message["role"] == "user" and message["sender_id"] == current_user_id
    row_class = "right" if is_current_user else "left"
    bubble_class = "right" if is_current_user else "left"
    raw_content = message["message_content"] or message["content"]
    content = format_message_content(raw_content)
    created_at = escape(format_timestamp(message["created_at"]))
    direction = "rtl" if contains_hebrew(raw_content) else "ltr"
    alignment = "right" if direction == "rtl" else "left"

    return (
        f'<div class="msg-row {row_class}">'
        f'<div class="bubble {bubble_class}" dir="{direction}" style="text-align: {alignment};">'
        f'<div class="message-content">{content}</div>'
        f'<div class="meta">{created_at}</div>'
        "</div>"
        "</div>"
    )


def typing_indicator_html() -> str:
    return (
        '<div class="msg-row left">'
        '<div class="typing-bubble" aria-label="Chat Bro is typing">'
        '<span class="typing-dot"></span>'
        '<span class="typing-dot"></span>'
        '<span class="typing-dot"></span>'
        "</div>"
        "</div>"
    )


def render_messages(
    messages: list[dict[str, Any]],
    current_user_id: int,
    show_typing: bool,
) -> None:
    messages_html = "\n".join(message_bubble_html(message, current_user_id) for message in messages)
    if show_typing:
        messages_html = f"{messages_html}\n{typing_indicator_html()}"

    st.markdown(
        f'<div class="messages">{messages_html}</div>',
        unsafe_allow_html=True,
    )


def scroll_messages_to_bottom(force: bool) -> None:
    behavior = "smooth" if force else "auto"
    components.html(
        f"""
        <script>
        const scrollLatestMessages = () => {{
            const containers = window.parent.document.querySelectorAll('.messages');
            const latest = containers[containers.length - 1];
            if (latest) {{
                latest.scrollTo({{ top: latest.scrollHeight, behavior: "{behavior}" }});
            }}
        }};
        setTimeout(scrollLatestMessages, 80);
        setTimeout(scrollLatestMessages, 280);
        </script>
        """,
        height=0,
    )


def rerun_while_typing() -> None:
    time.sleep(1.25)
    st.rerun()


def render_auth_screen() -> None:
    st.markdown(
        f"""
        <div class="auth-hero">
            <div class="eyebrow">Premium chat workspace</div>
            <h1 class="title">Welcome to {PRODUCT_NAME}</h1>
            <p class="subtitle">A rounded, glassy chat experience with private per-user conversations.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    login_tab, register_tab = st.tabs(["Login", "Register"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            if not username.strip() or not password.strip():
                st.warning("Please enter a username and password.")
            else:
                user = login_user(username, password)
                if user:
                    authenticate(user)

    with register_tab:
        with st.form("register_form"):
            username = st.text_input("Choose username", key="register_username")
            password = st.text_input("Choose password", type="password", key="register_password")
            submitted = st.form_submit_button("Register", use_container_width=True)

        if submitted:
            if len(username.strip()) < 3:
                st.warning("Username must be at least 3 characters.")
            elif len(password.strip()) < 4:
                st.warning("Password must be at least 4 characters.")
            else:
                user = register_user(username, password)
                if user:
                    authenticate(user)


def render_chat_screen() -> None:
    user = st.session_state.user
    username = escape(user["username"])
    conversation_id = st.session_state.conversation_id or f"default-{user['id']}"
    st.session_state.conversation_id = conversation_id

    st.markdown(
        f"""
        <div class="topbar">
            <div class="brand">Chat<span> Bro</span></div>
            <div class="user-pill">Logged in as {username}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="chat-intro">
            <strong>Chat Bro is online.</strong> Ask a question, test the flow, or describe what you want to build next.
        </div>
        """,
        unsafe_allow_html=True,
    )

    refresh_col, spacer_col, logout_col = st.columns([1, 6, 1])
    with refresh_col:
        if st.button("Refresh", use_container_width=True):
            st.session_state.should_scroll_bottom = False
            st.rerun()
    with logout_col:
        if st.button("Logout", use_container_width=True):
            st.session_state.user = None
            st.session_state.is_authenticated = False
            st.session_state.conversation_id = None
            st.rerun()

    messages = fetch_messages(user["id"], conversation_id)
    if messages is None:
        st.stop()

    show_typing = bool(messages and messages[-1]["role"] == "user")

    if not messages:
        st.markdown(
            '<div class="empty-state">No messages yet. Send the first one below.</div>',
            unsafe_allow_html=True,
        )
    else:
        render_messages(messages, user["id"], show_typing)
        scroll_messages_to_bottom(st.session_state.should_scroll_bottom or show_typing)
        st.session_state.should_scroll_bottom = False

    if show_typing:
        rerun_while_typing()

    with st.form("send_message_form", clear_on_submit=True):
        input_col, send_col = st.columns([6, 1])
        with input_col:
            content = st.text_input(
                "Message",
                placeholder="Message Chat Bro...",
                label_visibility="collapsed",
            )
        with send_col:
            submitted = st.form_submit_button("Send", use_container_width=True)

    if submitted:
        if not content.strip():
            st.warning("Message cannot be empty.")
        else:
            result = send_message(user["id"], content, conversation_id)
            if result:
                st.session_state.should_scroll_bottom = True
                st.rerun()


def main() -> None:
    init_session_state()
    inject_css()

    if st.session_state.is_authenticated and st.session_state.user:
        render_chat_screen()
    else:
        render_auth_screen()


if __name__ == "__main__":
    main()
