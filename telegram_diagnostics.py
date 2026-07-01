import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from news_alert import BASE_DIR, DEFAULT_CONFIG_PATH, TEMPLATE_CONFIG_PATH, load_config, load_dotenv


API_HOST = "api.telegram.org"


def mask(value: str) -> str:
    if not value:
        return "-"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def telegram_request(token: str, method: str, payload: dict | None = None) -> dict:
    url = f"https://{API_HOST}/bot{token}/{method}"
    data = None
    if payload is not None:
        data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(body)
            description = details.get("description") or body
        except json.JSONDecodeError:
            description = body
        raise RuntimeError(f"HTTP {exc.code}: {description}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def print_config_status() -> None:
    print(f"config path: {DEFAULT_CONFIG_PATH}")
    print(f"config.local exists: {DEFAULT_CONFIG_PATH.exists()}")
    print(f"config template exists: {TEMPLATE_CONFIG_PATH.exists()}")
    try:
        config = load_config(DEFAULT_CONFIG_PATH)
    except Exception as exc:
        print(f"config: failed to read ({exc})")
        return

    notifications = config.get("notifications") or {}
    scheduler = config.get("scheduler") or {}
    print(f"config.telegram_enabled: {bool(notifications.get('telegram_enabled'))}")
    print(f"config.instant_alerts: {bool(scheduler.get('instant_alerts'))}")


def tcp_connects() -> bool:
    try:
        with socket.create_connection((API_HOST, 443), timeout=5):
            return True
    except OSError as exc:
        print(f"FAIL: cannot connect to {API_HOST}:443: {exc}")
        return False


def main() -> int:
    env_path = BASE_DIR / ".env"
    load_dotenv(env_path)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    print(f".env path: {env_path}")
    print(f".env exists: {env_path.exists()}")
    print(f"TELEGRAM_BOT_TOKEN: present={bool(token)} length={len(token)} value={mask(token)}")
    print(f"TELEGRAM_CHAT_ID: present={bool(chat_id)} length={len(chat_id)} value={mask(chat_id)}")
    print_config_status()
    print()

    if not token or not chat_id:
        print("FAIL: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set in .env.")
        return 1

    try:
        ip = socket.gethostbyname(API_HOST)
        print(f"DNS {API_HOST}: {ip}")
    except OSError as exc:
        print(f"FAIL: cannot resolve {API_HOST}: {exc}")
        return 1

    if not tcp_connects():
        print("Hint: that laptop, network, VPN, firewall, or security software may block Telegram API.")
        return 1
    print(f"TCP {API_HOST}:443: OK")

    try:
        bot = telegram_request(token, "getMe")
        username = ((bot.get("result") or {}).get("username")) or "-"
        print(f"Telegram getMe: OK (@{username})")
    except Exception as exc:
        print(f"FAIL: Telegram getMe failed: {exc}")
        print("Hint: HTTP 401 means TELEGRAM_BOT_TOKEN is wrong.")
        print("Hint: SSL handshake timeout or network timeout means that laptop, network, VPN, firewall, or security software may block api.telegram.org.")
        return 1

    try:
        telegram_request(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": "뉴스 알림 텔레그램 진단 메시지",
                "disable_web_page_preview": "true",
            },
        )
        print("Telegram sendMessage: OK")
        return 0
    except Exception as exc:
        print(f"FAIL: Telegram sendMessage failed: {exc}")
        print("Hint: 'chat not found' means TELEGRAM_CHAT_ID is wrong or the user has not sent /start to the bot.")
        print("Hint: network timeout means that laptop, network, VPN, firewall, or security software may block api.telegram.org.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
