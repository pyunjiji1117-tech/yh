import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_CONFIG_PATH = BASE_DIR / "config.local.json"
KST = dt.timezone(dt.timedelta(hours=9))


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


@dataclass(frozen=True)
class Article:
    source: str
    title: str
    url: str
    published_at: str
    snippet: str
    matched_keywords: tuple[str, ...]

    @property
    def key(self) -> str:
        return self.url.strip()


def normalize_domain(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().casefold()
    if not text:
        return ""
    if "://" not in text and not text.startswith("//"):
        text = f"//{text}"
    parsed = urllib.parse.urlparse(text)
    host = parsed.hostname or ""
    host = host.strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def article_domain(article_or_url: Article | str | None) -> str:
    if isinstance(article_or_url, Article):
        return normalize_domain(article_or_url.url)
    return normalize_domain(article_or_url)


def domain_matches(domain: str, allowed_domains: list[str]) -> bool:
    normalized = normalize_domain(domain)
    if not normalized:
        return False
    for allowed_domain in allowed_domains:
        allowed = normalize_domain(allowed_domain)
        if allowed and (normalized == allowed or normalized.endswith(f".{allowed}")):
            return True
    return False


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(path: Path) -> dict:
    config_path = Path(path)
    if not config_path.exists() and config_path == DEFAULT_CONFIG_PATH and TEMPLATE_CONFIG_PATH.exists():
        config_path = TEMPLATE_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        print(f"[WARN] {name} must be a number. Using {default}.", file=sys.stderr)
        return default


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", "", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_article_datetime(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = None

    if parsed is None:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed


def compact_article_time(article: "Article") -> str:
    parsed = parse_article_datetime(article.published_at)
    if parsed:
        return parsed.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    return article.published_at or "-"


def notification_order(articles: list["Article"]) -> list["Article"]:
    def sort_key(article: Article):
        parsed = parse_article_datetime(article.published_at)
        if parsed:
            return (0, parsed.timestamp(), article.title)
        return (1, article.published_at, article.title)

    return sorted(articles, key=sort_key)


def find_keywords(text: str, keywords: list[str]) -> tuple[str, ...]:
    lowered = text.casefold()
    found = []
    for keyword in keywords:
        if keyword.casefold() in lowered:
            found.append(keyword)
    return tuple(found)


def request_json(url: str, headers: dict[str, str] | None = None, timeout: int = 15) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def request_text(url: str, timeout: int = 15) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "YHNewsAlert/1.0 (+https://localhost)",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_naver_news(config: dict) -> list[Article]:
    naver = config.get("naver", {})
    if not naver.get("enabled", True):
        return []

    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("[WARN] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET is missing. Skipping Naver.", file=sys.stderr)
        return []

    endpoint = "https://openapi.naver.com/v1/search/news.json"
    display = int(naver.get("display", 20))
    sort = naver.get("sort", "date")
    keywords = config.get("keywords", [])
    articles: list[Article] = []

    for keyword in keywords:
        params = urllib.parse.urlencode(
            {
                "query": keyword,
                "display": display,
                "start": 1,
                "sort": sort,
            }
        )
        url = f"{endpoint}?{params}"
        headers = {
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        }
        try:
            data = request_json(url, headers=headers)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"[WARN] Naver API failed for {keyword}: HTTP {exc.code} {body}", file=sys.stderr)
            continue
        except Exception as exc:
            print(f"[WARN] Naver API failed for {keyword}: {exc}", file=sys.stderr)
            continue

        for item in data.get("items", []):
            title = clean_text(item.get("title"))
            snippet = clean_text(item.get("description"))
            article_url = item.get("originallink") or item.get("link") or ""
            if not article_url:
                continue
            matched = tuple(dict.fromkeys((keyword, *find_keywords(f"{title} {snippet}", keywords))))
            articles.append(
                Article(
                    source="Naver News",
                    title=title,
                    url=article_url,
                    published_at=item.get("pubDate", ""),
                    snippet=snippet,
                    matched_keywords=matched,
                )
            )

    return articles


def parse_rss_items(source_name: str, xml_text: str, keywords: list[str]) -> list[Article]:
    root = ET.fromstring(xml_text)
    articles: list[Article] = []

    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"))
        snippet = clean_text(item.findtext("description"))
        url = clean_text(item.findtext("link"))
        published_at = clean_text(item.findtext("pubDate"))
        matched = find_keywords(f"{title} {snippet}", keywords)
        if not matched or not url:
            continue
        articles.append(
            Article(
                source=source_name,
                title=title,
                url=url,
                published_at=published_at,
                snippet=snippet,
                matched_keywords=matched,
            )
        )

    return articles


