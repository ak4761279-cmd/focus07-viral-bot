import os
import re
import io
import json
import time
import base64
import requests
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timezone, timedelta

TG_TOKEN = (os.getenv("TG_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
TG_CHAT = (os.getenv("TG_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
FORCE = os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch" or os.getenv("FORCE") == "1"

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
MEM_FILE = "competitor_memory.json"
OUT_DIR = "generated_thumbnails"

CHANNELS = [
    {"name": "EASYPREP SEMESTER", "url": "https://www.youtube.com/@easyprepsemester"},
    {"name": "EzyKnot Careers", "url": "https://www.youtube.com/@ezyknotcareers"},
]

SEED_VIDEOS = [
    {
        "channel": "EASYPREP SEMESTER",
        "video_id": "HQ_6SMrE13I",
        "url": "https://www.youtube.com/watch?v=HQ_6SMrE13I",
        "title": "B.Tech 5th Semester | कैसे होगा इतने कम समय में Syllabus | Academic Schedule | BEU Patna #beu",
        "published_at": "2026-11-26",
        "flaws": [
            "Official schedule aaye bina sirf tentative ~80-day estimate aur aakhir me paid batch pitch.",
            "Likes-to-views engagement kam; subject priority aur PYQ breakdown missing."
        ],
        "predicted_next": ["5th sem subject priority", "PYQ / VVI revision", "paid batch push"],
        "beat_topic": "BEU 5th Sem Late Start (~80 Days): Kaunse Subjects Pehle Karein & Fast PYQ Plan | Focus 07",
        "thumb_text": "80 DAYS 5TH SEM PLAN",
        "beat_angle": "Unke tentative calendar aur course pitch se aage badhkar exact subject priority, PYQ weightage, aur CGPA plan do."
    },
    {
        "channel": "EzyKnot Careers",
        "video_id": "eTAH0OyJSMI",
        "url": "https://www.youtube.com/watch?v=eTAH0OyJSMI",
        "title": "BEU B.Tech 1st Semester End Semester Exam Kab Hoga? | BEU Latest Update | Exam Date, Mid Sem, Form",
        "published_at": "2026-11-26",
        "flaws": [
            "12m 39s me naya exam-date update kam aur purani baaton / app & channel promotion ka repetition zyada.",
            "PYQs/solutions abhi pending hain; students ko turant ready sample questions nahi diye."
        ],
        "predicted_next": ["credit counting & subject priority", "1st sem VVI/PYQ videos", "answer writing"],
        "beat_topic": "BEU 1st Sem Exam Pattern & Credit Priority | 24 Pass Rule + 10 MCQ Trick in 8 Mins | Focus 07",
        "thumb_text": "24 PASS + 10 MCQ TRICK",
        "beat_angle": "12+ min ki repetition ke bajay 8-min crisp breakdown + credit/subject priority + instant PYQ/notes funnel do."
    },
    {
        "channel": "EzyKnot Careers",
        "video_id": "M0Wcz1fz9Pw",
        "url": "https://www.youtube.com/watch?v=M0Wcz1fz9Pw",
        "title": "EGD 1st Semester Exam Preparation| Engineering Graphics and Design Important Question BEU #beupatna",
        "published_at": "2026-11-20",
        "flaws": [
            "Drawing/projection questions ko live solve karne ke bajay sirf oral list aur screenshot par chhod diya."
        ],
        "predicted_next": ["other 1st sem subjects VVI", "exam day tips"],
        "beat_topic": "BEU 1st Sem EGD / High-Weightage Topics: Step-by-Step Clarity & Topper Sheet Tips | Focus 07",
        "thumb_text": "EGD VVI + SHEET TRICK",
        "beat_angle": "Sirf screenshot bolne ke bajay clean step-by-step approach aur exam-sheet mistakes se bachne ka shortcut do."
    },
]

TOPIC_CUES = [
    ("credit / subject priority", ["credit", "क्रेडिट", "किस सब्जेक्ट", "priority", "tough subject"]),
    ("important / VVI / PYQ questions", ["important question", "vvi", "pyq", "previous year", "इंपॉर्टेंट क्वेश्चन"]),
    ("viva / practical exam", ["viva", "वाइवा", "practical", "प्रैक्टिकल", "lab"]),
    ("exam schedule / form / center", ["exam date", "schedule", "form", "center", "सेंटर", "शेड्यूल"]),
    ("copy writing / MCQ / passing marks", ["copy", "mcq", "passing", "24", "marks", "सीजीपीए", "cgpa"]),
    ("marathon / master class / revision", ["marathon", "मैराथन", "master class", "मास्टर क्लास", "last minute", "booster"]),
]


def load_mem():
    if os.path.exists(MEM_FILE):
        try:
            with open(MEM_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("version") == 5:
                    return data
        except Exception:
            pass
    return {"version": 5, "seen_ids": [], "last_sent_date": ""}


def save_mem(mem):
    with open(MEM_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)


def tg_send(text):
    if not TG_TOKEN or not TG_CHAT:
        print(text)
        return False
    for i in range(0, len(text), 3800):
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text[i:i + 3800], "disable_web_page_preview": True},
            timeout=25,
        )
        if not r.ok:
            print("TG error:", r.status_code, r.text)
            return False
    return True


def tg_send_photo(img_bytes, caption):
    if not TG_TOKEN or not TG_CHAT:
        print("Photo ready:", caption)
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
        data={"chat_id": TG_CHAT, "caption": caption[:1000]},
        files={"photo": ("focus07_thumbnail.png", io.BytesIO(img_bytes), "image/png")},
        timeout=45,
    )
    if not r.ok:
        print("TG photo error:", r.status_code, r.text)
        return False
    return True


def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text


def download_ref_thumbnail(vid):
    for suffix in ["maxresdefault.jpg", "sddefault.jpg", "hqdefault.jpg"]:
        try:
            r = requests.get(f"https://i.ytimg.com/vi/{vid}/{suffix}", timeout=15)
            if r.ok and len(r.content) > 4000:
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                w, h = img.size
                if h > 0 and abs((w / h) - (16 / 9)) > 0.15:
                    target_h = int(w * 9 / 16)
                    if target_h < h:
                        top = (h - target_h) // 2
                        img = img.crop((0, top, w, top + target_h))
                return img
        except Exception:
            continue
    return None


def generate_better_thumbnail(item, ref_img):
    thumb_txt = item.get("thumb_text", "FOCUS 07 EXAM PLAN")
    title = item.get("title", "")

    if OPENAI_API_KEY:
        prompt = (
            f"Create a high-CTR 16:9 YouTube thumbnail for Bihar Engineering University (BEU) students "
            f"on the 'Focus 07' channel. Improve upon competitor video '{title}' with a bold dark navy "
            f"& electric blue background, glowing yellow and red highlight badges, clean exam checklist/scorecard "
            f"graphics, and huge crisp mobile-readable text: '{thumb_txt}' and 'FOCUS 07'. "
            f"No watermarks, no small clutter."
        )
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        for model_name, size_val in [("gpt-image-1", "1536x1024"), ("dall-e-3", "1792x1024")]:
            try:
                r = requests.post(
                    "https://api.openai.com/v1/images/generations",
                    headers=headers,
                    json={"model": model_name, "prompt": prompt, "size": size_val, "n": 1},
                    timeout=75,
                )
                if not r.ok:
                    continue
                data0 = (r.json().get("data") or [{}])[0]
                if data0.get("b64_json"):
                    return Image.open(io.BytesIO(base64.b64decode(data0["b64_json"]))).convert("RGB"), "OpenAI API"
                if data0.get("url"):
                    ir = requests.get(data0["url"], timeout=30)
                    if ir.ok:
                        return Image.open(io.BytesIO(ir.content)).convert("RGB"), "OpenAI API"
            except Exception:
                continue

    W, H = 1280, 720
    canvas = Image.new("RGB", (W, H), (10, 18, 42))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, W, 18], fill=(255, 193, 7))
    draw.rectangle([0, H - 18, W, H], fill=(239, 68, 68))

    if ref_img is not None:
        side = ref_img.resize((420, 236))
        draw.rounded_rectangle([815, 195, 1245, 441], radius=16, fill=(25, 39, 82), outline=(255, 193, 7), width=3)
        canvas.paste(side, (820, 200))
        draw.text((825, 452), "COMPETITOR REF", fill=(255, 193, 7))

    font = ImageFont.load_default()
    draw.rounded_rectangle([55, 70, 310, 125], radius=10, fill=(239, 68, 68))
    draw.text((75, 88), "🔥 FOCUS 07 UPGRADE", fill=(255, 255, 255), font=font)
    draw.text((60, 190), thumb_txt, fill=(255, 214, 10), font=font)
    draw.text((60, 265), f"BEAT: {item.get('channel', '')[:38]}", fill=(255, 255, 255), font=font)
    draw.text((60, 335), f"IDEA: {item.get('beat_topic', '')[:58]}", fill=(147, 197, 253), font=font)
    return canvas, "Local Fallback"


