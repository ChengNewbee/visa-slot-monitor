#!/usr/bin/env python3
"""Read-only Beijing B1/B2 slot monitor.

This program reads VisaBida's public, no-login B1/B2 summary and sends an alert
when Beijing's earliest regular-interview date enters the requested range. It
never opens or logs into the U.S. visa portal and never stores visa credentials.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import random
import re
import smtplib
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from email.header import Header
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_DIR = Path(__file__).resolve().parent
SOURCE_URL = "https://visabida.com/"
OFFICIAL_URL = "https://www.ustraveldocs.com/?country=China"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def load_env_file(path: Path) -> None:
    """Load a small KEY=VALUE file without overriding existing environment."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(PROJECT_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(f"VISA_{name}", default).strip()


CITY = env("CITY", "北京")
VISA_TYPE = env("TYPE", "B1/B2")
DESCRIPTION = env("DESCRIPTION", "All Others")
START_TEXT = env("START", "TODAY")
END_TEXT = env("END", "2026-11-30")
POLL_SECONDS = max(45, int(env("POLL_SECONDS", "60")))
NTFY_TOPIC = env("NTFY_TOPIC")
NTFY_SERVER = env("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
EMAIL_TO = env("EMAIL_TO")
SMTP_HOST = env("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(env("SMTP_PORT", "465"))
SMTP_USER = env("SMTP_USER")
SMTP_PASSWORD = env("SMTP_PASSWORD")
HEALTH_HOUR = min(23, max(0, int(env("HEALTH_HOUR", "9"))))
STATE_PATH = Path(env("STATE", ".state/state.json"))
if not STATE_PATH.is_absolute():
    STATE_PATH = PROJECT_DIR / STATE_PATH


def today_beijing() -> dt.date:
    return dt.datetime.now(BEIJING_TZ).date()


def parse_boundary(text: str, *, today: dt.date) -> dt.date:
    if text.upper() == "TODAY":
        return today
    return dt.date.fromisoformat(text)


def active_range(today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    today = today or today_beijing()
    configured_start = parse_boundary(START_TEXT, today=today)
    start = max(today, configured_start)
    end = parse_boundary(END_TEXT, today=today)
    if end < start:
        raise ValueError(f"monitoring period has ended: {start} > {end}")
    return start, end


def parse_full_cn_date(text: str) -> dt.date:
    match = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if not match:
        raise ValueError(text)
    year, month, day = map(int, match.groups())
    return dt.date(year, month, day)


def fetch_public_summary() -> str:
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": user_agent, "Accept-Language": "zh-CN,zh;q=0.9"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_public_summary(document: str, *, city: str = CITY) -> dict[str, object]:
    scope_match = re.search(r'<p class="summary-scope">(.*?)</p>', document, re.S)
    scope = _plain(scope_match.group(1)) if scope_match else ""
    if VISA_TYPE not in scope or "普通面谈" not in scope:
        raise RuntimeError(f"unexpected-summary-scope:{scope or 'missing'}")

    cards = re.findall(r'<article class="[^"]*trend-compare-card[^"]*">(.*?)</article>', document, re.S)
    card = next((item for item in cards if re.search(rf"<h3>\s*{re.escape(city)}\s*</h3>", item)), None)
    if card is None:
        raise RuntimeError(f"city-not-found:{city}")

    date_match = re.search(r'<p class="summary-date">\s*(.*?)\s*</p>', card, re.S)
    date_text = _plain(date_match.group(1)) if date_match else ""
    earliest = None if "未观测到日期" in date_text else parse_full_cn_date(date_text)
    count_match = re.search(r"([\d,]+)\s*个可约日期", _plain(card))
    count = int(count_match.group(1).replace(",", "")) if count_match else 0
    observed_match = re.search(r'<time datetime="([^"]+)">([^<]+)</time>', card, re.S)
    observed_at = observed_match.group(1) if observed_match else ""
    observed_text = _plain(observed_match.group(2)) if observed_match else "未知"
    stale = "已过期" in _plain(card)
    return {
        "city": city,
        "earliest": earliest,
        "count": count,
        "observed_at": observed_at,
        "observed_text": observed_text,
        "stale": stale,
        "scope": scope,
    }


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


def ntfy_push(title: str, body: str, priority: str = "urgent") -> bool:
    if not NTFY_TOPIC:
        return False
    headers = {
        "Title": Header(title, "utf-8").encode(),
        "Priority": priority,
        "Tags": "rotating_light" if priority == "urgent" else "information_source",
        "Click": OFFICIAL_URL,
    }
    request = urllib.request.Request(
        f"{NTFY_SERVER}/{urllib.parse.quote(NTFY_TOPIC)}",
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()
    return True


def send_email(title: str, body: str) -> bool:
    if not EMAIL_TO or not SMTP_USER or not SMTP_PASSWORD:
        print("[notify] QQ SMTP authorization code not configured; email skipped", flush=True)
        return False
    message = EmailMessage()
    message["Subject"] = title
    message["From"] = SMTP_USER
    message["To"] = EMAIL_TO
    message.set_content(body + f"\n\n官方预约入口：{OFFICIAL_URL}\n数据来源：{SOURCE_URL}")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=25) as smtp:
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(message)
    return True


def local_alert(title: str, body: str) -> bool:
    if sys.platform != "darwin":
        return False
    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    script = f'display notification "{esc(body)}" with title "{esc(title)}" sound name "Sosumi"'
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    return result.returncode == 0


def notify(title: str, body: str, *, urgent: bool = True) -> None:
    delivered = []
    try:
        if ntfy_push(title, body, "urgent" if urgent else "default"):
            delivered.append("ntfy")
    except Exception as exc:  # notification channels must not stop monitoring
        print(f"[notify] ntfy failed: {exc}", flush=True)
    try:
        if send_email(title, body):
            delivered.append("email")
    except Exception as exc:
        print(f"[notify] email failed: {exc}", flush=True)
    try:
        if local_alert(title, body):
            delivered.append("macOS")
    except Exception as exc:
        print(f"[notify] local notification failed: {exc}", flush=True)
    print(f"[notify] delivered through: {', '.join(delivered) or 'none'}", flush=True)


def check_once(*, health: bool = True) -> bool:
    now = dt.datetime.now(BEIJING_TZ)
    state = load_state()
    try:
        start, end = active_range(now.date())
    except ValueError as exc:
        if not state.get("ended_notified"):
            notify("美签提醒器已到截止日期", str(exc), urgent=False)
            state["ended_notified"] = True
            save_state(state)
        print(f"[{now.isoformat()}] ENDED: {exc}", flush=True)
        return True

    try:
        meta = parse_public_summary(fetch_public_summary())
        earliest = meta.get("earliest")
        if meta.get("stale"):
            raise RuntimeError(f"source-observation-stale:{meta.get('observed_text')}")
        dates = [earliest] if isinstance(earliest, dt.date) and start <= earliest <= end else []
    except Exception as exc:
        failures = int(state.get("consecutive_failures", 0)) + 1
        state["consecutive_failures"] = failures
        state["last_error"] = f"{now.isoformat()} {type(exc).__name__}: {exc}"
        if failures >= 3 and not state.get("failure_notified"):
            notify(
                "⚠️ 美签提醒器连续读取失败",
                f"已连续失败 {failures} 次：{exc}\n程序会继续自动重试。",
                urgent=False,
            )
            state["failure_notified"] = True
        save_state(state)
        print(f"[{now.isoformat()}] SCRAPE_FAILED #{failures}: {exc}", flush=True)
        return False

    recovered = bool(state.get("failure_notified"))
    state["consecutive_failures"] = 0
    state["failure_notified"] = False
    state["last_success"] = now.isoformat()
    current = [value.isoformat() for value in dates]
    previous = set(state.get("visible_dates", []))
    fresh = [value for value in current if value not in previous]
    previous_count = int(state.get("last_city_count", 0) or 0)
    count_increased = bool(current) and int(meta.get("count", 0) or 0) > previous_count

    if fresh or count_increased:
        title = f"🚨 北京 B1/B2 发现可约日期"
        body = (
            f"公开摘要最早日期：{', '.join(current)}\n"
            f"可约日期数量：{meta.get('count', 0)}（不是名额数）\n"
            f"数据观测时间：{meta.get('observed_text', '未知')} 北京时间\n"
            f"目标范围：{start.isoformat()} 至 {end.isoformat()}\n"
            f"发现时间：{now.strftime('%Y-%m-%d %H:%M:%S')} 北京时间\n"
            "请立即手动登录官方预约系统核实。"
        )
        notify(title, body)

    if recovered:
        notify("✅ 美签提醒器已恢复", "公开日历已恢复正常读取。", urgent=False)

    health_day = state.get("last_health_day")
    if health and now.hour >= HEALTH_HOUR and health_day != now.date().isoformat():
        summary = ", ".join(current) if current else "目标范围内暂无号源"
        notify(
            "✅ 美签提醒器每日状态",
            f"监控正常。{summary}\n最后检查：{now.strftime('%Y-%m-%d %H:%M:%S')}",
            urgent=False,
        )
        state["last_health_day"] = now.date().isoformat()

    state["visible_dates"] = current
    state["last_city_count"] = meta.get("count")
    save_state(state)
    print(
        f"[{now.isoformat()}] OK city={CITY} type={VISA_TYPE} "
        f"range={start}..{end} matches={current or 'none'}",
        flush=True,
    )
    return True


def watch(interval: int) -> None:
    print(f"Watching {CITY} {VISA_TYPE} every ~{interval}s; Ctrl-C to stop.", flush=True)
    while True:
        check_once()
        time.sleep(interval + random.uniform(0, min(8, interval * 0.1)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="check once and exit")
    parser.add_argument("--watch", type=int, metavar="SECONDS", help="keep checking")
    parser.add_argument("--test-notify", action="store_true", help="send a test notification")
    args = parser.parse_args()
    if args.test_notify:
        notify(
            "🧪 美签提醒器测试",
            f"监控目标：{CITY} {VISA_TYPE} {DESCRIPTION}\n截止日期：{END_TEXT}",
            urgent=False,
        )
        return 0
    if args.watch:
        watch(max(45, args.watch))
        return 0
    check_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
