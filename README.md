# Chat Bro

Chat Bro is a Python chat MVP with a separated client-server architecture:

```text
User -> Streamlit frontend -> FastAPI backend -> SQLite database
```

The Streamlit frontend never reads or writes the database directly. It talks to the FastAPI backend only through HTTP requests with JSON payloads. The backend is the only layer that uses SQLite.

## Project Structure

```text
simplechat/
├── requirements.txt
├── render.yaml
├── README.md
├── backend/
│   ├── __init__.py
│   ├── database.py
│   └── main.py
└── frontend/
    └── app.py
```

## Local Setup

Create a virtual environment:

```powershell
py -m venv .venv
```

Install dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create a local `.env` file from `.env.example` and set your Gemini key:

```text
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.5-flash
DATABASE_PATH=messages.db
API_BASE_URL=http://127.0.0.1:8000
```

Do not commit `.env` to GitHub.

## Run Locally

Start the backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

Start the frontend in a second terminal:

```powershell
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py
```

Open:

```text
http://localhost:8501
```

## Database

By default, SQLite is stored in:

```text
messages.db
```

For production hosting, set:

```text
DATABASE_PATH=/var/data/messages.db
```

On Render, the included `render.yaml` mounts a persistent disk at `/var/data`, so the SQLite file survives restarts and deploys.

## Gemini

Chat Bro uses Gemini through the backend only. The frontend never receives the API key.

Required environment variables:

```text
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.5-flash
```

## Deploy With Render

This repo includes `render.yaml` with two services:

```text
chatbro-backend   FastAPI API
chatbro-frontend  Streamlit UI
```

In Render:

1. Connect the GitHub repository.
2. Choose Blueprint deployment.
3. Select this repository.
4. Add the secret environment variable `GEMINI_API_KEY` to `chatbro-backend`.
5. Deploy both services.
6. Copy the backend public URL.
7. In `chatbro-frontend`, set `API_BASE_URL` to the backend URL.

Example:

```text
API_BASE_URL=https://chatbro-backend.onrender.com
```

If Render gives your backend a different URL, use that exact URL instead.

## Vercel Domain

Vercel is not used to run Streamlit. Use Vercel only as the domain/DNS/front-door layer.

Recommended setup:

1. Deploy Chat Bro on Render.
2. Copy the live Streamlit frontend URL from Render.
3. Point your custom domain to the Render frontend service, or configure Vercel to redirect your domain to the Render frontend URL.

The actual running app remains:

```text
Vercel/custom domain -> Render Streamlit frontend -> Render FastAPI backend -> SQLite persistent disk
```

## Manual Test

1. Register a new user.
2. Send a message.
3. Confirm the typing indicator appears.
4. Confirm the bot response appears without pressing refresh.
5. Log out.
6. Register or log in as a second user.
7. Confirm the second user does not see the first user's messages.
8. Ask a Hebrew question and confirm the answer stays in Hebrew and right-to-left.

## Current MVP Scope

Chat Bro currently supports private per-user chat history. Full private chats between users, group chats, admin panels, and a production Postgres migration can be added in a later phase.