def deep_analyze_fetched(vid, url, fallback_ch="Competitor"):
    title = vid
    channel = fallback_ch
    pub = NOW_IST.strftime("%Y-%m-%d")
    views = ""
    desc = ""

    try:
        html = fetch_html(url)
        mt = re.search(r'"title":"([^"]+)"', html)
        if mt:
            title = json.loads(f'"{mt.group(1)}"')
        mc = re.search(r'"ownerChannelName":"([^"]+)"', html)
        if mc:
            channel = json.loads(f'"{mc.group(1)}"')
        mp = re.search(r'"publishDate":"([^"]+)"', html)
        if mp:
            pub = mp.group(1)[:10]
        md = re.search(r'"shortDescription":"((?:\\.|[^"\\])*)"', html)
        if md:
            desc = json.loads(f'"{md.group(1)}"')
        mv = re.search(r'"viewCount":"(\d+)"', html)
        if mv:
            views = f"{int(mv.group(1)):,}"
    except Exception:
        pass

    low = f"{title}\n{desc}".lower()
    flaws = []
    if len(desc) < 120:
        flaws.append("Description kaafi short hai; SEO & direct resource links kamzor hain.")
    if "app" in low or "batch" in low or "course" in low:
        flaws.append("Paid app/batch ka pitch zyada hai; free actionable takeaways kam ho sakte hain.")
    if "comment" in low and ("question" in low or "topic" in low):
        flaws.append("Topic/PYQ deliver karne ke bajay pehle comments mangwaye ja rahe hain.")
    if not flaws:
        flaws.append("Lamba format/intro hone par retention gir sakta hai.")

    predicted = []
    for label, kws in TOPIC_CUES:
        if any(k in low for k in kws):
            predicted.append(label)
    if not predicted:
        predicted.append("semester exam / PYQ / update")

    beat_topic = f"BEU Latest: {title[:55].strip()} | Fast Notes & Strategy | Focus 07"
    thumb_text = "BEU FAST TRACK"
    if "5th" in low or "syllabus" in low:
        beat_topic = "BEU 5th Sem Short Timeline: Subject Priority & PYQ Strategy | Focus 07"
        thumb_text = "5TH SEM FAST PLAN"
    elif "1st" in low or "exam" in low or "egd" in low:
        beat_topic = "BEU 1st Sem Exam & High-Weightage Topics: Crisp Score Plan | Focus 07"
        thumb_text = "1ST SEM SCORE HACK"

    return {
        "channel": channel,
        "video_id": vid,
        "url": url,
        "title": title,
        "published_at": pub,
        "views": views,
        "flaws": flaws,
        "predicted_next": predicted[:4],
        "beat_topic": beat_topic,
        "thumb_text": thumb_text,
        "beat_angle": "Unse kam intro, zyada crisp step-by-step clarity, aur seedha Telegram/notes value do.",
    }


