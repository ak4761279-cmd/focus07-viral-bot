import os
import sys
import json
import time
import random
import requests
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = str(os.environ.get("CHAT_ID", "")).strip()
STATE_FILE = "bot_state.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

SEED_QUERIES = [
    ("JEE Mains 2027", "JEE Mains"),
    ("Bihar Polytechnic DCECE", "Polytechnic Entrance"),
    ("BCECE 2027", "BCECE Entrance"),
    ("Bihar Engineering BEU", "B.Tech / UGEAC"),
    ("SBTE Bihar", "Polytechnic Semester"),
    ("JEE Mains percentile vs college", "JEE + Bihar College")
]

def get_ist_time():
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    return now.strftime("%d %b %Y | %I:%M %p IST"), now.month

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_update_id": 0, "history": []}

def save_state(state):
    state["history"] = state["history"][-150:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def safe_request(method, url, **kwargs):
    kwargs.setdefault("headers", HEADERS)
    kwargs.setdefault("timeout", 15)
    for attempt in range(3):
        try:
            if method == "GET":
                return requests.get(url, **kwargs)
            return requests.post(url, **kwargs)
        except Exception as e:
            print(f"Retry {attempt + 1} due to: {e}")
            time.sleep(2)
    return None

def check_for_send_command(state):
    offset = state.get("last_update_id", 0) + 1
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=5"
    triggered = False
    resp = safe_request("GET", url)
    if resp and resp.status_code == 200:
        data = resp.json()
        if data.get("ok"):
            for update in data.get("result", []):
                state["last_update_id"] = update["update_id"]
                msg = update.get("message", {})
                sender_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip().lower()
                if sender_id == CHAT_ID and text in ["send", "/send", "topics", "topic"]:
                    triggered = True
    return triggered

def get_live_student_searches(seed):
    url = f"https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q={requests.utils.quote(seed)}"
    resp = safe_request("GET", url)
    if resp and resp.status_code == 200:
        try:
            data = resp.json()
            return [s for s in data[1] if s.lower() != seed.lower()][:4]
        except Exception:
            return []
    return []

def format_as_viral_title(raw_query, category, month):
    q = raw_query.title()
    season_tag = "2027 Target" if month in [11, 12] else ("Exam & Form Alert" if month in [1, 2, 3, 4] else "Counselling & Admission")
    templates = [
        f"🔥 <b>{q}</b> — पूरी सच्चाई और लेटेस्ट अपडेट! ({season_tag})",
        f"🚨 <b>{q}</b> | स्टूडेंट्स सबसे ज़्यादा यही सर्च कर रहे हैं!",
        f"🎯 <b>{q}</b> — गलती मत करना, वीडियो पूरा देखो!"
    ]
    return f"[{category}] {random.choice(templates)}\n🔍 <i>Exact Student Search:</i> <code>{raw_query}</code>"

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = safe_request("POST", url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    if resp:
        print("Telegram response:", resp.status_code, resp.text)

def generate_and_send_topics(state):
    ist_str, current_month = get_ist_time()
    history = state.get("history", [])
    top_5_topics = []

    for seed, category in SEED_QUERIES:
        if len(top_5_topics) >= 5:
            break
        for query in get_live_student_searches(seed):
            if query.lower() not in history:
                top_5_topics.append(format_as_viral_title(query, category, current_month))
                history.append(query.lower())
                break

    if len(top_5_topics) < 5:
        for seed, category in SEED_QUERIES:
            if len(top_5_topics) >= 5:
                break
            suggestions = get_live_student_searches(seed)
            if suggestions:
                top_5_topics.append(format_as_viral_title(suggestions[0], category, current_month))

    header = (
        f"📊 <b>FOCUS 07 — TOP 5 VIRAL SEARCH TOPICS</b>\n"
        f"🕒 <b>Date & Time:</b> {ist_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    body = "".join(f"<b>{i}.</b> {t}\n\n" for i, t in enumerate(top_5_topics[:5], 1))
    footer = "━━━━━━━━━━━━━━━━━━━━\n💡 <i>Tip: 'Exact Student Search' ko apne YouTube Title aur Tags me zaroor dalna!</i>"

    send_telegram_message(header + body + footer)
    state["history"] = history

def main():
    if not BOT_TOKEN or not CHAT_ID:
        print("Missing BOT_TOKEN or CHAT_ID")
        return

    state = load_state()
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"

    if mode == "force":
        generate_and_send_topics(state)
    else:
        if check_for_send_command(state):
            generate_and_send_topics(state)
        else:
            print("No 'send' command received.")

    save_state(state)

if __name__ == "__main__":
    main()
