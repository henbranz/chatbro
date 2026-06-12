import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_BACKEND_PORT = int(os.getenv("CHAT_BRO_BACKEND_PORT", "8000"))
DEFAULT_FRONTEND_PORT = int(os.getenv("CHAT_BRO_FRONTEND_PORT", "8501"))


def port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def first_available_port(start_port: int) -> int:
    port = start_port
    while not port_is_available(port):
        port += 1
    return port


def find_python() -> str:
    configured_python = os.getenv("CHAT_BRO_PYTHON")
    if configured_python:
        return configured_python

    candidates = [
        ROOT / ".venv" / "bin" / "python",
        ROOT / ".venv-macos" / "bin" / "python",
        ROOT / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def missing_modules(python_bin: str) -> list[str]:
    required = ["fastapi", "uvicorn", "streamlit", "sqlalchemy", "requests"]
    missing = []
    for module in required:
        result = subprocess.run(
            [python_bin, "-c", f"import {module}"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            missing.append(module)
    return missing


def start_process(command: list[str], env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(command, cwd=ROOT, env=env)


def main() -> int:
    backend_port = first_available_port(DEFAULT_BACKEND_PORT)
    frontend_port = first_available_port(DEFAULT_FRONTEND_PORT)
    env = os.environ.copy()
    env["CHAT_BRO_API_BASE_URL"] = f"http://127.0.0.1:{backend_port}"
    python_bin = find_python()
    missing = missing_modules(python_bin)
    if missing:
        print("Missing Python packages:", ", ".join(missing))
        print("Install dependencies first:")
        print(f'  "{python_bin}" -m pip install -r requirements.txt')
        return 1

    print(f"Using Python: {python_bin}")
    if backend_port != DEFAULT_BACKEND_PORT:
        print(f"Backend port {DEFAULT_BACKEND_PORT} is busy, using {backend_port} instead.")
    if frontend_port != DEFAULT_FRONTEND_PORT:
        print(f"Frontend port {DEFAULT_FRONTEND_PORT} is busy, using {frontend_port} instead.")

    backend = start_process(
        [
            python_bin,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(backend_port),
        ],
        env,
    )
    frontend = start_process(
        [
            python_bin,
            "-m",
            "streamlit",
            "run",
            "frontend/app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(frontend_port),
            "--server.headless",
            "true",
        ],
        env,
    )

    print(f"Chat Bro is starting at http://127.0.0.1:{frontend_port}")
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
