# News Alert

네이버 뉴스 검색 API와 금융위원회 RSS에서 키워드가 포함된 새 글을 찾아 알려주는 작은 알림 도구입니다.

## 설정

1. `.env.example`을 참고해 `.env`를 만듭니다.
2. 웹 대시보드에서 키워드와 RSS 출처를 설정합니다.
3. 저장된 개인 설정은 `config.local.json`에 보관되며 깃에 올라가지 않습니다.

`config.json`은 처음 실행할 때 참고하는 기본 샘플입니다. 노트북별 실제 설정은 `config.local.json`에 저장되므로 `git pull`을 해도 개인 키워드 목록이 덮어써지지 않습니다.

## 실행

웹 대시보드로 실행하려면:

```powershell
python web_app.py
```

브라우저에서 `http://127.0.0.1:8765`를 엽니다.

## 연합인포맥스 작성 기사 목록 수집

정원 기자 / `jwon@yna.co.kr` 검색 결과의 제목, URL, 기자명, 날짜 메타데이터를 수집하려면:

```powershell
python collect_einfomax_writer.py --max-articles 100 --max-pages 5
```

본문 수집은 공개 기사 저작권과 AI 활용 권리관계를 확인한 뒤, 권한이 있는 경우에만 사용하세요.

```powershell
python collect_einfomax_writer.py --include-body --confirm-ai-use-rights --max-articles 500 --max-pages 25 --output-dir data\einfomax_writer_latest500
```

현재 결과를 알림 없이 저장해서 최초 실행 스팸을 막으려면:

```powershell
python news_alert.py --mark-seen
```

새 기사만 한 번 확인하려면:

```powershell
python news_alert.py --once
```

10분마다 계속 확인하려면:

```powershell
python news_alert.py --loop --interval 600
```

## Telegram subscribers

`.env`에 `TELEGRAM_BOT_TOKEN`을 넣고 프로그램을 실행해두면, 사용자가 봇에서 `/start`를 보냈을 때 해당 `chat_id`가 `news_alerts.sqlite3`의 `telegram_subscribers` 테이블에 저장됩니다.

뉴스 알림은 다음 대상에게 발송됩니다.

- DB에 저장된 활성 구독자
- `.env`의 `TELEGRAM_CHAT_ID`
- `.env`의 `TELEGRAM_CHAT_IDS`에 쉼표로 입력한 chat_id 목록

구독 해제는 사용자가 봇에 `/stop`을 보내면 됩니다.

## 알림

기본은 콘솔 출력입니다. `.env`에 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`를 넣으면 텔레그램으로도 발송합니다.
