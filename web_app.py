import datetime as dt
import json
import os
import re
import sqlite3
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from news_alert import (
    Article,
    BASE_DIR,
    DEFAULT_CONFIG_PATH,
    collect_articles,
    configure_stdio,
    env_int,
    format_article,
    get_telegram_chat_ids,
    init_db,
    load_config,
    load_dotenv,
    notify_console,
    notify_telegram,
    save_new_articles,
    sync_telegram_subscribers,
    telegram_message,
)


load_dotenv(BASE_DIR / ".env")
HOST = os.environ.get("NEWS_ALERT_HOST", "127.0.0.1")
PORT = env_int("NEWS_ALERT_PORT", 8765)
KST = dt.timezone(dt.timedelta(hours=9))
CONFIG_PATH = DEFAULT_CONFIG_PATH
STATE_LOCK = threading.RLock()
STOP_EVENT = threading.Event()
EVENTS: deque[dict] = deque(maxlen=80)
RUNTIME_STATE = {
    "running": False,
    "checking": False,
    "last_check_at": None,
    "next_check_at": None,
    "last_total_count": 0,
    "last_new_count": 0,
    "last_error": None,
}


HTML = r"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>뉴스 알림 대시보드</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --surface: #ffffff;
      --surface-2: #eef3f8;
      --line: #d8e0ea;
      --text: #182231;
      --muted: #657285;
      --accent: #0f7b8f;
      --accent-2: #2563eb;
      --ok: #138a55;
      --warn: #b26b00;
      --bad: #bf3434;
      --shadow: 0 6px 18px rgba(24, 34, 49, .08);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "Malgun Gothic", Arial, sans-serif;
      font-size: 14px;
      letter-spacing: 0;
    }

    button, input, select {
      font: inherit;
    }

    button {
      min-height: 34px;
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--text);
      border-radius: 6px;
      padding: 0 12px;
      cursor: pointer;
    }

    button:hover { border-color: var(--accent); }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }
    button.danger {
      color: var(--bad);
      border-color: #edc4c4;
    }
    button.icon {
      width: 34px;
      padding: 0;
      display: inline-grid;
      place-items: center;
    }

    input, select {
      width: 100%;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      background: white;
      color: var(--text);
    }

    input[type="checkbox"] {
      width: 18px;
      min-height: 18px;
      accent-color: var(--accent);
    }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 5;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, .96);
      backdrop-filter: blur(10px);
    }

    .topbar-inner {
      max-width: 1280px;
      margin: 0 auto;
      padding: 14px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }

    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 700;
    }

    h2 {
      margin: 0 0 12px;
      font-size: 16px;
    }

    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 30px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--surface-2);
      color: var(--muted);
      white-space: nowrap;
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--muted);
    }

    .dot.ok { background: var(--ok); }
    .dot.warn { background: var(--warn); }
    .dot.bad { background: var(--bad); }

    main {
      max-width: 1280px;
      margin: 0 auto;
      padding: 18px 20px 32px;
      display: grid;
      grid-template-columns: minmax(340px, 430px) minmax(0, 1fr);
      gap: 16px;
    }

    .stack {
      display: grid;
      gap: 12px;
      align-content: start;
    }

    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 14px;
    }

    .field-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }

    .field {
      display: grid;
      gap: 5px;
      min-width: 0;
    }

    label {
      color: var(--muted);
      font-size: 12px;
    }

    .checkline {
      min-height: 32px;
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
    }

    .checkline label {
      font-size: 14px;
      color: var(--text);
    }

    .inline-form {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      margin-bottom: 10px;
    }

    .file-import {
      margin-bottom: 10px;
    }

    .chips {
      display: flex;
      gap: 7px;
      flex-wrap: wrap;
      min-height: 34px;
    }

    .chips .empty {
      width: 100%;
      min-height: 36px;
    }

    .chip {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      max-width: 100%;
      min-height: 30px;
      padding: 0 4px 0 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--surface-2);
    }

    .chip span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .chip button {
      width: 24px;
      min-height: 24px;
      border: 0;
      background: transparent;
      padding: 0;
      color: var(--muted);
    }

    .feed-row {
      display: grid;
      grid-template-columns: minmax(90px, .9fr) minmax(160px, 1.5fr) auto;
      gap: 8px;
      margin-bottom: 8px;
      align-items: center;
    }

    .meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
    }

    .article-list {
      display: grid;
      gap: 9px;
    }

    .article {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 12px;
      display: grid;
      gap: 7px;
    }

    .article a {
      color: var(--accent-2);
      font-weight: 700;
      text-decoration: none;
      line-height: 1.4;
    }

    .article a:hover { text-decoration: underline; }

    .article p {
      margin: 0;
      color: #354154;
      line-height: 1.5;
    }

    .event-log {
      display: grid;
      gap: 7px;
      max-height: 320px;
      overflow: auto;
    }

    .event {
      display: grid;
      grid-template-columns: 78px minmax(0, 1fr);
      gap: 8px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 7px;
      color: var(--muted);
    }

    .event:last-child { border-bottom: 0; }

    .empty {
      min-height: 78px;
      display: grid;
      place-items: center;
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: #fbfcfe;
    }

    .message {
      color: var(--muted);
      min-height: 20px;
    }

    .message.bad { color: var(--bad); }
    .message.ok { color: var(--ok); }

    @media (max-width: 860px) {
      .topbar-inner {
        align-items: flex-start;
        flex-direction: column;
      }

      .toolbar {
        justify-content: flex-start;
      }

      main {
        grid-template-columns: 1fr;
        padding: 14px;
      }

      .field-grid {
        grid-template-columns: 1fr;
      }

      .feed-row {
        grid-template-columns: 1fr;
      }

      button.icon {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div>
        <h1>뉴스 알림 대시보드</h1>
        <div class="meta-row" id="summary">불러오는 중</div>
      </div>
      <div class="toolbar">
        <span class="status-pill"><span class="dot" id="statusDot"></span><span id="statusText">대기</span></span>
        <button id="checkNow" class="primary">지금 검사</button>
        <button id="markSeen">현재 결과 저장</button>
        <button id="saveConfig">설정 저장</button>
      </div>
    </div>
  </header>

  <main>
    <section class="stack">
      <div class="panel">
        <h2>키워드</h2>
        <div class="inline-form">
          <input id="keywordInput" placeholder="감시할 키워드">
          <button id="addKeyword">추가</button>
        </div>
        <input type="file" id="keywordFile" accept=".txt,text/plain" hidden>
        <div class="file-import">
          <button id="importKeywords">TXT 추가</button>
        </div>
        <div class="chips" id="keywords"></div>
      </div>

      <div class="panel">
        <h2>제외 키워드</h2>
        <div class="inline-form">
          <input id="excludeInput" placeholder="제외할 단어">
          <button id="addExclude">추가</button>
        </div>
        <input type="file" id="excludeFile" accept=".txt,text/plain" hidden>
        <div class="file-import">
          <button id="importExcludes">TXT 추가</button>
        </div>
        <div class="chips" id="excludeKeywords"></div>
      </div>

      <div class="panel">
        <h2>검사와 알림</h2>
        <div class="field-grid">
          <div class="field">
            <label for="interval">검사 간격</label>
            <select id="interval">
              <option value="60">1분</option>
              <option value="300">5분</option>
              <option value="600">10분</option>
              <option value="1800">30분</option>
              <option value="3600">1시간</option>
            </select>
          </div>
          <div class="field">
            <label for="fixedTimes">고정 알림 시간</label>
            <input id="fixedTimes" placeholder="09:00, 18:00">
          </div>
        </div>
        <div class="checkline">
          <input type="checkbox" id="schedulerEnabled">
          <label for="schedulerEnabled">백그라운드 자동 검사</label>
        </div>
        <div class="checkline">
          <input type="checkbox" id="instantAlerts">
          <label for="instantAlerts">새 기사 즉시 알림</label>
        </div>
        <div class="checkline">
          <input type="checkbox" id="fixedTimeAlerts">
          <label for="fixedTimeAlerts">고정 시간 요약 알림</label>
        </div>
      </div>

      <div class="panel">
        <h2>출처</h2>
        <div class="field-grid">
          <div class="checkline">
            <input type="checkbox" id="naverEnabled">
            <label for="naverEnabled">네이버 뉴스 API</label>
          </div>
          <div class="field">
            <label for="naverDisplay">키워드당 검색 개수</label>
            <input type="number" min="1" max="100" id="naverDisplay">
          </div>
          <div class="field">
            <label for="naverSort">정렬</label>
            <select id="naverSort">
              <option value="date">최신순</option>
              <option value="sim">관련도순</option>
            </select>
          </div>
        </div>
        <div id="feeds"></div>
        <div class="feed-row">
          <input id="feedName" placeholder="RSS 이름">
          <input id="feedUrl" placeholder="RSS URL">
          <button id="addFeed">추가</button>
        </div>
      </div>

      <div class="panel">
        <h2>전송</h2>
        <div class="checkline">
          <input type="checkbox" id="telegramEnabled">
          <label for="telegramEnabled">텔레그램 알림</label>
        </div>
        <div class="meta-row">
          <span id="telegramStatus">확인 중</span>
          <span id="telegramMode">-</span>
        </div>
        <div style="margin-top: 10px;">
          <button id="testTelegram">테스트 전송</button>
        </div>
        <div class="message" id="formMessage"></div>
      </div>
    </section>

    <section class="stack">
      <div class="panel">
        <h2>최근 기사</h2>
        <div class="article-list" id="articles"></div>
      </div>

      <div class="panel">
        <h2>활동 기록</h2>
        <div class="event-log" id="events"></div>
      </div>
    </section>
  </main>

  <script>
    let config = null;

    async function request(path, options = {}) {
      const response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "요청 실패");
      }
      return data;
    }

    function escapeHtml(value) {
      return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function setMessage(text, kind = "") {
      const el = document.getElementById("formMessage");
      el.textContent = text;
      el.className = `message ${kind}`;
    }

    function ensureConfig() {
      config.scheduler = config.scheduler || {};
      config.notifications = config.notifications || {};
      config.naver = config.naver || {};
      config.rss_feeds = config.rss_feeds || [];
      config.keywords = config.keywords || [];
      config.exclude_keywords = config.exclude_keywords || [];
    }

    function renderChips(id, items, removeFn) {
      const el = document.getElementById(id);
      if (!items.length) {
        el.innerHTML = `<div class="empty">없음</div>`;
        return;
      }
      el.innerHTML = items.map((item, index) => `
        <span class="chip">
          <span>${escapeHtml(item)}</span>
          <button title="삭제" data-index="${index}">x</button>
        </span>
      `).join("");
      el.querySelectorAll("button").forEach(button => {
        button.addEventListener("click", () => removeFn(Number(button.dataset.index)));
      });
    }

    function renderFeeds() {
      const el = document.getElementById("feeds");
      if (!config.rss_feeds.length) {
        el.innerHTML = `<div class="empty">등록된 RSS 없음</div>`;
        return;
      }
      el.innerHTML = config.rss_feeds.map((feed, index) => `
        <div class="feed-row">
          <input value="${escapeHtml(feed.name)}" data-field="name" data-index="${index}">
          <input value="${escapeHtml(feed.url)}" data-field="url" data-index="${index}">
          <button class="danger icon" title="삭제" data-remove="${index}">x</button>
        </div>
      `).join("");
      el.querySelectorAll("input").forEach(input => {
        input.addEventListener("change", async () => {
          config.rss_feeds[Number(input.dataset.index)][input.dataset.field] = input.value.trim();
          try { await saveConfig("출처 저장됨"); } catch (error) { setMessage(error.message, "bad"); }
        });
      });
      el.querySelectorAll("button[data-remove]").forEach(button => {
        button.addEventListener("click", async () => {
          config.rss_feeds.splice(Number(button.dataset.remove), 1);
          renderConfig();
          try { await saveConfig("출처 저장됨"); } catch (error) { setMessage(error.message, "bad"); }
        });
      });
    }

    function renderConfig() {
      ensureConfig();
      renderChips("keywords", config.keywords, index => {
        config.keywords.splice(index, 1);
        renderConfig();
        saveConfig("키워드 저장됨").catch(error => setMessage(error.message, "bad"));
      });
      renderChips("excludeKeywords", config.exclude_keywords, index => {
        config.exclude_keywords.splice(index, 1);
        renderConfig();
        saveConfig("제외 키워드 저장됨").catch(error => setMessage(error.message, "bad"));
      });
      document.getElementById("schedulerEnabled").checked = !!config.scheduler.enabled;
      document.getElementById("instantAlerts").checked = !!config.scheduler.instant_alerts;
      document.getElementById("fixedTimeAlerts").checked = !!config.scheduler.fixed_time_alerts;
      document.getElementById("interval").value = String(config.scheduler.poll_interval_seconds || 600);
      document.getElementById("fixedTimes").value = (config.scheduler.fixed_times || []).join(", ");
      document.getElementById("naverEnabled").checked = config.naver.enabled !== false;
      document.getElementById("naverDisplay").value = config.naver.display || 20;
      document.getElementById("naverSort").value = config.naver.sort || "date";
      document.getElementById("telegramEnabled").checked = !!config.notifications.telegram_enabled;
      renderFeeds();
    }

    function syncFormToConfig() {
      ensureConfig();
      config.scheduler.enabled = document.getElementById("schedulerEnabled").checked;
      config.scheduler.instant_alerts = document.getElementById("instantAlerts").checked;
      config.scheduler.fixed_time_alerts = document.getElementById("fixedTimeAlerts").checked;
      config.scheduler.poll_interval_seconds = Number(document.getElementById("interval").value);
      config.scheduler.fixed_times = document.getElementById("fixedTimes").value
        .split(",")
        .map(value => value.trim())
        .filter(Boolean);
      config.naver.enabled = document.getElementById("naverEnabled").checked;
      config.naver.display = Number(document.getElementById("naverDisplay").value || 20);
      config.naver.sort = document.getElementById("naverSort").value;
      config.notifications.telegram_enabled = document.getElementById("telegramEnabled").checked;
    }

    async function saveConfig(message = "저장됨") {
      syncFormToConfig();
      const data = await request("/api/config", {
        method: "POST",
        body: JSON.stringify(config)
      });
      config = data.config;
      renderConfig();
      setMessage(message, "ok");
      await loadState();
    }

    async function addItem(inputId, target, message) {
      const input = document.getElementById(inputId);
      const value = input.value.trim();
      if (!value) return;
      if (!target.includes(value)) target.push(value);
      input.value = "";
      renderConfig();
      await saveConfig(message);
    }

    function parseListText(text) {
      const seen = new Set();
      const items = [];
      text.split(/\r?\n/)
        .map(value => value.replace(/^\ufeff/, "").trim())
        .filter(Boolean)
        .forEach(value => {
          const key = value.toLocaleLowerCase();
          if (seen.has(key)) return;
          seen.add(key);
          items.push(value);
        });
      return items;
    }

    async function readTextFile(file) {
      const buffer = await file.arrayBuffer();
      const decoders = [
        () => new TextDecoder("utf-8", { fatal: true }),
        () => new TextDecoder("euc-kr", { fatal: true }),
        () => new TextDecoder("utf-8")
      ];
      let lastError = null;
      for (const createDecoder of decoders) {
        try {
          return createDecoder().decode(buffer);
        } catch (error) {
          lastError = error;
        }
      }
      throw lastError || new Error("파일을 읽을 수 없습니다.");
    }

    async function importListFile(fileInputId, target, messagePrefix) {
      const input = document.getElementById(fileInputId);
      const file = input.files && input.files[0];
      if (!file) return;

      try {
        const items = parseListText(await readTextFile(file));
        const existing = new Set(target.map(value => String(value).toLocaleLowerCase()));
        let added = 0;
        items.forEach(item => {
          const key = item.toLocaleLowerCase();
          if (existing.has(key)) return;
          existing.add(key);
          target.push(item);
          added += 1;
        });
        input.value = "";
        renderConfig();
        await saveConfig(`${messagePrefix} ${added}개 저장됨`);
      } catch (error) {
        input.value = "";
        setMessage(error.message, "bad");
      }
    }

    function wireControls() {
      document.getElementById("addKeyword").addEventListener("click", async () => {
        try { await addItem("keywordInput", config.keywords, "키워드 저장됨"); } catch (error) { setMessage(error.message, "bad"); }
      });
      document.getElementById("keywordInput").addEventListener("keydown", event => {
        if (event.key === "Enter") {
          event.preventDefault();
          addItem("keywordInput", config.keywords, "키워드 저장됨").catch(error => setMessage(error.message, "bad"));
        }
      });
      document.getElementById("importKeywords").addEventListener("click", () => document.getElementById("keywordFile").click());
      document.getElementById("keywordFile").addEventListener("change", () => {
        importListFile("keywordFile", config.keywords, "키워드").catch(error => setMessage(error.message, "bad"));
      });
      document.getElementById("addExclude").addEventListener("click", async () => {
        try { await addItem("excludeInput", config.exclude_keywords, "제외 키워드 저장됨"); } catch (error) { setMessage(error.message, "bad"); }
      });
      document.getElementById("excludeInput").addEventListener("keydown", event => {
        if (event.key === "Enter") {
          event.preventDefault();
          addItem("excludeInput", config.exclude_keywords, "제외 키워드 저장됨").catch(error => setMessage(error.message, "bad"));
        }
      });
      document.getElementById("importExcludes").addEventListener("click", () => document.getElementById("excludeFile").click());
      document.getElementById("excludeFile").addEventListener("change", () => {
        importListFile("excludeFile", config.exclude_keywords, "제외 키워드").catch(error => setMessage(error.message, "bad"));
      });
      document.getElementById("addFeed").addEventListener("click", async () => {
        const name = document.getElementById("feedName").value.trim();
        const url = document.getElementById("feedUrl").value.trim();
        if (!name || !url) return;
        config.rss_feeds.push({ name, url });
        document.getElementById("feedName").value = "";
        document.getElementById("feedUrl").value = "";
        renderConfig();
        try { await saveConfig("출처 저장됨"); } catch (error) { setMessage(error.message, "bad"); }
      });
      document.getElementById("saveConfig").addEventListener("click", async () => {
        try { await saveConfig(); } catch (error) { setMessage(error.message, "bad"); }
      });
      document.getElementById("checkNow").addEventListener("click", async () => {
        try {
          setMessage("검사 중");
          const data = await request("/api/check-now", { method: "POST", body: "{}" });
          setMessage(`새 기사 ${data.new_count}개`, "ok");
          await loadAll();
        } catch (error) { setMessage(error.message, "bad"); }
      });
      document.getElementById("markSeen").addEventListener("click", async () => {
        try {
          const data = await request("/api/mark-seen", { method: "POST", body: "{}" });
          setMessage(`현재 결과 ${data.total_count}개 저장됨`, "ok");
          await loadAll();
        } catch (error) { setMessage(error.message, "bad"); }
      });
      document.getElementById("testTelegram").addEventListener("click", async () => {
        try {
          const data = await request("/api/test-telegram", { method: "POST", body: "{}" });
          setMessage(data.message, "ok");
          await loadState();
        } catch (error) { setMessage(error.message, "bad"); }
      });
    }

    function renderState(data) {
      const state = data.state;
      const dot = document.getElementById("statusDot");
      const text = document.getElementById("statusText");
      dot.className = "dot";
      if (state.last_error) {
        dot.classList.add("bad");
        text.textContent = "오류";
      } else if (state.checking) {
        dot.classList.add("warn");
        text.textContent = "검사 중";
      } else if (state.running) {
        dot.classList.add("ok");
        text.textContent = "실행 중";
      } else {
        text.textContent = "정지";
      }
      document.getElementById("summary").innerHTML = `
        <span>마지막 검사: ${escapeHtml(state.last_check_at || "-")}</span>
        <span>다음 검사: ${escapeHtml(state.next_check_at || "-")}</span>
        <span>최근 새 기사: ${escapeHtml(state.last_new_count)}</span>
      `;
      document.getElementById("telegramStatus").textContent = data.telegram_configured
        ? `텔레그램 구독자 ${data.telegram_recipient_count || 0}명`
        : "텔레그램 연결 정보 없음";
      document.getElementById("telegramMode").textContent = data.telegram_enabled
        ? "알림 켜짐"
        : "알림 꺼짐";
      renderEvents(data.events || []);
    }

    function renderArticles(items) {
      const el = document.getElementById("articles");
      if (!items.length) {
        el.innerHTML = `<div class="empty">저장된 기사 없음</div>`;
        return;
      }
      el.innerHTML = items.map(item => `
        <article class="article">
          <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>
          <div class="meta-row">
            <span>${escapeHtml(item.source)}</span>
            <span>${escapeHtml(item.matched_keywords)}</span>
            <span>${escapeHtml(item.published_at || item.first_seen_at || "")}</span>
          </div>
          <p>${escapeHtml(item.snippet || "")}</p>
        </article>
      `).join("");
    }

    function renderEvents(events) {
      const el = document.getElementById("events");
      if (!events.length) {
        el.innerHTML = `<div class="empty">기록 없음</div>`;
        return;
      }
      el.innerHTML = events.map(event => `
        <div class="event">
          <span>${escapeHtml(event.time)}</span>
          <span>${escapeHtml(event.message)}</span>
        </div>
      `).join("");
    }

    async function loadState() {
      const state = await request("/api/state");
      renderState(state);
    }

    async function loadAll() {
      const [configData, articleData, stateData] = await Promise.all([
        request("/api/config"),
        request("/api/articles?limit=40"),
        request("/api/state")
      ]);
      config = configData.config;
      renderConfig();
      renderArticles(articleData.articles);
      renderState(stateData);
    }

    wireControls();
    loadAll().catch(error => setMessage(error.message, "bad"));
    setInterval(() => {
      loadState().catch(() => {});
      request("/api/articles?limit=40").then(data => renderArticles(data.articles)).catch(() => {});
    }, 15000);
  </script>
</body>
</html>
"""


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def local_time_text(value: dt.datetime | None = None) -> str:
    value = value or now_kst()
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")


def add_event(message: str) -> None:
    with STATE_LOCK:
        EVENTS.appendleft({"time": now_kst().strftime("%H:%M:%S"), "message": message})


def normalize_string_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def validate_fixed_time(value: str) -> bool:
    if not re.match(r"^\d{2}:\d{2}$", value):
        return False
    hour, minute = value.split(":", 1)
    return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59


def normalize_config(config: dict) -> dict:
    config = dict(config or {})
    config["keywords"] = normalize_string_list(config.get("keywords"))
    config["exclude_keywords"] = normalize_string_list(config.get("exclude_keywords"))

    naver = dict(config.get("naver") or {})
    naver["enabled"] = bool(naver.get("enabled", True))
    naver["display"] = max(1, min(100, int(naver.get("display", 20) or 20)))
    naver["sort"] = naver.get("sort") if naver.get("sort") in {"date", "sim"} else "date"
    config["naver"] = naver

    feeds = []
    for feed in config.get("rss_feeds") or []:
        name = str(feed.get("name", "")).strip()
        url = str(feed.get("url", "")).strip()
        if name and url:
            feeds.append({"name": name, "url": url})
    config["rss_feeds"] = feeds

    scheduler = dict(config.get("scheduler") or {})
    scheduler["enabled"] = bool(scheduler.get("enabled", True))
    scheduler["poll_interval_seconds"] = max(60, int(scheduler.get("poll_interval_seconds", 600) or 600))
    scheduler["instant_alerts"] = bool(scheduler.get("instant_alerts", True))
    scheduler["fixed_time_alerts"] = bool(scheduler.get("fixed_time_alerts", False))
    fixed_times = normalize_string_list(scheduler.get("fixed_times") or ["09:00"])
    invalid_times = [value for value in fixed_times if not validate_fixed_time(value)]
    if invalid_times:
        raise ValueError(f"고정 알림 시간 형식 오류: {', '.join(invalid_times)}")
    scheduler["fixed_times"] = fixed_times
    config["scheduler"] = scheduler

    notifications = dict(config.get("notifications") or {})
    notifications["console_enabled"] = bool(notifications.get("console_enabled", True))
    notifications["telegram_enabled"] = bool(notifications.get("telegram_enabled", False))
    config["notifications"] = notifications

    config["database"] = str(config.get("database") or "news_alerts.sqlite3")
    return config


def read_config() -> dict:
    try:
        return normalize_config(load_config(CONFIG_PATH))
    except FileNotFoundError:
        return normalize_config({})


def write_config(config: dict) -> dict:
    normalized = normalize_config(config)
    CONFIG_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    add_event("설정 저장")
    return normalized


def db_path(config: dict) -> Path:
    return BASE_DIR / config.get("database", "news_alerts.sqlite3")


def telegram_recipient_ids(config: dict) -> list[str]:
    conn = init_db(db_path(config))
    try:
        sync_telegram_subscribers(conn)
        return get_telegram_chat_ids(conn)
    finally:
        conn.close()


def ensure_service_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS service_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.commit()


def get_service_value(conn: sqlite3.Connection, key: str) -> str | None:
    ensure_service_tables(conn)
    row = conn.execute("SELECT value FROM service_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_service_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    ensure_service_tables(conn)
    conn.execute(
        """
        INSERT INTO service_state (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    conn.commit()


def mark_notified(config: dict, articles: list[Article]) -> None:
    if not articles:
        return
    with init_db(db_path(config)) as conn:
        notified_at = now_utc_iso()
        for article in articles:
            conn.execute("UPDATE articles SET notified_at = ? WHERE article_key = ?", (notified_at, article.key))
        conn.commit()


def row_to_article(row: sqlite3.Row) -> Article:
    keywords = tuple(part.strip() for part in (row["matched_keywords"] or "").split(",") if part.strip())
    return Article(
        source=row["source"],
        title=row["title"],
        url=row["url"],
        published_at=row["published_at"] or "",
        snippet=row["snippet"] or "",
        matched_keywords=keywords,
    )


def recent_articles(limit: int = 40) -> list[dict]:
    config = read_config()
    with init_db(db_path(config)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT source, title, url, published_at, snippet, matched_keywords, first_seen_at, notified_at
            FROM articles
            ORDER BY first_seen_at DESC
            LIMIT ?
            """,
            (max(1, min(200, limit)),),
        ).fetchall()
    return [dict(row) for row in rows]


def articles_since(config: dict, since_iso: str | None) -> list[Article]:
    since_iso = since_iso or "1970-01-01T00:00:00+00:00"
    with init_db(db_path(config)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT source, title, url, published_at, snippet, matched_keywords
            FROM articles
            WHERE first_seen_at > ?
            ORDER BY first_seen_at ASC
            """,
            (since_iso,),
        ).fetchall()
    return [row_to_article(row) for row in rows]


def send_telegram_text(text: str, chat_ids: list[str]) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or not chat_ids:
        return 0

    sent_count = 0
    for chat_id in chat_ids:
        telegram_message(token, chat_id, text[:3900])
        sent_count += 1
    return sent_count


def send_fixed_digest(config: dict, slot: str) -> None:
    if not config["scheduler"]["fixed_time_alerts"]:
        return
    today_slot = f"{now_kst().strftime('%Y-%m-%d')} {slot}"

    with init_db(db_path(config)) as conn:
        last_slot = get_service_value(conn, "last_fixed_slot")
        if last_slot == today_slot:
            return
        last_digest_at = get_service_value(conn, "last_fixed_digest_at")

    articles = articles_since(config, last_digest_at)
    with init_db(db_path(config)) as conn:
        set_service_value(conn, "last_fixed_slot", today_slot)
        set_service_value(conn, "last_fixed_digest_at", now_utc_iso())

    if not articles:
        add_event(f"고정 알림 {slot}: 새 기사 없음")
        return

    if config["notifications"]["telegram_enabled"]:
        text = f"[뉴스 요약] {slot} 기준 새 기사 {len(articles)}개"
        try:
            chat_ids = telegram_recipient_ids(config)
            if not chat_ids:
                raise ValueError("텔레그램 구독자가 없습니다. 봇에 /start를 먼저 보내주세요.")
            send_telegram_text(text, chat_ids)
            notify_telegram(articles, chat_ids)
            mark_notified(config, articles)
            add_event(f"고정 알림 {slot}: {len(articles)}개 전송")
        except Exception as exc:
            add_event(f"고정 알림 실패: {exc}")
    else:
        add_event(f"고정 알림 {slot}: {len(articles)}개, 텔레그램 꺼짐")


def perform_check(mark_seen: bool = False, reason: str = "manual") -> dict:
    config = read_config()
    with STATE_LOCK:
        RUNTIME_STATE["checking"] = True
        RUNTIME_STATE["last_error"] = None

    try:
        articles = collect_articles(config)
        with init_db(db_path(config)) as conn:
            new_articles = save_new_articles(conn, articles, mark_seen=mark_seen)

        if mark_seen:
            add_event(f"현재 결과 {len(articles)}개 저장")
        elif new_articles:
            if config["notifications"]["console_enabled"]:
                notify_console(new_articles)
            if config["scheduler"]["instant_alerts"] and config["notifications"]["telegram_enabled"]:
                chat_ids = telegram_recipient_ids(config)
                if not chat_ids:
                    raise ValueError("텔레그램 구독자가 없습니다. 봇에 /start를 먼저 보내주세요.")
                notify_telegram(new_articles, chat_ids)
                mark_notified(config, new_articles)
                add_event(f"새 기사 {len(new_articles)}개 즉시 전송")
            else:
                add_event(f"새 기사 {len(new_articles)}개 발견")
        else:
            add_event("새 기사 없음")

        with STATE_LOCK:
            RUNTIME_STATE["last_check_at"] = local_time_text()
            RUNTIME_STATE["last_total_count"] = len(articles)
            RUNTIME_STATE["last_new_count"] = 0 if mark_seen else len(new_articles)
            RUNTIME_STATE["last_error"] = None

        return {
            "total_count": len(articles),
            "new_count": 0 if mark_seen else len(new_articles),
            "reason": reason,
        }
    except Exception as exc:
        with STATE_LOCK:
            RUNTIME_STATE["last_error"] = str(exc)
        add_event(f"검사 실패: {exc}")
        traceback.print_exc()
        raise
    finally:
        with STATE_LOCK:
            RUNTIME_STATE["checking"] = False


def scheduler_loop() -> None:
    add_event("웹서비스 시작")
    next_poll = time.monotonic() + 2

    while not STOP_EVENT.is_set():
        config = read_config()
        scheduler = config["scheduler"]
        interval = scheduler["poll_interval_seconds"]

        with STATE_LOCK:
            RUNTIME_STATE["running"] = scheduler["enabled"]
            RUNTIME_STATE["next_check_at"] = (
                local_time_text(dt.datetime.fromtimestamp(time.time() + max(0, next_poll - time.monotonic()), KST))
                if scheduler["enabled"]
                else None
            )

        current_slot = now_kst().strftime("%H:%M")
        if scheduler["enabled"] and current_slot in scheduler["fixed_times"]:
            send_fixed_digest(config, current_slot)

        if scheduler["enabled"] and time.monotonic() >= next_poll:
            try:
                perform_check(mark_seen=False, reason="schedule")
            except Exception:
                pass
            next_poll = time.monotonic() + interval

        STOP_EVENT.wait(5)


class Handler(BaseHTTPRequestHandler):
    server_version = "YHNewsAlert/1.0"

    def log_message(self, fmt, *args):
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self) -> None:
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self.send_html()
            return

        if parsed.path == "/api/health":
            self.send_json({"ok": True})
            return

        if parsed.path == "/api/config":
            self.send_json({"config": read_config()})
            return

        if parsed.path == "/api/articles":
            params = urllib.parse.parse_qs(parsed.query)
            limit = int(params.get("limit", ["40"])[0])
            self.send_json({"articles": recent_articles(limit)})
            return

        if parsed.path == "/api/state":
            with STATE_LOCK:
                state = dict(RUNTIME_STATE)
                events = list(EVENTS)
            config = read_config()
            token_present = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
            recipient_count = len(telegram_recipient_ids(config)) if token_present else 0
            self.send_json(
                {
                    "state": state,
                    "events": events,
                    "telegram_configured": bool(token_present and recipient_count),
                    "telegram_recipient_count": recipient_count,
                    "telegram_enabled": bool(config["notifications"]["telegram_enabled"]),
                }
            )
            return

        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/config":
                config = write_config(self.read_json_body())
                self.send_json({"config": config})
                return

            if parsed.path == "/api/check-now":
                result = perform_check(mark_seen=False, reason="manual")
                self.send_json(result)
                return

            if parsed.path == "/api/mark-seen":
                result = perform_check(mark_seen=True, reason="manual")
                self.send_json(result)
                return

            if parsed.path == "/api/test-telegram":
                config = read_config()
                if not os.environ.get("TELEGRAM_BOT_TOKEN"):
                    raise ValueError("텔레그램 토큰이 없습니다.")
                chat_ids = telegram_recipient_ids(config)
                if not chat_ids:
                    raise ValueError("텔레그램 구독자가 없습니다. 봇에 /start를 먼저 보내주세요.")
                sent_count = send_telegram_text(f"뉴스 알림 테스트 전송\n{local_time_text()}", chat_ids)
                add_event(f"텔레그램 테스트 전송: {sent_count}명")
                self.send_json({"message": f"텔레그램 테스트 메시지 {sent_count}명에게 전송됨"})
                return

            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> int:
    configure_stdio()
    write_config(read_config())

    worker = threading.Thread(target=scheduler_loop, name="news-alert-scheduler", daemon=True)
    worker.start()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"뉴스 알림 웹서비스 실행: http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STOP_EVENT.set()
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