def discover_live_videos(seen_ids):
    known = {v["video_id"] for v in SEED_VIDEOS}
    extra_urls = [u.strip() for u in os.getenv("COMPETITOR_URLS", "").split(",") if u.strip()]
    targets = [c["url"] for c in CHANNELS] + extra_urls

    new_items = []
    for ch_url in targets:
        try:
            html = fetch_html(ch_url)
            vids = list(dict.fromkeys(re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)))
            for vid in vids[:3]:
                if vid in known or vid in seen_ids:
                    continue
                known.add(vid)
                v_url = f"https://www.youtube.com/watch?v={vid}"
                info = deep_analyze_fetched(vid, v_url)
                new_items.append(info)
                time.sleep(0.4)
        except Exception:
            continue
    return new_items


def run():
    mem = load_mem()
    seen = set(mem.get("seen_ids", []))
    os.makedirs(OUT_DIR, exist_ok=True)

    new_items = discover_live_videos(seen)
    report_items = new_items + SEED_VIDEOS

    lines = [f"🚨 FOCUS 07 DEEP COMPETITOR & GADBAD REPORT ({NOW_IST.strftime('%d %b %Y, %I:%M %p IST')})"]

    if new_items:
        lines.append("\n🆕 NAYA VIDEO PACKDA GAYA:")
        for ni in new_items:
            lines.append(f"• [{ni['channel']}] {ni['title']} ({ni['published_at']})")
            seen.add(ni["video_id"])

    for item in report_items[:4]:
        v_str = f" | Views: {item['views']}" if item.get("views") else ""
        flaw_block = "\n     ❌ " + "\n     ❌ ".join(item["flaws"])
        lines.append(
            f"\n━━━━━━━━━━━━━━━━━━━━\n"
            f"▶️ {item['channel']} ({item['published_at']}{v_str})\n"
            f"📌 Video: {item['title']}\n"
            f"⚠️ GADBAD REPORT:{flaw_block}\n"
            f"🔮 Agla Kya La Sakte Hain: {', '.join(item['predicted_next'])}\n"
            f"🏆 Beat Topic: {item['beat_topic']}\n"
            f"🎯 Beat Angle: {item['beat_angle']}\n"
            f"🖼️ Thumb Text: {item['thumb_text']}"
        )

    today_str = NOW_IST.strftime("%Y-%m-%d")
    if new_items or FORCE or mem.get("last_sent_date") != today_str:
        if tg_send("\n".join(lines)):
            mem["last_sent_date"] = today_str

        thumb_targets = new_items if new_items else SEED_VIDEOS[:2]
        for item in thumb_targets:
            ref_img = download_ref_thumbnail(item["video_id"])
            gen_img, engine = generate_better_thumbnail(item, ref_img)
            save_path = os.path.join(OUT_DIR, f"{item['video_id']}_focus07.png")
            gen_img.save(save_path, format="PNG")
            buf = io.BytesIO()
            gen_img.save(buf, format="PNG")
            tg_send_photo(
                buf.getvalue(),
                f"🖼️ Focus 07 Thumbnail ({engine})\nRef: {item['channel']} — {item['thumb_text']}",
            )
            time.sleep(1)

    mem["seen_ids"] = list(seen)[-100:]
    save_mem(mem)


if __name__ == "__main__":
    run()
