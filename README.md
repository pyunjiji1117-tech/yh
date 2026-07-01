# News Alert

네이버 뉴스 검색 API와 금융위원회 RSS에서 키워드가 포함된 새 글을 찾아 알려주는 작은 알림 도구입니다.

## 설정

1. `.env.example`을 참고해 `.env`를 만듭니다.
2. `config.json`의 `keywords`에 감시할 키워드를 넣습니다.
3. 특정 사이트 RSS가 있으면 `rss_feeds`에 추가합니다.

## 실행

웹 대시보드로 실행하려면:

```powershell
python web_app.py
```

브라우저에서 `http://127.0.0.1:8765`를 엽니다.

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

## 알림

기본은 콘솔 출력입니다. `.env`에 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`를 넣으면 텔레그램으로도 발송합니다.
