#!/usr/bin/env python3
"""Send today's daily reports to Telegram as plain-text messages.

Reports stay as Markdown in the repo; for Telegram each article section is
converted to plain text (one message per article, split if over the 4096-char
limit) with bare URLs so Telegram renders them as clickable links.

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

REPORTS_DIR = Path("reports")
STATS_RE = re.compile(r"發現：(\d+) 篇，完成：(\d+) 篇，略過：(\d+) 篇")
TITLE_RE = re.compile(r"^# (.+?) 每日文獻導讀")
MAX_LEN = 3900  # margin under Telegram's 4096-char message limit


def send_message(token: str, chat_id: str, text: str) -> None:
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt in range(2):
        try:
            with urllib.request.urlopen(url, data=data, timeout=60) as resp:
                resp.read()
            return
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt == 0:
                retry_after = json.loads(exc.read()).get("parameters", {}).get("retry_after", 5)
                time.sleep(retry_after + 1)
                continue
            raise


def strip_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = text.replace("`", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_message(text: str) -> list[str]:
    if len(text) <= MAX_LEN:
        return [text]
    chunks, current = [], ""
    for para in text.split("\n\n"):
        while len(para) > MAX_LEN:  # single oversized paragraph: hard split
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:MAX_LEN])
            para = para[MAX_LEN:]
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > MAX_LEN:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [f"({i}/{len(chunks)})\n{chunk}" for i, chunk in enumerate(chunks, 1)] if len(chunks) > 1 else chunks


def article_sections(text: str) -> list[str]:
    """Split the report body into '## ' sections, skipping the error section."""
    sections = re.split(r"(?m)^## ", text)[1:]
    return [s for s in sections if not s.startswith("執行錯誤")]


def article_messages(label: str, section: str) -> list[str]:
    lines = section.rstrip().split("\n")
    title, body = lines[0].strip(), "\n".join(lines[1:])
    text = strip_markdown(f"📄 {title}\n\n{body}")
    return split_message(f"【{label}】\n{text}")


def find_reports() -> tuple[str, list[Path]]:
    today = date.today().isoformat()
    reports = sorted(REPORTS_DIR.glob(f"{today}-*-daily.md"))
    if reports:
        return today, reports
    dates = sorted({p.name[:10] for p in REPORTS_DIR.glob("????-??-??-*-daily.md")})
    if not dates:
        return today, []
    latest = dates[-1]
    return latest, sorted(REPORTS_DIR.glob(f"{latest}-*-daily.md"))


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set", file=sys.stderr)
        return 1

    report_date, reports = find_reports()
    if not reports:
        send_message(token, chat_id, f"🧠 {report_date} 沒有產生任何 daily report。")
        return 0

    summary = [f"🧠 神經科每日文獻 {report_date}", ""]
    queue = []
    total = 0
    for path in reports:
        text = path.read_text(encoding="utf-8")
        title_match = TITLE_RE.search(text)
        stats_match = STATS_RE.search(text)
        label = title_match.group(1) if title_match else path.stem
        processed = int(stats_match.group(2)) if stats_match else 0
        total += processed
        summary.append(f"• {label}：{processed} 篇")
        if processed > 0:
            for section in article_sections(text):
                queue.extend(article_messages(label, section))
    summary += ["", f"共 {total} 篇新文獻/摘要。"]

    send_message(token, chat_id, "\n".join(summary))
    for message in queue:
        time.sleep(1.1)  # stay under Telegram per-chat rate limits
        send_message(token, chat_id, message)
    print(f"sent summary + {len(queue)} message(s) for {report_date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
