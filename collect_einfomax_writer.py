import argparse
import csv
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError as exc:
    raise SystemExit(
        "beautifulsoup4 is required. Install it with: python -m pip install beautifulsoup4"
    ) from exc


BASE_URL = "https://news.einfomax.co.kr"
DEFAULT_OUTPUT_DIR = Path("data") / "einfomax_writer"
DEFAULT_USER_AGENT = "YHNewsAlert/1.0 (+local-persona-research)"


def request_html(url: str, delay: float, data: dict | None = None) -> str:
    if delay > 0:
        time.sleep(delay)
    encoded_data = None
    if data is not None:
        encoded_data = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded_data,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def search_payload(page: int, reporter_name: str, email: str, start_date: str, end_date: str) -> dict:
    return {
        "page": str(page),
        "total": "",
        "box_idxno": "",
        "sc_section_code": "",
        "sc_sub_section_code": "",
        "sc_serial_code": "",
        "sc_area": "A",
        "sc_level": "",
        "sc_article_type": "",
        "sc_view_level": "",
        "sc_user_name": reporter_name,
        "sc_sdate": start_date,
        "sc_edate": end_date,
        "sc_serial_number": "",
        "sc_order_by": "E",
        "sc_word": f" {email}",
        "sc_andor": "OR",
        "sc_word2": "",
        "sc_multi_code": "",
        "sc_is_image": "",
        "sc_is_movie": "",
    }


def absolute_url(href: str) -> str:
    return urllib.parse.urljoin(BASE_URL, href)


def text_of(element) -> str:
    if not element:
        return ""
    return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()


def parse_total_count(soup: BeautifulSoup) -> int | None:
    header_text = text_of(soup.select_one("section.section-body header.header"))
    match = re.search(r"총\s*:\s*([\d,]+)건", header_text)
    if not match:
        match = re.search(r"\(\s*([\d,]+)건\s*\)", header_text)
    return int(match.group(1).replace(",", "")) if match else None


def parse_listing(html_text: str) -> tuple[list[dict], int | None]:
    soup = BeautifulSoup(html_text, "html.parser")
    total_count = parse_total_count(soup)
    articles = []

    for link in soup.select("#section-list h4.titles a"):
        item = link.find_parent("li")
        href = link.get("href") or ""
        idx_match = re.search(r"idxno=(\d+)", href)
        articles.append(
            {
                "idxno": idx_match.group(1) if idx_match else "",
                "title": text_of(link),
                "url": absolute_url(href),
                "category": text_of(item.select_one(".info.category")) if item else "",
                "reporter": text_of(item.select_one(".info.name")) if item else "",
                "listed_at": text_of(item.select_one(".info.dated")) if item else "",
            }
        )

    return articles, total_count


def parse_article(html_text: str, fallback: dict) -> dict:
    soup = BeautifulSoup(html_text, "html.parser")
    title = text_of(soup.select_one("h3.heading")) or fallback.get("title", "")
    meta_text = text_of(soup.select_one(".article-view-header .infomation"))
    reporter = fallback.get("reporter", "")
    input_at = ""
    updated_at = ""

    reporter_match = re.search(r"기자명\s+(.+? 기자)", meta_text)
    if reporter_match:
        reporter = reporter_match.group(1).strip()

    input_match = re.search(r"입력\s+(\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2})", meta_text)
    if input_match:
        input_at = input_match.group(1)

    updated_match = re.search(r"수정\s+(\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2})", meta_text)
    if updated_match:
        updated_at = updated_match.group(1)

    body_node = soup.select_one("#article-view-content-div") or soup.select_one(".article-body")
    body = clean_article_body(body_node)

    return {
        **fallback,
        "title": title,
        "reporter": reporter,
        "input_at": input_at,
        "updated_at": updated_at,
        "body": body,
        "body_chars": len(body),
    }


def clean_article_body(body_node) -> str:
    if not body_node:
        return ""

    node = BeautifulSoup(str(body_node), "html.parser")
    for removable in node.select(
        "script, style, iframe, ins, .ad-template, .google-auto-placed, "
        ".article-sns, .article-copywriter, .tag-group, .related-article, "
        ".article-relation, .view-copyright, .article-ad"
    ):
        removable.decompose()

    raw_lines = []
    for line in node.get_text("\n", strip=True).splitlines():
        cleaned = html.unescape(re.sub(r"\s+", " ", line)).strip()
        if not cleaned:
            continue
        if is_noise_line(cleaned):
            continue
        raw_lines.append(cleaned)

    return "\n".join(raw_lines)


