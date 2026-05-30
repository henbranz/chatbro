import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND_PORT = os.getenv("CHAT_BRO_BACKEND_PORT", "8000")
FRONTEND_PORT = os.getenv("CHAT_BRO_FRONTEND_PORT", "8501")


def start_process(command: list[str], env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(command, cwd=ROOT, env=env)


def main() -> int:
    env = os.environ.copy()
    env.setdefault("CHAT_BRO_API_BASE_URL", f"http://127.0.0.1:{BACKEND_PORT}")

    backend = start_process(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            BACKEND_PORT,
        ],
        env,
    )
    frontend = start_process(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "frontend/app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            FRONTEND_PORT,
            "--server.headless",
            "true",
        ],
        env,
    )

    print(f"Chat Bro is starting at http://127.0.0.1:{FRONTEND_PORT}")
    try:
        while backend.poll() is None and frontend.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in (frontend, backend):
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        for process in (frontend, backend):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    return backend.returncode or frontend.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
