import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
import time
from datetime import datetime
from html import escape
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

import requests
import streamlit as st


API_BASE_URL = os.getenv("CHAT_BRO_API_BASE_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT = 5
PRODUCT_NAME = "Chat Bro"
POLLING_INTERVAL_SECONDS = 1
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "chat-bro-logo.png"


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
    if "selected_conversation_id" not in st.session_state:
        st.session_state.selected_conversation_id = None
    if "should_scroll_bottom" not in st.session_state:
        st.session_state.should_scroll_bottom = False
    if "show_search" not in st.session_state:
        st.session_state.show_search = False
    if "search_query" not in st.session_state:
        st.session_state.search_query = ""
    if "search_results" not in st.session_state:
        st.session_state.search_results = None
    if "last_search_query" not in st.session_state:
        st.session_state.last_search_query = ""
    if "active_chat_type" not in st.session_state:
        st.session_state.active_chat_type = "single"
    if "selected_group_id" not in st.session_state:
        st.session_state.selected_group_id = None
    if "group_messages" not in st.session_state:
        st.session_state.group_messages = []
    if "group_last_message_id" not in st.session_state:
        st.session_state.group_last_message_id = 0
    if "group_messages_group_id" not in st.session_state:
        st.session_state.group_messages_group_id = None
    if "show_login_password" not in st.session_state:
        st.session_state.show_login_password = False
    if "show_register_password" not in st.session_state:
        st.session_state.show_register_password = False
    if "invite_panel_group_id" not in st.session_state:
        st.session_state.invite_panel_group_id = None
    if "show_user_info_editor" not in st.session_state:
        st.session_state.show_user_info_editor = False
    if "show_user_menu" not in st.session_state:
        st.session_state.show_user_menu = False
    if "cached_conversations" not in st.session_state:
        st.session_state.cached_conversations = []
    if "cached_groups" not in st.session_state:
        st.session_state.cached_groups = []
    if "cached_invitations" not in st.session_state:
        st.session_state.cached_invitations = []
    restore_user_from_url()


def restore_user_from_url() -> None:
    if st.session_state.user:
        return

    user_id = st.query_params.get("user_id")
    username = st.query_params.get("username")
    if not user_id or not username:
        return

    try:
        resolved_user_id = int(user_id)
    except ValueError:
        return

    st.session_state.user = {
        "id": resolved_user_id,
        "user_id": resolved_user_id,
        "username": username,
        "success": True,
    }
    st.session_state.is_authenticated = True
    st.session_state.conversation_id = st.query_params.get("conversation_id") or f"default-{resolved_user_id}"
    st.session_state.active_chat_type = st.query_params.get("chat_type") or "single"
    group_id = st.query_params.get("group_id")
    if group_id:
        try:
            st.session_state.selected_group_id = int(group_id)
        except ValueError:
            st.session_state.selected_group_id = None


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


def register_user(username: str, email: str, password: str):
    return api_request("POST", "/register", json={"username": username, "email": email, "password": password})


def login_user(username: str, password: str):
    return api_request("POST", "/login", json={"username": username, "password": password})


def fetch_user_profile(user_id: int):
    return api_request("GET", f"/users/{user_id}")


def update_user_profile(user_id: int, username: str, email: str):
    return api_request("PATCH", f"/users/{user_id}", json={"username": username, "email": email})


def looks_like_email(email: str) -> bool:
    local, separator, domain = email.strip().partition("@")
    return bool(local and separator and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def submit_login_from_fields() -> None:
    username = st.session_state.get("login_username", "").strip()
    password = st.session_state.get("login_password", "").strip()
    if username and password:
        user = login_user(username, password)
        if user:
            authenticate(user, rerun=False)


def submit_register_from_fields() -> None:
    username = st.session_state.get("register_username", "").strip()
    email = st.session_state.get("register_email", "").strip()
    password = st.session_state.get("register_password", "").strip()
    if len(username) >= 3 and looks_like_email(email) and len(password) >= 4:
        user = register_user(username, email, password)
        if user:
            authenticate(user, rerun=False)


def authenticate(user: dict[str, Any], *, rerun: bool = True) -> None:
    st.session_state.user = user
    st.session_state.is_authenticated = True
    st.session_state.conversation_id = f"default-{user['id']}"
    st.session_state.selected_conversation_id = None
    st.session_state.should_scroll_bottom = True
    st.session_state.show_search = False
    st.session_state.search_query = ""
    st.session_state.search_results = None
    st.session_state.last_search_query = ""
    st.session_state.active_chat_type = "single"
    st.session_state.selected_group_id = None
    st.session_state.group_messages = []
    st.session_state.group_last_message_id = 0
    st.session_state.group_messages_group_id = None
    st.session_state.invite_panel_group_id = None
    st.session_state.show_user_info_editor = False
    st.session_state.show_user_menu = False
    st.session_state.cached_conversations = []
    st.session_state.cached_groups = []
    st.session_state.cached_invitations = []
    st.query_params["user_id"] = str(user["id"])
    st.query_params["username"] = user["username"]
    st.query_params["conversation_id"] = st.session_state.conversation_id
    st.query_params["chat_type"] = "single"
    if "group_id" in st.query_params:
        del st.query_params["group_id"]
    if rerun:
        st.rerun()


def fetch_messages(user_id: int, conversation_id: str):
    return api_request(
        "GET",
        "/messages",
        params={"user_id": user_id, "conversation_id": conversation_id, "limit": 100},
    )


def fetch_conversations(user_id: int):
    return api_request("GET", "/conversations", params={"user_id": user_id})


def send_message(sender_id: int, content: str, conversation_id: str):
    return api_request(
        "POST",
        "/messages",
        json={"sender_id": sender_id, "content": content, "conversation_id": conversation_id},
    )


def create_conversation(user_id: int, title: str = "New Chat"):
    return api_request("POST", "/conversations", json={"user_id": user_id, "title": title})


def search_messages(user_id: int, query: str):
    return api_request("GET", "/messages/search", params={"user_id": user_id, "q": query})


def search_chats_and_messages(user_id: int, query: str):
    return api_request("GET", "/search", params={"user_id": user_id, "q": query})


def fetch_gemini_status(user_id: int):
    return api_request("GET", "/settings/gemini", params={"user_id": user_id})


def create_group(user_id: int, name: str):
    return api_request("POST", "/groups/create", json={"user_id": user_id, "name": name})


def fetch_groups(user_id: int):
    return api_request("GET", "/groups/my", params={"user_id": user_id})


def invite_user_to_group(group_id: int, inviter_user_id: int, invited_identity: str):
    identity = invited_identity.strip()
    payload: dict[str, Any] = {"inviter_user_id": inviter_user_id}
    if "@" in identity:
        payload["invited_email"] = identity.lower()
    elif identity.startswith("#") and identity[1:].isdigit():
        payload["invited_user_id"] = int(identity[1:])
    else:
        payload["invited_username"] = identity
    return api_request(
        "POST",
        f"/groups/{group_id}/invite",
        json=payload,
    )


def fetch_invitations(user_id: int):
    return api_request("GET", "/invitations/my", params={"user_id": user_id})


def accept_invitation(invitation_id: int, user_id: int):
    return api_request("POST", f"/invitations/{invitation_id}/accept", json={"user_id": user_id})


def decline_invitation(invitation_id: int, user_id: int):
    return api_request("POST", f"/invitations/{invitation_id}/decline", json={"user_id": user_id})


def fetch_group_messages(user_id: int, group_id: int, after_id: int | None = None):
    if after_id:
        return api_request(
            "GET",
            f"/groups/{group_id}/messages/new",
            params={"user_id": user_id, "after_id": after_id, "limit": 100},
        )
    return api_request(
        "GET",
        f"/groups/{group_id}/messages",
        params={"user_id": user_id, "limit": 100},
    )


def fetch_group_typing(user_id: int, group_id: int):
    return api_request("GET", f"/groups/{group_id}/typing", params={"user_id": user_id})


def send_group_message(sender_id: int, group_id: int, content: str):
    return api_request(
        "POST",
        f"/groups/{group_id}/messages",
        json={"sender_id": sender_id, "content": content},
    )


def fetch_chat_shell_endpoint(endpoint: str, user_id: int) -> list[dict[str, Any]] | None:
    try:
        response = requests.get(
            f"{API_BASE_URL}{endpoint}",
            params={"user_id": user_id},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def fetch_chat_shell_data(user_id: int) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        conversations_future = executor.submit(fetch_chat_shell_endpoint, "/conversations", user_id)
        groups_future = executor.submit(fetch_chat_shell_endpoint, "/groups/my", user_id)
        return conversations_future.result(), groups_future.result()


@st.cache_data
def logo_background_value() -> str:
    if not LOGO_PATH.exists():
        return "none"
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"url('data:image/png;base64,{encoded}')"


def format_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        return parsed.astimezone(ZoneInfo("Asia/Jerusalem")).strftime("%H:%M")
    except ValueError:
        return value


def truncate_text(value: str | None, max_length: int = 72) -> str:
    if not value:
        return "No messages yet"
    compact = " ".join(value.split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[: max_length - 1].rstrip()}..."


def conversation_label(conversation: dict[str, Any]) -> str:
    preview = truncate_text(conversation.get("last_message"), 48)
    updated_at = format_timestamp(conversation["updated_at"])
    return f"{conversation['title']}  ·  {preview}  ·  {updated_at}"


def group_label(group: dict[str, Any]) -> str:
    preview = truncate_text(group.get("last_message"), 42)
    updated_at = format_timestamp(group["updated_at"])
    member_word = "member" if group["member_count"] == 1 else "members"
    return f"{group['name']} · {group['member_count']} {member_word} · {preview} · {updated_at}"


GROUP_NAME_COLORS = [
    "#d9772f",
    "#2e7d76",
    "#7c5cc4",
    "#b14f6a",
    "#5b6f2a",
    "#bf6a25",
    "#2f6ea5",
    "#8a5a2d",
]


def group_sender_color(message: dict[str, Any]) -> str:
    if message.get("sender_type") == "bot":
        return "#d9772f"
    sender_id = message.get("sender_user_id")
    if isinstance(sender_id, int):
        return GROUP_NAME_COLORS[sender_id % len(GROUP_NAME_COLORS)]
    name = message.get("sender_display_name") or ""
    return GROUP_NAME_COLORS[sum(ord(character) for character in name) % len(GROUP_NAME_COLORS)]


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
    logo_background = logo_background_value()
    st.markdown(
        """
        <style>
        :root {
            --cb-bg: #f6efe4;
            --cb-surface: rgba(255, 250, 241, 0.82);
            --cb-surface-solid: #fffaf1;
            --cb-text: #1f1f1d;
            --cb-muted: #7d7768;
            --cb-orange: #d9772f;
            --cb-orange-soft: #e7a15f;
            --cb-olive: #7c7a63;
            --cb-border: rgba(90, 74, 52, 0.16);
            --cb-shadow: rgba(55, 43, 28, 0.16);
            --bg: var(--cb-bg);
            --glass: var(--cb-surface);
            --glass-strong: rgba(255, 250, 241, 0.92);
            --text: var(--cb-text);
            --muted: var(--cb-muted);
            --line: var(--cb-border);
            --accent: var(--cb-orange);
            --accent-soft: rgba(231, 161, 95, 0.24);
            --user: #2c2620;
            --bot: rgba(255, 250, 241, 0.94);
            --shadow: 0 20px 70px var(--cb-shadow);
            --ui-radius: 24px;
        }

        .stApp {
            background:
                radial-gradient(circle at 16% 4%, rgba(201, 100, 66, 0.16), transparent 32%),
                radial-gradient(circle at 88% 12%, rgba(245, 223, 213, 0.85), transparent 30%),
                linear-gradient(180deg, #fbf9f4 0%, var(--bg) 100%);
            color: var(--text);
        }

        .stApp:has(.auth-page) {
            background: var(--cb-bg);
        }

        .stApp:has(.auth-page)::before {
            content: "";
            position: fixed;
            inset: 0;
            background-image: __CHAT_BRO_LOGO__;
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            opacity: 0.4;
            filter: saturate(0.94) blur(0.3px);
            pointer-events: none;
            z-index: 0;
        }

        .stApp:has(.auth-page)::after {
            content: "";
            position: fixed;
            inset: 0;
            background: linear-gradient(180deg, rgba(246,239,228,0.36), rgba(255,250,241,0.50));
            pointer-events: none;
            z-index: 0;
        }

        .block-container {
            max-width: 1040px;
            padding: 28px 22px 34px;
            position: relative;
            z-index: 1;
        }

        #MainMenu, footer, header {
            visibility: hidden;
        }

        .stApp:has(.auth-page) div[data-testid="stTabs"] [role="tablist"] {
            justify-content: center;
            gap: 8px;
        }

        .stApp:has(.auth-page) div[data-testid="stTabs"] {
            max-width: 460px;
            margin: 0 auto 24px;
            padding: 18px 22px 22px;
            border: 1px solid var(--line);
            border-radius: 28px;
            background: var(--glass-strong);
            box-shadow: 0 18px 55px rgba(55,43,28,0.13);
            backdrop-filter: blur(22px);
        }

        button[data-baseweb="tab"] {
            color: var(--text) !important;
            font-weight: 800 !important;
            opacity: 1 !important;
            padding-left: 14px !important;
            padding-right: 14px !important;
            border-radius: 999px !important;
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
            margin: 5vh auto 18px;
            padding: 28px 26px;
            text-align: center;
            background: rgba(255, 250, 241, 0.78);
            border: 1px solid var(--line);
            border-radius: 28px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(22px);
            transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
        }

        .auth-hero:hover {
            transform: translateY(-2px);
            border-color: rgba(201, 100, 66, 0.28);
            box-shadow: 0 24px 80px rgba(54, 43, 31, 0.15);
        }

        .auth-page {
            display: none;
        }

        .title {
            margin: 0;
            color: var(--text);
            font-size: 34px;
            line-height: 1.12;
            font-weight: 820;
            letter-spacing: 0;
            white-space: nowrap;
        }

        .subtitle {
            max-width: 540px;
            margin: 12px auto 0;
            color: var(--muted);
            font-size: 16px;
            line-height: 1.55;
            font-weight: 720;
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

        div[data-testid="stHorizontalBlock"]:has(.topbar-brand-block):has(.topbar-message-block) {
            align-items: center;
            gap: 16px;
            padding: 12px 18px;
            margin-bottom: 18px;
            background: var(--glass);
            border: 1px solid var(--line);
            border-radius: var(--ui-radius);
            box-shadow: 0 14px 45px rgba(54,43,31,0.08);
            backdrop-filter: blur(20px);
        }

        .topbar-brand-block {
            display: flex;
            align-items: center;
            min-height: 44px;
        }

        .topbar-message-block {
            min-height: 44px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .topbar-message {
            flex: 1;
            color: var(--muted);
            font-size: 15px;
            line-height: 1.45;
            text-align: center;
            font-weight: 780;
            direction: rtl;
            unicode-bidi: isolate;
        }

        .brand {
            position: relative;
            display: inline-flex;
            font-size: 34px;
            font-weight: 900;
            color: var(--text);
            letter-spacing: 0;
            line-height: 1;
        }

        .brand span {
            color: var(--accent);
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

        div[data-testid="stHorizontalBlock"]:has(.topbar-brand-block) div[data-testid="stPopover"] button {
            min-height: 42px;
            min-width: 120px;
            width: auto !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 6px !important;
            padding: 0 14px !important;
            line-height: 1 !important;
            border-radius: var(--ui-radius) !important;
            border: 1px solid rgba(171,83,31,0.28) !important;
            background: linear-gradient(135deg, #e88a34, #c96525) !important;
            color: #fffaf1 !important;
            font-weight: 850 !important;
            box-shadow: 0 12px 26px rgba(137,89,42,0.18) !important;
            white-space: nowrap;
        }

        div[data-testid="stHorizontalBlock"]:has(.topbar-brand-block) button[data-testid="stPopoverButton"] > div {
            width: 100% !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 6px !important;
        }

        div[data-testid="stHorizontalBlock"]:has(.topbar-brand-block) button[data-testid="stPopoverButton"] div[aria-hidden="true"] {
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1 !important;
        }

        div[data-testid="stHorizontalBlock"]:has(.topbar-brand-block) div[data-testid="stPopover"] button:hover {
            border-color: rgba(217,119,47,0.30) !important;
            background: linear-gradient(135deg, #f09b4a, #d9772f) !important;
            color: #fffaf1 !important;
        }

        div[data-testid="stHorizontalBlock"]:has(.topbar-brand-block) div[data-testid="stPopover"] button p,
        div[data-testid="stHorizontalBlock"]:has(.topbar-brand-block) div[data-testid="stPopover"] button svg {
            margin: 0 !important;
            line-height: 1 !important;
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

        .sidebar-title {
            margin: 0 0 8px;
            color: var(--text);
            font-size: 14px;
            font-weight: 850;
        }

        .sidebar-caption {
            margin: 0 0 12px;
            color: var(--muted);
            font-size: 12px;
            line-height: 1.45;
        }

        div[data-testid="stExpander"] {
            margin-bottom: 6px;
            border: 1px solid rgba(137, 89, 42, 0.18);
            border-radius: var(--ui-radius);
            background: rgba(255,250,241,0.58);
            box-shadow: 0 12px 30px rgba(54,43,31,0.06);
            overflow: hidden;
        }

        div[data-testid="stExpander"] details {
            border: 0 !important;
        }

        div[data-testid="stExpander"] summary {
            min-height: 46px;
            padding: 8px 12px;
            background: rgba(255,250,241,0.96) !important;
            border-bottom: 1px solid rgba(137, 89, 42, 0.14);
        }

        div[data-testid="stExpander"] summary,
        div[data-testid="stExpander"] summary * {
            color: var(--text) !important;
            -webkit-text-fill-color: var(--text) !important;
        }

        div[data-testid="stExpander"] summary p {
            color: var(--text) !important;
            font-size: 15px;
            font-weight: 900;
        }

        div[data-testid="stExpander"] div[data-testid="stExpanderDetails"] {
            padding-top: 0;
        }

        div[role="radiogroup"] {
            gap: 8px;
        }

        div[role="radiogroup"] label {
            flex: 0 0 auto !important;
            width: 100%;
            min-height: 48px;
            padding: 10px 12px !important;
            margin-bottom: 8px;
            border: 1px solid rgba(137, 89, 42, 0.18);
            border-radius: 16px;
            background: linear-gradient(135deg, rgba(231,161,95,0.48), rgba(255,250,241,0.72));
            color: var(--text) !important;
            transition: transform 160ms ease, border-color 160ms ease, background 160ms ease, box-shadow 160ms ease;
        }

        div[role="radiogroup"] label:not(:has(input:checked)),
        div[role="radiogroup"] label:not(:has(input:checked)) p,
        div[role="radiogroup"] label:not(:has(input:checked)) span {
            color: var(--text) !important;
            -webkit-text-fill-color: var(--text) !important;
        }

        div[role="radiogroup"] label p,
        div[role="radiogroup"] label span {
            color: inherit !important;
        }

        div[role="radiogroup"] label:hover {
            transform: translateY(-1px);
            border-color: rgba(217,119,47,0.34);
            background: linear-gradient(135deg, rgba(231,161,95,0.62), rgba(255,250,241,0.90));
            box-shadow: 0 10px 22px rgba(55,43,28,0.10);
        }

        div[role="radiogroup"] label:has(input:checked) {
            border-color: rgba(95, 65, 34, 0.42);
            background: linear-gradient(135deg, #d9772f, #c96d2c);
            color: #fffaf1 !important;
            -webkit-text-fill-color: #fffaf1 !important;
            box-shadow: 0 12px 26px rgba(137,89,42,0.20);
        }

        div[role="radiogroup"] label:has(input:checked) p,
        div[role="radiogroup"] label:has(input:checked) span {
            color: #fffaf1 !important;
            -webkit-text-fill-color: #fffaf1 !important;
        }

        .search-result {
            padding: 10px 0 8px;
            border-bottom: 1px solid rgba(96,76,55,0.13);
        }

        .search-result:last-child {
            border-bottom: 0;
        }

        .search-meta {
            margin-bottom: 5px;
            color: var(--muted);
            font-size: 11px;
            font-weight: 760;
        }

        .search-text {
            color: var(--text);
            font-size: 13px;
            line-height: 1.42;
            overflow-wrap: anywhere;
        }

        .search-kind {
            display: inline-flex;
            margin-right: 6px;
            padding: 2px 7px;
            border-radius: 999px;
            background: rgba(231,161,95,0.22);
            color: #79411e;
            font-size: 10px;
            font-weight: 850;
        }

        div[class*="st-key-toggle_invite_group_"] button {
            width: 46px !important;
            min-width: 46px !important;
            height: 46px !important;
            min-height: 46px !important;
            padding: 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            text-align: center !important;
            line-height: 1 !important;
            overflow: hidden !important;
            border-radius: 999px !important;
            border: 1px solid rgba(217,119,47,0.30) !important;
            background: rgba(255,250,241,0.86) !important;
            color: var(--accent) !important;
            box-shadow: 0 12px 26px rgba(137,89,42,0.10) !important;
        }

        div[class*="st-key-toggle_invite_group_"] button p,
        div[class*="st-key-toggle_invite_group_"] button div[data-testid="stMarkdownContainer"],
        .st-key-toggle_login_password button p,
        .st-key-toggle_login_password button div[data-testid="stMarkdownContainer"],
        .st-key-toggle_register_password button p,
        .st-key-toggle_register_password button div[data-testid="stMarkdownContainer"],
        div[data-testid="stForm"]:has(input[placeholder="Search chats, groups, emails..."]) div[data-testid="stFormSubmitButton"] button div[data-testid="stMarkdownContainer"],
        div[data-testid="stForm"]:has(input[placeholder="Search chats, groups, emails..."]) div[data-testid="stFormSubmitButton"] button p {
            display: none !important;
            width: 0 !important;
            min-width: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            line-height: 0 !important;
        }

        div[class*="st-key-toggle_invite_group_"] button:hover {
            transform: translateY(-1px);
            background: #fffaf1 !important;
            box-shadow: 0 16px 32px rgba(137,89,42,0.15) !important;
        }

        div[data-testid="stForm"]:has(input[placeholder="Invite by email..."]) {
            animation: invite-drawer-in 260ms ease both;
            transform-origin: top right;
            margin: 10px auto 16px;
            max-width: 560px;
            padding: 8px;
            border: 1px solid rgba(217,119,47,0.16);
            border-radius: 24px;
            background: rgba(255,250,241,0.66);
            box-shadow: 0 16px 42px rgba(54,43,31,0.08);
        }

        @keyframes invite-drawer-in {
            from {
                opacity: 0;
                transform: translateY(-8px) scale(0.98);
            }
            to {
                opacity: 1;
                transform: translateY(0) scale(1);
            }
        }

        .section-divider {
            height: 1px;
            margin: 16px 0 12px;
            background: rgba(96,76,55,0.14);
        }

        .group-note,
        .invitation-card {
            margin: 8px 0;
            padding: 10px 12px;
            border-radius: 16px;
            background: rgba(255,250,241,0.72);
            border: 1px solid rgba(96,76,55,0.14);
            color: var(--text);
            font-size: 13px;
            line-height: 1.4;
        }

        .group-card-active {
            margin: 8px 0;
            padding: 10px 12px;
            border-radius: 16px;
            background: linear-gradient(135deg, #d9772f, #c96d2c);
            color: #fffaf1;
            font-size: 13px;
            font-weight: 800;
            box-shadow: 0 12px 26px rgba(137,89,42,0.20);
        }

        .group-controls {
            margin-bottom: 12px;
            padding: 10px 12px;
            border-radius: 18px;
            background: rgba(255,250,241,0.58);
            border: 1px solid rgba(96,76,55,0.12);
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
            font-size: 15px;
            line-height: 1.5;
            text-align: center;
            font-weight: 700;
        }

        .chat-intro[dir="rtl"] {
            direction: rtl;
            unicode-bidi: isolate;
        }

        .messages {
            display: flex;
            flex-direction: column-reverse;
            gap: 12px;
            height: min(58vh, 560px);
            min-height: 360px;
            overflow-y: auto;
            scroll-behavior: auto;
            overflow-anchor: none;
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

        .bubble.system {
            max-width: min(620px, 82%);
            background: rgba(245,223,213,0.62);
            border: 1px solid rgba(201,100,66,0.18);
            color: #6e4328;
            text-align: center;
            font-size: 13px;
            font-weight: 720;
            box-shadow: none;
        }

        .sender {
            display: none;
        }

        .group-sender {
            display: block;
            margin-bottom: 5px;
            font-size: 12px;
            font-weight: 850;
            opacity: 1;
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

        .typing-label {
            margin-right: 5px;
            color: var(--muted);
            font-size: 12px;
            font-weight: 820;
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

        div[data-testid="stForm"]:has(input[placeholder="Search chats, groups, emails..."]) {
            max-width: none;
            margin: 0 0 14px;
            padding: 0;
            border: 0;
            border-radius: 0;
            background: transparent;
            box-shadow: none;
            backdrop-filter: none;
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

        div[data-testid="stTextInput"] button {
            display: none !important;
        }

        div[data-testid="stTextInput"]:has(input[placeholder="Search chats, groups, emails..."]) div[data-baseweb="input"] {
            border-radius: 999px !important;
            border-color: rgba(217,119,47,0.24) !important;
            background: rgba(255,250,241,0.88) !important;
        }

        div[data-testid="stTextInput"]:has(input[placeholder="Search chats, groups, emails..."]) input {
            background-image: none !important;
            padding-right: 1rem !important;
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

        .stButton > button:focus,
        div[data-testid="stFormSubmitButton"] button:focus,
        div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {
            outline: 3px solid rgba(217,119,47,0.20) !important;
            outline-offset: 2px !important;
        }

        button:has(span[data-testid="stIconMaterial"]) {
            min-width: 48px !important;
            width: 48px !important;
            height: 44px !important;
            min-height: 44px !important;
            padding: 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            text-align: center !important;
            line-height: 1 !important;
            overflow: hidden !important;
            border-radius: 999px !important;
            background: rgba(255,250,241,0.88) !important;
            border: 1px solid rgba(217,119,47,0.24) !important;
            color: var(--cb-orange) !important;
            box-shadow: 0 6px 16px rgba(55,43,28,0.07) !important;
        }

        button:has(span[data-testid="stIconMaterial"]) > div,
        button:has(span[data-testid="stIconMaterial"]) span[data-has-shortcut="false"],
        button:has(span[data-testid="stIconMaterial"]) span[data-testid="stIconMaterial"] + div,
        button:has(span[data-testid="stIconMaterial"]) span:has(> span[data-testid="stIconMaterial"]) {
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 100% !important;
            height: 100% !important;
            min-width: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            gap: 0 !important;
            line-height: 1 !important;
        }

        button:has(span[data-testid="stIconMaterial"]) div[data-testid="stMarkdownContainer"]:empty {
            display: none !important;
        }

        button:has(span[data-testid="stIconMaterial"]) span[data-testid="stIconMaterial"] {
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 20px !important;
            height: 20px !important;
            margin: 0 !important;
            line-height: 1 !important;
            font-size: 20px !important;
            text-align: center !important;
        }

        .st-key-toggle_login_password button:has(span[data-testid="stIconMaterial"]),
        .st-key-toggle_register_password button:has(span[data-testid="stIconMaterial"]) {
            height: 40px !important;
            min-height: 40px !important;
            margin-top: 12px !important;
        }

        button:has(span[data-testid="stIconMaterial"]):hover {
            background: rgba(231,161,95,0.18) !important;
            border-color: rgba(217,119,47,0.42) !important;
            color: #a95322 !important;
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

        div[data-testid="stForm"]:has(input[placeholder="Search chats, groups, emails..."]) div[data-testid="stFormSubmitButton"] button {
            min-width: 44px !important;
            width: 44px !important;
            height: 44px !important;
            min-height: 44px !important;
            padding: 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            text-align: center !important;
            line-height: 1 !important;
            background: rgba(255,250,241,0.88) !important;
            color: var(--cb-orange) !important;
            border-color: rgba(217,119,47,0.24) !important;
            box-shadow: 0 6px 16px rgba(55,43,28,0.07) !important;
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
            align-items: flex-start;
        }

        .stApp div[data-testid="stForm"],
        .stApp div[data-testid="stTabs"],
        .stApp div[data-testid="stExpander"],
        .stApp .auth-hero,
        .stApp .chat-panel,
        .stApp .messages,
        .stApp .empty-state,
        .stApp .group-note,
        .stApp .invitation-card,
        .stApp .group-card-active,
        .stApp .group-controls,
        .stApp .bubble,
        .stApp .typing-bubble,
        .stApp div[data-baseweb="input"],
        .stApp .stButton > button,
        .stApp div[data-testid="stFormSubmitButton"] button,
        .stApp div[data-testid="stPopover"] button,
        .stApp button[data-baseweb="tab"] {
            border-radius: var(--ui-radius) !important;
        }

        .stApp div[data-testid="stHorizontalBlock"]:has(.topbar-brand-block) div[data-testid="stPopover"] button {
            min-width: 120px !important;
            width: auto !important;
            background: linear-gradient(135deg, #e88a34, #c96525) !important;
            border-color: rgba(171,83,31,0.28) !important;
            color: #fffaf1 !important;
            box-shadow: 0 12px 26px rgba(137,89,42,0.18) !important;
        }

        .stApp:has(.auth-page) [data-testid="stHorizontalBlock"],
        div[data-testid="stForm"]:has(input[placeholder="Message Chat Bro..."]) [data-testid="stHorizontalBlock"],
        div[data-testid="stForm"]:has(input[placeholder="Search chats, groups, emails..."]) [data-testid="stHorizontalBlock"] {
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
                white-space: normal;
            }

            .topbar {
                border-radius: 24px;
                align-items: flex-start;
                flex-direction: column;
            }

            div[role="radiogroup"] label {
                min-height: 44px;
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
        """.replace("__CHAT_BRO_LOGO__", logo_background),
        unsafe_allow_html=True,
    )


def install_message_autoscroll() -> None:
    st.html(
        """
        <script>
        (() => {
            const doc = window.parent && window.parent.document ? window.parent.document : document;
            const view = doc.defaultView || window;
            const scrollPane = (pane, force = false) => {
                if (!pane) {
                    return;
                }
                if (!force && doc.__chatBroUserScrolledMessages) {
                    pane.scrollTop = doc.__chatBroSavedMessageScrollTop || pane.scrollTop;
                    return;
                }
                pane.scrollTop = 0;
            };
            const scrollAllMessages = (force = false) => {
                const panes = doc.querySelectorAll(".messages");
                if (!panes.length) {
                    return;
                }
                panes.forEach((pane) => {
                    scrollPane(pane, force);
                });
            };
            const scheduleScroll = (force = false) => {
                if (force) {
                    doc.__chatBroUserScrolledMessages = false;
                    doc.__chatBroSavedMessageScrollTop = 0;
                }
                view.requestAnimationFrame(() => scrollAllMessages(force));
                [25, 75, 160, 320, 650, 1100, 1800].forEach((delay) => {
                    view.setTimeout(() => scrollAllMessages(force), delay);
                });
            };

            doc.__chatBroScrollToBottom = scheduleScroll;
            const bindScrollMemory = () => {
                doc.querySelectorAll(".messages").forEach((pane) => {
                    if (pane.dataset.chatBroScrollMemory === "true") {
                        return;
                    }
                    pane.dataset.chatBroScrollMemory = "true";
                    pane.addEventListener("scroll", () => {
                        const userScrolled = Math.abs(pane.scrollTop) > 24;
                        pane.dataset.chatBroUserScrolled = userScrolled ? "true" : "false";
                        doc.__chatBroUserScrolledMessages = userScrolled;
                        doc.__chatBroSavedMessageScrollTop = userScrolled ? pane.scrollTop : 0;
                    }, { passive: true });
                });
            };
            bindScrollMemory();
            view.setInterval(bindScrollMemory, 1000);
            scheduleScroll(false);
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
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


def group_message_bubble_html(message: dict[str, Any], current_user_id: int) -> str:
    sender_type = message.get("sender_type", "user")
    is_current_user = sender_type == "user" and message.get("sender_user_id") == current_user_id
    if sender_type == "system":
        row_class = "left"
        bubble_class = "system"
    else:
        row_class = "right" if is_current_user else "left"
        bubble_class = "right" if is_current_user else "left"

    raw_content = message["content"]
    content = format_message_content(raw_content)
    created_at = escape(format_timestamp(message["created_at"]))
    direction = "rtl" if contains_hebrew(raw_content) else "ltr"
    alignment = "center" if sender_type == "system" else ("right" if direction == "rtl" else "left")
    sender_name = escape(message.get("sender_display_name") or "Unknown")
    if sender_type == "bot":
        sender_name = f"{sender_name} · chatbot"
    elif sender_type == "system":
        sender_name = "System"

    sender_color = group_sender_color(message)
    sender_html = (
        ""
        if sender_type == "system"
        else f'<div class="group-sender" style="color: {sender_color};">{sender_name}</div>'
    )
    return (
        f'<div class="msg-row {row_class}">'
        f'<div class="bubble {bubble_class}" dir="{direction}" style="text-align: {alignment};">'
        f"{sender_html}"
        f'<div class="message-content">{content}</div>'
        f'<div class="meta">{created_at}</div>'
        "</div>"
        "</div>"
    )


def append_group_messages(messages: list[dict[str, Any]]) -> None:
    existing_ids = {message["id"] for message in st.session_state.group_messages}
    added = []
    for message in messages:
        if message["id"] in existing_ids:
            continue
        existing_ids.add(message["id"])
        added.append(message)
    if not added:
        return

    st.session_state.group_messages = sorted(
        [*st.session_state.group_messages, *added],
        key=lambda message: message["id"],
    )
    st.session_state.group_last_message_id = max(
        st.session_state.group_last_message_id,
        *(message["id"] for message in added),
    )


def sync_group_messages(user_id: int, group_id: int) -> bool:
    if st.session_state.group_messages_group_id != group_id:
        st.session_state.group_messages = []
        st.session_state.group_last_message_id = 0
        st.session_state.group_messages_group_id = group_id

    previous_count = len(st.session_state.group_messages)
    messages = fetch_group_messages(
        user_id,
        group_id,
        after_id=st.session_state.group_last_message_id or None,
    )
    if messages is None:
        st.stop()
    append_group_messages(messages)
    return len(st.session_state.group_messages) > previous_count


def typing_indicator_html(label: str = "Chat Bro is typing") -> str:
    safe_label = escape(label)
    return (
        '<div class="msg-row left">'
        f'<div class="typing-bubble" aria-label="{safe_label}">'
        f'<span class="typing-label">{safe_label}</span>'
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
    message_items = [message_bubble_html(message, current_user_id) for message in messages]
    if show_typing:
        message_items.append(typing_indicator_html())
    messages_html = "\n".join(reversed(message_items))

    st.markdown(
        f'<div class="messages"><div class="message-bottom-anchor"></div>{messages_html}</div>',
        unsafe_allow_html=True,
    )


def render_group_messages(
    messages: list[dict[str, Any]],
    current_user_id: int,
    show_bot_typing: bool,
    typing_users: list[dict[str, Any]],
) -> None:
    message_items = [group_message_bubble_html(message, current_user_id) for message in messages]
    if show_bot_typing:
        message_items.append(typing_indicator_html("Chat Bro is typing"))
    if typing_users:
        names = ", ".join(user["username"] for user in typing_users[:3])
        verb = "are" if len(typing_users) > 1 else "is"
        message_items.append(typing_indicator_html(f"{names} {verb} typing"))
    messages_html = "\n".join(reversed(message_items))
    st.markdown(
        f'<div class="messages"><div class="message-bottom-anchor"></div>{messages_html}</div>',
        unsafe_allow_html=True,
    )


def scroll_messages_to_bottom(force: bool) -> None:
    force_js = "true" if force else "false"
    st.html(
        f"""
        <script>
        (() => {{
        const forceScroll = {force_js};
        const scrollLatestMessages = () => {{
            const doc = window.parent && window.parent.document ? window.parent.document : document;
            if (forceScroll) {{
                doc.__chatBroUserScrolledMessages = false;
                doc.__chatBroSavedMessageScrollTop = 0;
            }}
            if (doc.__chatBroScrollToBottom) {{
                doc.__chatBroScrollToBottom(forceScroll);
                return;
            }}
            const containers = doc.querySelectorAll('.messages');
            const latest = containers[containers.length - 1];
            if (latest && (forceScroll || !doc.__chatBroUserScrolledMessages)) {{
                latest.scrollTop = 0;
            }}
        }};
        window.requestAnimationFrame(scrollLatestMessages);
        [25, 75, 160, 320, 650, 1100, 1800].forEach((delay) => setTimeout(scrollLatestMessages, delay));
        }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def render_group_typing_capture(user_id: int, group_id: int) -> None:
    api_base_url = json.dumps(API_BASE_URL)
    st.html(
        f"""
        <script>
        (() => {{
            const apiBaseUrl = {api_base_url};
            const userId = {user_id};
            const groupId = {group_id};
            const doc = window.parent && window.parent.document ? window.parent.document : document;
            const view = doc.defaultView || window;

            const sendTyping = (() => {{
                let lastSentAt = 0;
                let lastState = null;
                return (isTyping, force = false) => {{
                    const now = Date.now();
                    if (!force && isTyping && lastState === true && now - lastSentAt < 800) {{
                        return;
                    }}
                    if (!force && !isTyping && lastState === false && now - lastSentAt < 800) {{
                        return;
                    }}
                    lastSentAt = now;
                    lastState = isTyping;
                    fetch(`${{apiBaseUrl}}/groups/${{groupId}}/typing`, {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        body: JSON.stringify({{ user_id: userId, is_typing: isTyping }}),
                        keepalive: true,
                    }}).catch(() => {{}});
                }};
            }})();

            const attachToInput = (input) => {{
                if (!input || input.dataset.chatBroTypingGroup === String(groupId)) {{
                    return;
                }}
                if (input.chatBroTypingCleanup) {{
                    input.chatBroTypingCleanup();
                }}
                input.dataset.chatBroTypingGroup = String(groupId);
                let idleTimer = null;
                let heartbeatTimer = null;
                const startHeartbeat = () => {{
                    if (!heartbeatTimer) {{
                        heartbeatTimer = view.setInterval(() => sendTyping(true), 1500);
                    }}
                }};
                const stopHeartbeat = () => {{
                    if (heartbeatTimer) {{
                        view.clearInterval(heartbeatTimer);
                        heartbeatTimer = null;
                    }}
                }};
                const onInput = () => {{
                    if (!input.value) {{
                        stopHeartbeat();
                        sendTyping(false, true);
                        return;
                    }}
                    sendTyping(true);
                    startHeartbeat();
                    view.clearTimeout(idleTimer);
                    idleTimer = view.setTimeout(() => {{
                        stopHeartbeat();
                        sendTyping(false, true);
                    }}, 3200);
                }};
                const onBlur = () => {{
                    stopHeartbeat();
                    sendTyping(false, true);
                }};
                const onKeydown = (event) => {{
                    if (event.key === "Enter") {{
                        view.setTimeout(() => {{
                            stopHeartbeat();
                            sendTyping(false, true);
                        }}, 0);
                    }}
                }};
                input.addEventListener("input", onInput);
                input.addEventListener("blur", onBlur);
                input.addEventListener("keydown", onKeydown);
                input.chatBroTypingCleanup = () => {{
                    input.removeEventListener("input", onInput);
                    input.removeEventListener("blur", onBlur);
                    input.removeEventListener("keydown", onKeydown);
                    stopHeartbeat();
                }};
            }};

            const findMessageInput = () => {{
                const inputs = Array.from(doc.querySelectorAll('input[placeholder="Message Chat Bro..."]'));
                return inputs[inputs.length - 1] || null;
            }};
            const bindLatestInput = () => attachToInput(findMessageInput());
            bindLatestInput();

            if (doc.__chatBroTypingInputWatcher) {{
                view.clearInterval(doc.__chatBroTypingInputWatcher);
            }}
            doc.__chatBroTypingInputWatcher = view.setInterval(bindLatestInput, 700);

            view.addEventListener("beforeunload", () => {{
                const input = findMessageInput();
                if (input && input.chatBroTypingCleanup) {{
                    input.chatBroTypingCleanup();
                }}
                sendTyping(false, true);
            }});
        }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def render_message_area_content(user_id: int, conversation_id: str, auto_rerun_typing: bool) -> None:
    messages = fetch_messages(user_id, conversation_id)
    if messages is None:
        st.stop()

    show_typing = bool(messages and messages[-1]["role"] == "user")

    if not messages:
        st.markdown(
            '<div class="empty-state">No messages yet. Send the first one below.</div>',
            unsafe_allow_html=True,
        )
    else:
        render_messages(messages, user_id, show_typing)
        scroll_messages_to_bottom(st.session_state.should_scroll_bottom)
        st.session_state.should_scroll_bottom = False

    if show_typing and auto_rerun_typing:
        rerun_while_typing()


def render_group_message_area_content(user_id: int, group_id: int) -> None:
    has_new_messages = sync_group_messages(user_id, group_id)
    typing_users = fetch_group_typing(user_id, group_id)
    if typing_users is None:
        typing_users = []
    show_bot_typing = bool(
        st.session_state.group_messages
        and st.session_state.group_messages[-1].get("sender_type") == "user"
    )
    if not st.session_state.group_messages and not typing_users and not show_bot_typing:
        st.markdown(
            '<div class="empty-state">No group messages yet. Send the first one below.</div>',
            unsafe_allow_html=True,
        )
        return

    render_group_messages(st.session_state.group_messages, user_id, show_bot_typing, typing_users)
    scroll_messages_to_bottom(st.session_state.should_scroll_bottom)
    st.session_state.should_scroll_bottom = False


streamlit_fragment = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)

if streamlit_fragment:

    @streamlit_fragment(run_every=f"{POLLING_INTERVAL_SECONDS}s")
    def render_polled_message_area(user_id: int, conversation_id: str) -> None:
        render_message_area_content(user_id, conversation_id, auto_rerun_typing=False)

    @streamlit_fragment(run_every=f"{POLLING_INTERVAL_SECONDS}s")
    def render_polled_group_message_area(user_id: int, group_id: int) -> None:
        render_group_message_area_content(user_id, group_id)


else:

    def render_polled_message_area(user_id: int, conversation_id: str) -> None:
        render_message_area_content(user_id, conversation_id, auto_rerun_typing=True)

    def render_polled_group_message_area(user_id: int, group_id: int) -> None:
        render_group_message_area_content(user_id, group_id)


def rerun_while_typing() -> None:
    time.sleep(1.25)
    st.rerun()


def render_auth_screen() -> None:
    st.markdown(
        f"""
        <div class="auth-page"></div>
        <div class="auth-hero">
            <h1 class="title">Welcome to {PRODUCT_NAME}</h1>
            <p class="subtitle">When generations can communicate.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    login_tab, register_tab = st.tabs(["Login", "Register"])

    with login_tab:
        username_col, _username_spacer = st.columns([9, 1.5], gap="medium")
        with username_col:
            username = st.text_input("Username", key="login_username")
        password_col, visibility_col = st.columns([9, 1.5], gap="medium")
        with password_col:
            password = st.text_input(
                "Password",
                type="default" if st.session_state.show_login_password else "password",
                key="login_password",
            )
        with visibility_col:
            st.write("")
            if st.button(
                " ",
                key="toggle_login_password",
                type="tertiary",
                icon=":material/visibility_off:" if st.session_state.show_login_password else ":material/visibility:",
                help="Hide password" if st.session_state.show_login_password else "Show password",
            ):
                st.session_state.show_login_password = not st.session_state.show_login_password
                st.rerun()

        if st.button("Login", key="login_submit", use_container_width=True):
            if not username.strip() or not password.strip():
                st.warning("Please enter a username and password.")
            else:
                user = login_user(username, password)
                if user:
                    authenticate(user)

    with register_tab:
        username_col, _username_spacer = st.columns([9, 1.5], gap="medium")
        with username_col:
            username = st.text_input("Choose username", key="register_username")
        email_col, _email_spacer = st.columns([9, 1.5], gap="medium")
        with email_col:
            email = st.text_input("Email", key="register_email")
        password_col, visibility_col = st.columns([9, 1.5], gap="medium")
        with password_col:
            password = st.text_input(
                "Choose password",
                type="default" if st.session_state.show_register_password else "password",
                key="register_password",
            )
        with visibility_col:
            st.write("")
            if st.button(
                " ",
                key="toggle_register_password",
                type="tertiary",
                icon=":material/visibility_off:" if st.session_state.show_register_password else ":material/visibility:",
                help="Hide password" if st.session_state.show_register_password else "Show password",
            ):
                st.session_state.show_register_password = not st.session_state.show_register_password
                st.rerun()

        if st.button("Register", key="register_submit", use_container_width=True):
            if len(username.strip()) < 3:
                st.warning("Username must be at least 3 characters.")
            elif not looks_like_email(email):
                st.warning("Please enter a valid email.")
            elif len(password.strip()) < 4:
                st.warning("Password must be at least 4 characters.")
            else:
                user = register_user(username, email, password)
                if user:
                    authenticate(user)


def select_conversation(conversation: dict[str, Any], *, scroll_bottom: bool = True) -> None:
    st.session_state.active_chat_type = "single"
    st.session_state.selected_conversation_id = conversation["id"]
    st.session_state.conversation_id = conversation["conversation_id"]
    st.session_state.should_scroll_bottom = scroll_bottom
    st.query_params["conversation_id"] = conversation["conversation_id"]
    st.query_params["chat_type"] = "single"
    if "group_id" in st.query_params:
        del st.query_params["group_id"]


def select_group(group: dict[str, Any], *, scroll_bottom: bool = True) -> None:
    st.session_state.active_chat_type = "group"
    st.session_state.selected_group_id = group["id"]
    st.session_state.should_scroll_bottom = scroll_bottom
    st.session_state.group_messages = []
    st.session_state.group_last_message_id = 0
    st.session_state.group_messages_group_id = None
    st.query_params["chat_type"] = "group"
    st.query_params["group_id"] = str(group["id"])


def select_group_id(group_id: int, *, scroll_bottom: bool = True) -> None:
    st.session_state.active_chat_type = "group"
    st.session_state.selected_group_id = group_id
    st.session_state.should_scroll_bottom = scroll_bottom
    st.session_state.group_messages = []
    st.session_state.group_last_message_id = 0
    st.session_state.group_messages_group_id = None
    st.query_params["chat_type"] = "group"
    st.query_params["group_id"] = str(group_id)


def resolve_active_conversation(conversations: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not conversations:
        return None

    active_key = st.session_state.conversation_id
    active = next((conversation for conversation in conversations if conversation["conversation_id"] == active_key), None)
    if not active:
        active = conversations[0]
        select_conversation(active)
    else:
        st.session_state.selected_conversation_id = active["id"]
    return active


def render_conversation_list(conversations: list[dict[str, Any]]) -> dict[str, Any] | None:
    st.markdown('<p class="sidebar-title">Conversations</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sidebar-caption">Your saved chats stay here after refresh.</p>',
        unsafe_allow_html=True,
    )

    active = resolve_active_conversation(conversations)
    if not active:
        st.info("No conversations yet.")
        return None

    conversation_keys = [conversation["conversation_id"] for conversation in conversations]
    labels = {conversation["conversation_id"]: conversation_label(conversation) for conversation in conversations}
    with st.container(height=258, border=False):
        selected_key = st.radio(
            "Conversations",
            conversation_keys,
            index=conversation_keys.index(active["conversation_id"]),
            format_func=lambda key: labels[key],
            label_visibility="collapsed",
        )

    if selected_key != st.session_state.conversation_id:
        selected_conversation = next(
            conversation for conversation in conversations if conversation["conversation_id"] == selected_key
        )
        select_conversation(selected_conversation)
        st.rerun()

    return active


def resolve_active_group(groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    if st.session_state.active_chat_type != "group" or not groups:
        return None
    active_group_id = st.session_state.selected_group_id
    active = next((group for group in groups if group["id"] == active_group_id), None)
    if not active:
        st.session_state.active_chat_type = "single"
        st.session_state.selected_group_id = None
        return None
    return active


def render_group_creation(user_id: int) -> None:
    st.markdown('<p class="sidebar-title">Create group</p>', unsafe_allow_html=True)
    with st.form("create_group_form", clear_on_submit=True):
        group_name = st.text_input(
            "Group name",
            placeholder="New group name",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Create group", use_container_width=True)
    if submitted:
        if not group_name.strip():
            st.warning("Group name is required.")
        else:
            group = create_group(user_id, group_name)
            if group:
                select_group(group)
                st.rerun()


def render_group_list(groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    active = resolve_active_group(groups)
    if not groups:
        st.markdown('<div class="group-note">No group chats yet.</div>', unsafe_allow_html=True)
        return None

    with st.container(height=228, border=False):
        for group in groups:
            label = escape(group_label(group))
            if active and group["id"] == active["id"]:
                st.markdown(f'<div class="group-card-active">{label}</div>', unsafe_allow_html=True)
                continue
            if st.button(label, key=f"open_group_{group['id']}", use_container_width=True):
                select_group(group)
                st.rerun()
    return active


def render_invitations(user_id: int, invitations: list[dict[str, Any]] | None = None) -> None:
    if invitations is None:
        invitations = fetch_invitations(user_id)
    if invitations is not None:
        st.session_state.cached_invitations = invitations
    if invitations is None or not invitations:
        return

    st.markdown('<p class="sidebar-title">Invitations</p>', unsafe_allow_html=True)
    for invitation in invitations:
        group_name = escape(invitation["group_name"])
        invited_by = escape(invitation["invited_by_username"])
        st.markdown(
            f"""
            <div class="invitation-card">
                <strong>{group_name}</strong><br>
                Invited by {invited_by}
            </div>
            """,
            unsafe_allow_html=True,
        )
        accept_col, decline_col = st.columns(2)
        with accept_col:
            if st.button("Accept", key=f"accept_invitation_{invitation['id']}", use_container_width=True):
                accepted = accept_invitation(invitation["id"], user_id)
                if accepted:
                    st.session_state.active_chat_type = "group"
                    st.session_state.selected_group_id = accepted["group_id"]
                    st.session_state.group_messages = []
                    st.session_state.group_last_message_id = 0
                    st.session_state.group_messages_group_id = None
                    st.query_params["chat_type"] = "group"
                    st.query_params["group_id"] = str(accepted["group_id"])
                    st.rerun()
        with decline_col:
            if st.button("Decline", key=f"decline_invitation_{invitation['id']}", use_container_width=True):
                declined = decline_invitation(invitation["id"], user_id)
                if declined:
                    st.rerun()


if streamlit_fragment:

    @streamlit_fragment(run_every=f"{POLLING_INTERVAL_SECONDS}s")
    def render_polled_invitations(user_id: int, fallback: list[dict[str, Any]] | None = None) -> None:
        invitations = fetch_invitations(user_id)
        render_invitations(user_id, invitations if invitations is not None else fallback)


else:

    def render_polled_invitations(user_id: int, fallback: list[dict[str, Any]] | None = None) -> None:
        render_invitations(user_id, fallback)


def render_search_panel(user_id: int) -> None:
    with st.form("search_form", clear_on_submit=False):
        search_input_col, search_button_col = st.columns([5, 1], gap="small")
        with search_input_col:
            query = st.text_input(
                "Search chats, groups, emails, messages",
                key="search_query",
                placeholder="Search chats, groups, emails...",
                label_visibility="collapsed",
            )
        with search_button_col:
            search_submitted = st.form_submit_button(
                " ",
                icon=":material/search:",
                use_container_width=True,
                help="Search",
            )
    search_query = query.strip()
    if not search_query:
        st.session_state.search_results = None
        return

    if search_submitted or st.session_state.search_results is None or st.session_state.last_search_query != search_query:
        results = search_chats_and_messages(user_id, search_query)
        if results is not None:
            st.session_state.search_results = results
            st.session_state.last_search_query = search_query

    results = st.session_state.search_results
    if results is None:
        return
    conversations = results.get("conversations", []) if isinstance(results, dict) else []
    messages = results.get("messages", results if isinstance(results, list) else []) if results else []
    groups = results.get("groups", []) if isinstance(results, dict) else []
    group_messages = results.get("group_messages", []) if isinstance(results, dict) else []
    group_members = results.get("group_members", []) if isinstance(results, dict) else []

    unique_messages = []
    seen_message_keys = set()
    for result in messages:
        content = result.get("message_content") or result.get("content") or ""
        message_key = (result.get("id"), result.get("conversation_key"), content)
        fallback_key = (result.get("conversation_key"), result.get("sender_id"), content, result.get("created_at"))
        dedupe_key = message_key if result.get("id") is not None else fallback_key
        if dedupe_key in seen_message_keys:
            continue
        seen_message_keys.add(dedupe_key)
        unique_messages.append(result)
    messages = unique_messages

    unique_group_messages = []
    seen_group_message_keys = set()
    for result in group_messages:
        dedupe_key = (result.get("id"), result.get("group_id"), result.get("content"), result.get("created_at"))
        if dedupe_key in seen_group_message_keys:
            continue
        seen_group_message_keys.add(dedupe_key)
        unique_group_messages.append(result)
    group_messages = unique_group_messages

    if not conversations and not messages and not groups and not group_messages and not group_members:
        st.info("No matching chats or messages.")
        return

    for result in groups:
        group_name = escape(result.get("name", "Group"))
        preview = escape(truncate_text(result.get("last_message"), 90))
        timestamp = escape(format_timestamp(result["updated_at"]))
        member_count = result.get("member_count", 0)
        st.markdown(
            f"""
            <div class="search-result">
                <div class="search-meta"><span class="search-kind">GROUP</span>{member_count} members · {timestamp}</div>
                <div class="search-text"><strong>{group_name}</strong><br>{preview}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open group", key=f"open_search_group_{result['id']}", use_container_width=True):
            select_group_id(result["id"])
            st.rerun()

    for result in group_members:
        group_name = escape(result.get("group_name", "Group"))
        username = escape(result.get("username", "User"))
        email = escape(result.get("email") or "No email")
        role = escape(result.get("role", "member"))
        st.markdown(
            f"""
            <div class="search-result">
                <div class="search-meta"><span class="search-kind">MEMBER</span>{group_name} · {role}</div>
                <div class="search-text"><strong>{username}</strong><br>{email}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open group", key=f"open_search_group_member_{result['group_id']}_{result['user_id']}", use_container_width=True):
            select_group_id(result["group_id"])
            st.rerun()

    for result in group_messages:
        message_text = escape(truncate_text(result["content"], 120))
        sender = escape(result.get("sender_display_name", "unknown"))
        group_name = escape(result.get("group_name", "Group"))
        timestamp = escape(format_timestamp(result["created_at"]))
        st.markdown(
            f"""
            <div class="search-result">
                <div class="search-meta"><span class="search-kind">GROUP MSG</span>{group_name} · {sender} · {timestamp}</div>
                <div class="search-text">{message_text}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open group", key=f"open_search_group_message_{result['id']}", use_container_width=True):
            select_group_id(result["group_id"])
            st.rerun()

    for result in conversations:
        conversation_title = escape(result.get("title", "Conversation"))
        preview = escape(truncate_text(result.get("last_message"), 90))
        timestamp = escape(format_timestamp(result["updated_at"]))
        st.markdown(
            f"""
            <div class="search-result">
                <div class="search-meta"><span class="search-kind">CHAT</span>{timestamp}</div>
                <div class="search-text"><strong>{conversation_title}</strong><br>{preview}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open", key=f"open_search_conversation_{result['id']}", use_container_width=True):
            st.session_state.active_chat_type = "single"
            st.session_state.selected_group_id = None
            st.session_state.selected_conversation_id = result["id"]
            st.session_state.conversation_id = result["conversation_id"]
            st.session_state.should_scroll_bottom = True
            st.query_params["chat_type"] = "single"
            if "group_id" in st.query_params:
                del st.query_params["group_id"]
            st.rerun()

    for result in messages:
        message_text = escape(truncate_text(result["message_content"] or result["content"], 120))
        sender = escape(result.get("sender_username", "unknown"))
        conversation_title = escape(result.get("conversation_title", "Conversation"))
        timestamp = escape(format_timestamp(result["created_at"]))
        st.markdown(
            f"""
            <div class="search-result">
                <div class="search-meta"><span class="search-kind">MESSAGE</span>{conversation_title} · {sender} · {timestamp}</div>
                <div class="search-text">{message_text}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open", key=f"open_search_result_{result['id']}", use_container_width=True):
            st.session_state.active_chat_type = "single"
            st.session_state.selected_group_id = None
            st.session_state.selected_conversation_id = result["conversation_id"]
            st.session_state.conversation_id = result["conversation_key"]
            st.session_state.should_scroll_bottom = True
            st.query_params["chat_type"] = "single"
            if "group_id" in st.query_params:
                del st.query_params["group_id"]
            st.rerun()


def logout_user() -> None:
    st.session_state.user = None
    st.session_state.is_authenticated = False
    st.session_state.conversation_id = None
    st.session_state.selected_conversation_id = None
    st.session_state.active_chat_type = "single"
    st.session_state.selected_group_id = None
    st.session_state.group_messages = []
    st.session_state.group_last_message_id = 0
    st.session_state.group_messages_group_id = None
    st.session_state.invite_panel_group_id = None
    st.session_state.show_user_info_editor = False
    st.session_state.show_user_menu = False
    st.session_state.show_search = False
    st.session_state.search_results = None
    st.session_state.last_search_query = ""
    st.session_state.cached_conversations = []
    st.session_state.cached_groups = []
    st.session_state.cached_invitations = []
    st.query_params.clear()
    st.rerun()


def render_user_menu(user: dict[str, Any]) -> None:
    with st.popover(user["username"], key="user_menu_popover", use_container_width=True):
        render_user_menu_panel(user)


def render_user_menu_panel(user: dict[str, Any]) -> None:
    st.caption(f"User #{user['id']}")
    if st.button("Edit user info", key="toggle_user_info_editor", use_container_width=True):
        st.session_state.show_user_info_editor = not st.session_state.show_user_info_editor
        st.rerun()

    if st.session_state.show_user_info_editor:
        with st.form("edit_user_info_form", clear_on_submit=False):
            new_username = st.text_input("Username", value=user.get("username", ""))
            new_email = st.text_input("Email", value=user.get("email") or "")
            save_profile = st.form_submit_button("Save changes", use_container_width=True)
        if save_profile:
            if len(new_username.strip()) < 3:
                st.warning("Username must be at least 3 characters.")
            elif new_email.strip() and not looks_like_email(new_email):
                st.warning("Please enter a valid email.")
            else:
                updated_user = update_user_profile(user["id"], new_username, new_email)
                if updated_user:
                    st.session_state.user = updated_user
                    st.query_params["username"] = updated_user["username"]
                    st.success("User info updated.")
                    st.rerun()

    if st.button("Logout", key="logout_from_user_menu", use_container_width=True):
        logout_user()


def render_single_chat_main(user: dict[str, Any], active_conversation: dict[str, Any]) -> None:
    conversation_id = active_conversation["conversation_id"]
    new_chat_col, _spacer_col = st.columns([1.3, 6.7])
    with new_chat_col:
        if st.button("New Chat", use_container_width=True):
            conversation = create_conversation(user["id"])
            if conversation:
                select_conversation(conversation)
                st.session_state.search_results = None
                st.session_state.should_scroll_bottom = True
                st.rerun()

    render_polled_message_area(user["id"], conversation_id)

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


def render_group_chat_main(user: dict[str, Any], active_group: dict[str, Any]) -> None:
    group_name = escape(active_group["name"])
    member_count = active_group["member_count"]
    title_col, invite_toggle_col = st.columns([7, 0.7])
    with title_col:
        st.markdown(
            f"""
            <div class="group-controls">
                <strong>{group_name}</strong><br>
                {member_count} member{'s' if member_count != 1 else ''} · chatbot included
            </div>
            """,
            unsafe_allow_html=True,
        )
    invite_open = st.session_state.invite_panel_group_id == active_group["id"]
    with invite_toggle_col:
        st.write("")
        if st.button(
            " ",
            key=f"toggle_invite_group_{active_group['id']}",
            icon=":material/add:",
            help="Invite user",
        ):
            st.session_state.invite_panel_group_id = None if invite_open else active_group["id"]
            st.rerun()

    if invite_open:
        with st.form(f"invite_group_{active_group['id']}", clear_on_submit=True):
            invite_input_col, invite_button_col = st.columns([4, 1])
            with invite_input_col:
                invited_email = st.text_input(
                    "Invite user",
                    placeholder="Invite by email...",
                    label_visibility="collapsed",
                )
            with invite_button_col:
                invite_submitted = st.form_submit_button(
                    "Invite",
                    icon=":material/person_add:",
                    use_container_width=True,
                )
        if invite_submitted:
            if not invited_email.strip():
                st.warning("Enter an email address to invite.")
            elif not looks_like_email(invited_email):
                st.warning("Please enter a valid email address.")
            else:
                invitation = invite_user_to_group(active_group["id"], user["id"], invited_email)
                if invitation:
                    invite_target = invitation.get("invited_email") or invitation["invited_username"]
                    st.session_state.invite_panel_group_id = None
                    st.success(f"Invitation sent to {invite_target}.")
                    st.rerun()

    render_polled_group_message_area(user["id"], active_group["id"])

    with st.form(f"send_group_message_form_{active_group['id']}", clear_on_submit=True):
        input_col, send_col = st.columns([6, 1])
        with input_col:
            content = st.text_input(
                "Group message",
                placeholder="Message Chat Bro...",
                label_visibility="collapsed",
            )
        with send_col:
            submitted = st.form_submit_button("Send", use_container_width=True)

    render_group_typing_capture(user["id"], active_group["id"])

    if submitted:
        if not content.strip():
            st.warning("Message cannot be empty.")
        else:
            result = send_group_message(user["id"], active_group["id"], content)
            if result:
                append_group_messages(result.get("messages", []))
                st.session_state.should_scroll_bottom = True
                st.rerun()


def render_chat_screen() -> None:
    user = st.session_state.user
    brand_col, message_col, user_menu_col = st.columns([1.4, 4.4, 1.3], gap="small")
    with brand_col:
        st.markdown(
            '<div class="topbar-brand-block"><div class="brand">Chat<span> Bro</span></div></div>',
            unsafe_allow_html=True,
        )
    with message_col:
        st.markdown(
            '<div class="topbar-message topbar-message-block" dir="rtl">Chat Bro מחובר. שאל שאלה, בדוק את הזרימה, והתחל שיחה.</div>',
            unsafe_allow_html=True,
        )
    with user_menu_col:
        render_user_menu(user)

    sidebar_col, chat_col = st.columns([1.25, 3.75], gap="large")
    active_conversation = None
    active_group = None
    with sidebar_col:
        sidebar_placeholder = st.container()

    with chat_col:
        chat_placeholder = st.container()

    conversations, groups = fetch_chat_shell_data(user["id"])
    if conversations is None:
        conversations = st.session_state.cached_conversations
    else:
        st.session_state.cached_conversations = conversations

    if groups is None:
        groups = st.session_state.cached_groups
    else:
        st.session_state.cached_groups = groups

    with sidebar_placeholder:
        render_search_panel(user["id"])
        render_polled_invitations(user["id"], st.session_state.cached_invitations)
        with st.expander("MyChat", expanded=True):
            active_conversation = render_conversation_list(conversations)
        with st.expander("MyGroups", expanded=st.session_state.active_chat_type == "group"):
            render_group_creation(user["id"])
            active_group = render_group_list(groups)

    if st.session_state.active_chat_type == "group" and not active_group:
        st.session_state.active_chat_type = "single"

    if st.session_state.active_chat_type == "single" and not active_conversation:
        with chat_placeholder:
            st.markdown(
                '<div class="empty-state">Your chat is loading...</div>',
                unsafe_allow_html=True,
            )
        return

    with chat_placeholder:
        if st.session_state.active_chat_type == "group" and active_group:
            render_group_chat_main(user, active_group)
        elif active_conversation:
            render_single_chat_main(user, active_conversation)


def main() -> None:
    init_session_state()
    inject_css()
    install_message_autoscroll()

    if st.session_state.is_authenticated and st.session_state.user:
        render_chat_screen()
    else:
        render_auth_screen()


if __name__ == "__main__":
    main()
