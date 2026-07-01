import argparse
import datetime as dt
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


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", "", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


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
    conn.commit()
    return conn


def save_new_articles(conn: sqlite3.Connection, articles: list[Article], mark_seen: bool) -> list[Article]:
    new_articles: list[Article] = []
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

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


def notify_console(articles: list[Article]) -> None:
    if not articles:
        print("새 기사 없음")
        return

    for index, article in enumerate(articles, start=1):
        print(f"\n=== 새 기사 {index}/{len(articles)} ===")
        print(format_article(article))


def notify_telegram(articles: list[Article]) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id or not articles:
        return

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    for article in articles:
        data = urllib.parse.urlencode(
            {
                "chat_id": chat_id,
                "text": format_article(article),
                "disable_web_page_preview": "false",
            }
        ).encode("utf-8")
        request = urllib.request.Request(endpoint, data=data, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read()
        except Exception as exc:
            print(f"[WARN] Telegram notification failed: {exc}", file=sys.stderr)


def collect_articles(config: dict) -> list[Article]:
    articles = []
    articles.extend(fetch_naver_news(config))
    articles.extend(fetch_rss_feeds(config))

    exclude_keywords = config.get("exclude_keywords", [])
    if not exclude_keywords:
        return articles

    filtered = []
    for article in articles:
        text = f"{article.title} {article.snippet}".casefold()
        if any(keyword.casefold() in text for keyword in exclude_keywords):
            continue
        filtered.append(article)
    return filtered


def run_once(config: dict, mark_seen: bool = False) -> int:
    db_path = BASE_DIR / config.get("database", "news_alerts.sqlite3")
    articles = collect_articles(config)

    with init_db(db_path) as conn:
        new_articles = save_new_articles(conn, articles, mark_seen=mark_seen)

    if mark_seen:
        print(f"기존 기사 {len(articles)}개를 알림 없이 저장했습니다.")
        return 0

    notify_console(new_articles)
    notify_telegram(new_articles)
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