def fetch_rss_feeds(config: dict) -> list[Article]:
    articles: list[Article] = []
    keywords = config.get("keywords", [])

    for feed in config.get("rss_feeds", []):
        name = feed["name"]
        url = feed["url"]
        try:
            xml_text = request_text(url)
            articles.extend(parse_rss_items(name, xml_text, keywords))
        except Exception as exc:
            print(f"[WARN] RSS failed for {name}: {exc}", file=sys.stderr)

    return articles


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            article_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            published_at TEXT,
            snippet TEXT,
            matched_keywords TEXT,
            first_seen_at TEXT NOT NULL,
            notified_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_subscribers (
            chat_id TEXT PRIMARY KEY,
            chat_type TEXT,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            subscribed_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def telegram_api_request(token: str, method: str, params: dict[str, str] | None = None, timeout: int = 15) -> dict:
    endpoint = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    request = urllib.request.Request(endpoint, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def telegram_message(token: str, chat_id: str, text: str) -> None:
    telegram_api_request(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        },
    )


def get_telegram_state(conn: sqlite3.Connection, key: str) -> str | None:
    cursor = conn.execute("SELECT value FROM telegram_state WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row[0] if row else None


def set_telegram_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO telegram_state (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def parse_telegram_chat_ids(raw_values: list[str]) -> list[str]:
    chat_ids: list[str] = []
    for raw_value in raw_values:
        for chat_id in re.split(r"[\s,;]+", raw_value.strip()):
            if chat_id and chat_id not in chat_ids:
                chat_ids.append(chat_id)
    return chat_ids


def parse_telegram_chat_ids_from_env() -> list[str]:
    return parse_telegram_chat_ids(
        [
            os.environ.get("TELEGRAM_CHAT_IDS", ""),
            os.environ.get("TELEGRAM_CHAT_ID", ""),
        ]
    )


def get_telegram_chat_ids(conn: sqlite3.Connection, manual_chat_ids: list[str] | None = None) -> list[str]:
    chat_ids = list(manual_chat_ids) if manual_chat_ids is not None else parse_telegram_chat_ids_from_env()
    cursor = conn.execute(
        """
        SELECT chat_id
        FROM telegram_subscribers
        WHERE is_active = 1
        ORDER BY subscribed_at, chat_id
        """
    )
    for (chat_id,) in cursor.fetchall():
        if chat_id not in chat_ids:
            chat_ids.append(chat_id)
    return chat_ids


def extract_telegram_command(text: str | None) -> str:
    if not text:
        return ""
    first_word = text.strip().split(maxsplit=1)[0].casefold()
    if not first_word.startswith("/"):
        return ""
    return first_word.split("@", 1)[0]


def save_telegram_subscriber(conn: sqlite3.Connection, message: dict) -> str:
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    chat_id = str(chat.get("id") or "")
    if not chat_id:
        return ""

    now = utc_now()
    cursor = conn.execute("SELECT 1 FROM telegram_subscribers WHERE chat_id = ?", (chat_id,))
    exists = cursor.fetchone() is not None
    values = (
        chat.get("type", ""),
        chat.get("username") or user.get("username") or "",
        chat.get("first_name") or user.get("first_name") or chat.get("title") or "",
        chat.get("last_name") or user.get("last_name") or "",
        now,
        chat_id,
    )
    if exists:
        conn.execute(
            """
            UPDATE telegram_subscribers
            SET chat_type = ?, username = ?, first_name = ?, last_name = ?,
                last_seen_at = ?, is_active = 1
            WHERE chat_id = ?
            """,
            values,
        )
    else:
        conn.execute(
            """
            INSERT INTO telegram_subscribers (
                chat_id, chat_type, username, first_name, last_name,
                subscribed_at, last_seen_at, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (chat_id, values[0], values[1], values[2], values[3], now, now),
        )
    return chat_id


def stop_telegram_subscriber(conn: sqlite3.Connection, message: dict) -> str:
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    if not chat_id:
        return ""
    conn.execute(
        """
        UPDATE telegram_subscribers
        SET is_active = 0, last_seen_at = ?
        WHERE chat_id = ?
        """,
        (utc_now(), chat_id),
    )
    return chat_id


def sync_telegram_subscribers(conn: sqlite3.Connection, token: str | None = None) -> None:
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return

    params: dict[str, str] = {
        "timeout": "0",
        "allowed_updates": json.dumps(["message"]),
    }
    last_update_id = get_telegram_state(conn, "telegram_last_update_id")
    if last_update_id:
        params["offset"] = str(int(last_update_id) + 1)

    try:
        response = telegram_api_request(token, "getUpdates", params=params)
    except Exception as exc:
        print(f"[WARN] Telegram subscriber sync failed: {exc}", file=sys.stderr)
        return

    updates = response.get("result", [])
    max_update_id = int(last_update_id) if last_update_id else None
    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)

        message = update.get("message") or {}
        command = extract_telegram_command(message.get("text"))
        if command == "/start":
            chat_id = save_telegram_subscriber(conn, message)
            if chat_id:
                try:
                    telegram_message(token, chat_id, "News alerts are now enabled. Send /stop to unsubscribe.")
                except Exception as exc:
                    print(f"[WARN] Telegram welcome message failed: {exc}", file=sys.stderr)
        elif command == "/stop":
            chat_id = stop_telegram_subscriber(conn, message)
            if chat_id:
                try:
                    telegram_message(token, chat_id, "News alerts are now disabled. Send /start to subscribe again.")
                except Exception as exc:
                    print(f"[WARN] Telegram stop message failed: {exc}", file=sys.stderr)

    if max_update_id is not None:
        set_telegram_state(conn, "telegram_last_update_id", str(max_update_id))
    conn.commit()


def save_new_articles(conn: sqlite3.Connection, articles: list[Article], mark_seen: bool) -> list[Article]:
    new_articles: list[Article] = []
    now = utc_now()

    for article in articles:
        if not article.key:
            continue
        cursor = conn.execute("SELECT 1 FROM articles WHERE article_key = ?", (article.key,))
        if cursor.fetchone():
            continue

        notified_at = now if mark_seen else None
        conn.execute(
            """
            INSERT INTO articles (
                article_key, source, title, url, published_at, snippet,
                matched_keywords, first_seen_at, notified_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.key,
                article.source,
                article.title,
                article.url,
                article.published_at,
                article.snippet,
                ", ".join(article.matched_keywords),
                now,
                notified_at,
            ),
        )
        if not mark_seen:
            new_articles.append(article)

    conn.commit()
    return new_articles


def format_article(article: Article) -> str:
    keyword_text = ", ".join(article.matched_keywords)
    lines = [
        f"[{article.source}] {article.title}",
        f"키워드: {keyword_text}",
    ]
    if article.published_at:
        lines.append(f"게시일: {article.published_at}")
    if article.snippet:
        lines.append(f"요약: {article.snippet}")
    lines.append(f"링크: {article.url}")
    return "\n".join(lines)


def format_telegram_article(article: Article) -> str:
    keyword_text = ", ".join(article.matched_keywords) or "-"
    lines = [
        f"제목: {article.title}",
        f"시간: {compact_article_time(article)}",
        f"키워드: {keyword_text}",
    ]
    if article.url:
        lines.append(f"링크: {article.url}")
    return "\n".join(lines)


def notify_console(articles: list[Article]) -> None:
    if not articles:
        print("새 기사 없음")
        return

    for index, article in enumerate(articles, start=1):
        print(f"\n=== 새 기사 {index}/{len(articles)} ===")
        print(format_article(article))


def notify_telegram(articles: list[Article], chat_ids: list[str], token: str | None = None) -> None:
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or not chat_ids or not articles:
        return

    ordered_articles = notification_order(articles)
    for chat_id in chat_ids:
        for article in ordered_articles:
            try:
                telegram_message(token, chat_id, format_telegram_article(article))
            except Exception as exc:
                print(f"[WARN] Telegram notification failed for chat {chat_id}: {exc}", file=sys.stderr)


def collect_articles(config: dict, apply_media_filter: bool = True) -> list[Article]:
    articles = []
    articles.extend(fetch_naver_news(config))
    articles.extend(fetch_rss_feeds(config))

    exclude_keywords = config.get("exclude_keywords", [])
    if exclude_keywords:
        filtered = []
        for article in articles:
            text = f"{article.title} {article.snippet}".casefold()
            if any(keyword.casefold() in text for keyword in exclude_keywords):
                continue
            filtered.append(article)
        articles = filtered

    media_filter = config.get("media_filter") or {}
    allowed_domains = media_filter.get("allowed_domains") or []
    if apply_media_filter and media_filter.get("enabled") and allowed_domains:
        articles = [article for article in articles if domain_matches(article_domain(article), allowed_domains)]

    return articles


def run_once(config: dict, mark_seen: bool = False) -> int:
    db_path = BASE_DIR / config.get("database", "news_alerts.sqlite3")
    articles = collect_articles(config)

    conn = init_db(db_path)
    try:
        sync_telegram_subscribers(conn)
        new_articles = save_new_articles(conn, articles, mark_seen=mark_seen)
        telegram_chat_ids = get_telegram_chat_ids(conn)
    finally:
        conn.close()

    if mark_seen:
        print(f"기존 기사 {len(articles)}개를 알림 없이 저장했습니다.")
        return 0

    notify_console(new_articles)
    notify_telegram(new_articles, telegram_chat_ids)
    return len(new_articles)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Keyword news alert collector")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config JSON")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--loop", action="store_true", help="Run forever")
    parser.add_argument("--interval", type=int, default=600, help="Loop interval seconds")
    parser.add_argument("--mark-seen", action="store_true", help="Save current results without notifying")
    return parser.parse_args()


def main() -> int:
    configure_stdio()
    args = parse_args()
    load_dotenv(BASE_DIR / ".env")
    config = load_config(Path(args.config))

    if args.loop:
        while True:
            print(f"\n[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] checking news...")
            run_once(config, mark_seen=args.mark_seen)
            time.sleep(args.interval)

    run_once(config, mark_seen=args.mark_seen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