def is_noise_line(line: str) -> bool:
    noise_patterns = (
        r"^저작권자",
        r"무단전재",
        r"무단 전재",
        r"^관련기사$",
        r"^SNS 기사보내기",
        r"^기사스크랩하기",
        r"^이 기사를 공유합니다",
        r"^URL복사",
    )
    return any(re.search(pattern, line) for pattern in noise_patterns)


def load_existing(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("idxno"):
                seen.add(str(row["idxno"]))
            elif row.get("url"):
                seen.add(row["url"])
    return seen


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    fieldnames = [
        "idxno",
        "title",
        "url",
        "category",
        "reporter",
        "listed_at",
        "input_at",
        "updated_at",
        "body_chars",
        "body",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def collect(args: argparse.Namespace) -> int:
    if args.include_body and not args.confirm_ai_use_rights:
        raise SystemExit(
            "본문 수집은 --confirm-ai-use-rights가 필요합니다. "
            "공개 기사에는 저작권 및 AI 활용 제한이 적용될 수 있으므로, 권한이 있는 경우에만 실행하세요."
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / args.jsonl_name
    csv_path = output_dir / args.csv_name
    seen = load_existing(jsonl_path) if args.resume else set()
    collected = 0
    total_count = None

    print("연합인포맥스 검색 결과 수집 시작")
    print(f"기자: {args.reporter_name}, 검색어: {args.email}, 기간: {args.start_date}~{args.end_date}")
    print(f"출력: {jsonl_path}")

    for page in range(1, args.max_pages + 1):
        list_url = f"{BASE_URL}/news/articleList.html"
        payload = search_payload(page, args.reporter_name, args.email, args.start_date, args.end_date)
        try:
            listing_html = request_html(list_url, args.delay, data=payload)
        except Exception as exc:
            print(f"[WARN] 목록 페이지 실패 page={page}: {exc}", file=sys.stderr)
            break

        articles, page_total = parse_listing(listing_html)
        total_count = total_count or page_total
        if not articles:
            print(f"page {page}: 기사 없음, 종료")
            break

        print(f"page {page}: {len(articles)}개 발견")
        for article in articles:
            article_key = article.get("idxno") or article["url"]
            if article_key in seen:
                continue
            if not args.include_body:
                row = {**article, "input_at": "", "updated_at": "", "body": "", "body_chars": 0}
            else:
                try:
                    detail_html = request_html(article["url"], args.delay)
                    row = parse_article(detail_html, article)
                except Exception as exc:
                    print(f"[WARN] 본문 실패 idxno={article.get('idxno')}: {exc}", file=sys.stderr)
                    row = {**article, "input_at": "", "updated_at": "", "body": "", "body_chars": 0}

            append_jsonl(jsonl_path, row)
            seen.add(article_key)
            collected += 1

            if collected >= args.max_articles:
                rows = read_jsonl(jsonl_path)
                write_csv(csv_path, rows)
                print_summary(collected, total_count, jsonl_path, csv_path)
                return 0

    rows = read_jsonl(jsonl_path)
    write_csv(csv_path, rows)
    print_summary(collected, total_count, jsonl_path, csv_path)
    return 0


def print_summary(collected: int, total_count: int | None, jsonl_path: Path, csv_path: Path) -> None:
    print("수집 완료")
    print(f"이번 실행 신규 저장: {collected}개")
    if total_count is not None:
        print(f"검색 결과 총량: {total_count}개")
    print(f"JSONL: {jsonl_path}")
    print(f"CSV: {csv_path}")


def default_end_date() -> str:
    return dt.date.today().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Yonhap Infomax articles by reporter/email search.")
    parser.add_argument("--reporter-name", default="정원")
    parser.add_argument("--email", default="jwon@yna.co.kr")
    parser.add_argument("--start-date", default="2011-01-05")
    parser.add_argument("--end-date", default=default_end_date())
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-articles", type=int, default=100)
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait before each request.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--jsonl-name", default="einfomax_jwon_articles.jsonl")
    parser.add_argument("--csv-name", default="einfomax_jwon_articles.csv")
    parser.add_argument("--include-body", action="store_true", help="Also collect article body text.")
    parser.add_argument(
        "--confirm-ai-use-rights",
        action="store_true",
        help="Required with --include-body. Use only when you have rights/permission for AI use.",
    )
    parser.add_argument("--resume", action="store_true", default=True, help="Skip articles already in JSONL.")
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(collect(parse_args()))
