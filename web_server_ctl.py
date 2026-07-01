import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

from news_alert import BASE_DIR, env_int, load_dotenv


load_dotenv(BASE_DIR / ".env")
HOST = os.environ.get("NEWS_ALERT_HOST", "127.0.0.1")
PORT = env_int("NEWS_ALERT_PORT", 8765)
URL = f"http://{HOST}:{PORT}"


def server_responding(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/health", timeout=timeout) as response:
            response.read()
        return True
    except Exception:
        return False


def port_open() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def listening_pids() -> list[int]:
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="ignore",
            check=False,
        )
    except OSError:
        return []

    pids = set()
    marker = f":{PORT}"
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local_address = parts[1]
        state = parts[3].upper()
        if state == "LISTENING" and local_address.endswith(marker):
            try:
                pid = int(parts[4])
            except ValueError:
                continue
            if pid:
                pids.add(pid)
    return sorted(pids)


def start_server() -> int:
    pids = listening_pids()
    if pids or port_open():
        print("News alert web server is already running.")
        if pids:
            print("PID: " + ", ".join(str(pid) for pid in pids))
        webbrowser.open(URL)
        return 0

    out_path = BASE_DIR / "web_service.out.log"
    err_path = BASE_DIR / "web_service.err.log"
    creationflags = 0
    for name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"):
        creationflags |= getattr(subprocess, name, 0)

    with out_path.open("ab") as out_log, err_path.open("ab") as err_log:
        process = subprocess.Popen(
            [sys.executable, str(BASE_DIR / "web_app.py")],
            cwd=BASE_DIR,
            stdin=subprocess.DEVNULL,
            stdout=out_log,
            stderr=err_log,
            creationflags=creationflags,
            close_fds=True,
        )

    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if server_responding(timeout=0.8):
            print(f"Started news alert web server. PID: {process.pid}")
            webbrowser.open(URL)
            return 0
        if process.poll() is not None:
            print("Server process exited during startup.")
            print("Check web_service.err.log.")
            return 1
        time.sleep(0.5)

    print(f"Server start was requested. PID: {process.pid}")
    print("It did not answer yet. Check web_service.err.log if the page does not open.")
    return 1


def stop_server() -> int:
    pids = listening_pids()
    if not pids:
        print("News alert web server is not running.")
        return 0

    exit_code = 0
    for pid in pids:
        print(f"Stopping PID {pid}", flush=True)
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="ignore",
            check=False,
        )
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip()
            if output:
                print(output)
            exit_code = result.returncode

    time.sleep(1)
    remaining = listening_pids()
    if remaining:
        print("Server may still be running. PID: " + ", ".join(str(pid) for pid in remaining))
        return exit_code or 1

    print("Stopped news alert web server.")
    return exit_code


def status_server() -> int:
    pids = listening_pids()
    if pids:
        print("News alert web server is running.")
        print("PID: " + ", ".join(str(pid) for pid in pids))
        print(f"URL: {URL}")
        return 0
    print("News alert web server is not running.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local news alert web server.")
    parser.add_argument("command", choices=["start", "stop", "status"])
    args = parser.parse_args()

    if args.command == "start":
        return start_server()
    if args.command == "stop":
        return stop_server()
    return status_server()


if __name__ == "__main__":
    raise SystemExit(main())
