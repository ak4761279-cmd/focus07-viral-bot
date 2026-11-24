import os
import io
import re
import textwrap
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont
from pytrends.request import TrendReq
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from google.genai import types

# Environment Secrets
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
YT_API_KEY = os.environ.get("YT_API_KEY")
YT_CHANNEL_ID = os.environ.get("YT_CHANNEL_ID", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

IST = timezone(timedelta(hours=5, minutes=30))
TODAY_STR = datetime.now(IST).strftime("%d %b %Y (%A)")


def get_channel_data():
    if YT_CHANNEL_ID.startswith("@"):
        ch_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,contentDetails&forHandle={YT_CHANNEL_ID}&key={YT_API_KEY}"
    else:
        ch_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,contentDetails&id={YT_CHANNEL_ID}&key={YT_API_KEY}"

    ch_res = requests.get(ch_url, timeout=15).json()
    if not ch_res.get("items"):
        return None, []

    channel_info = ch_res["items"][0]
    uploads_playlist = channel_info["contentDetails"]["relatedPlaylists"]["uploads"]

    pl_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId={uploads_playlist}&maxResults=5&key={YT_API_KEY}"
    pl_res = requests.get(pl_url, timeout=15).json()

    video_ids = [item["snippet"]["resourceId"]["videoId"] for item in pl_res.get("items", [])]
    if not video_ids:
        return channel_info, []

    vid_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&id={','.join(video_ids)}&key={YT_API_KEY}"
    vid_res = requests.get(vid_url, timeout=15).json()

    return channel_info, vid_res.get("items", [])


def get_video_transcript(video_id):
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.fetch(video_id, languages=['hi', 'en', 'en-IN'])
        full_text = " ".join([t.text for t in transcript_list])
        return full_text[:3000]
    except Exception:
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['hi', 'en', 'en-IN'])
            full_text = " ".join([t['text'] for t in transcript_list])
            return full_text[:3000]
        except Exception:
            return "Transcript/Captions available nahi hain."


def get_official_notices():
    """Scrape latest headlines/notices from BEU, BCECEB, and SBTE official portals."""
    portals = [
        ("BEU Patna", "https://beu-bih.ac.in"),
        ("BCECEB", "https://bceceboard.bihar.gov.in"),
        ("SBTE Bihar", "https://sbte.bihar.gov.in")
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    collected = []

    for name, url in portals:
        try:
            res = requests.get(url, headers=headers, timeout=12, verify=False)
            soup = BeautifulSoup(res.text, "html.parser")
            links = []
            for a in soup.find_all("a"):
                txt = " ".join(a.get_text().split())
                if len(txt) > 18 and any(k in txt.lower() for k in [
                    "notice", "exam", "result", "admit", "form", "registration",
                    "schedule", "counselling", "mop", "spot", "semester", "2026", "date"
                ]):
                    if txt not in links:
                        links.append(txt[:110])
                if len(links) >= 3:
                    break
            if links:
                collected.append(f"[{name}]: " + " | ".join(links))
            else:
                collected.append(f"[{name}]: Portal reachable, no new keyword notice.")
        except Exception:
            collected.append(f"[{name}]: Server slow/down today.")

    return "\n".join(collected)


def get_realtime_trends():
    keywords = ["Bihar Engineering", "Bihar Polytechnic", "Bihar Paramedical", "BCECE", "JEE Mains"]
    trends_summary = []
    try:
        pytrends = TrendReq(hl='en-IN', tz=330, timeout=(10, 25))
        pytrends.build_payload(keywords, cat=0, timeframe='now 7-d', geo='IN')
        related = pytrends.related_queries()
        for kw in keywords:
            if kw in related and related[kw]['rising'] is not None:
                top_rising = related[kw]['rising']['query'].head(3).tolist()
                trends_summary.append(f"{kw}: {', '.join(top_rising)}")
    except Exception as e:
        trends_summary.append(f"Trends fallback active ({str(e)[:40]})")

    return "\n".join(trends_summary) if trends_summary else "Ongoing BEU/BCECE/DCECE exam & counselling cycle."


def get_working_models(client):
    candidates = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.0-flash", "gemini-2.5-flash", "gemini-2.0-flash"]
    try:
        for m in client.models.list():
            name = getattr(m, "name", "")
            if "flash" in name and "lite" not in name and "8b" not in name and "image" not in name:
                clean_name = name.replace("models/", "")
                if clean_name not in candidates:
                    candidates.insert(0, clean_name)
    except Exception:
        pass
    return candidates


def generate_coach_report(client, channel_info, videos, transcript, trends_text, notices_text):
    subs = channel_info["statistics"].get("subscriberCount", "Hidden")
    total_views = channel_info["statistics"].get("viewCount", "0")

    video_lines = []
    for i, v in enumerate(videos, 1):
        title = v["snippet"]["title"]
        views = v["statistics"].get("viewCount", "0")
        likes = v["statistics"].get("likeCount", "0")
        comments = v["statistics"].get("commentCount", "0")
        pub = v["snippet"]["publishedAt"][:10]
        video_lines.append(f"{i}. [{pub}] '{title}' -> {views} views, {likes} likes, {comments} comments")

    latest_vid = videos[0]
    thumbs = latest_vid["snippet"]["thumbnails"]
    thumb_url = thumbs.get("maxres", thumbs.get("high", thumbs.get("default")))["url"]
    img_bytes = requests.get(thumb_url, timeout=15).content
    thumb_image = Image.open(io.BytesIO(img_bytes))

    prompt = f"""
Tum YouTube Growth Coach ho Shivam ke channel 'Focus 07' (Bihar Engineering University BEU, BCECE, DCECE, Polytechnic, Paramedical updates) ke liye.
Aaj ki date hai: {TODAY_STR}.

CHANNEL DATA:
- Subscribers: {subs} | Total Views: {total_views}
- Recent 5 Videos:
{chr(10).join(video_lines)}

LATEST VIDEO TRANSCRIPT:
{transcript}

OFFICIAL WEBSITE LIVE NOTICES (BEU / BCECEB / SBTE):
{notices_text}

GOOGLE REAL-TIME RISING TRENDS (India):
{trends_text}

TUMHARA KAAM (Hinglish mein, clean plain text with emojis aur bullet points — bilkul bhi HTML tags ya markdown ** # use mat karna):

1. 🏛️ LIVE OFFICIAL NOTICE RADAR ({TODAY_STR}):
BEU, BCECEB aur SBTE websites ke taज़ा notices ka short update aur kis par turant video banana chahiye.

2. 📊 CHANNEL SNAPSHOT & THUMBNAIL AUDIT:
Subscribers, views aur attached thumbnail/transcript mein kya sudhaar karein (2-3 crisp points).

3. 🔥 AAJ KE 5 VIRAL VIDEO TOPICS ({TODAY_STR}):
Har topic ke liye EXACT isi format mein likho:
Topic 1: [Topic Name]
Clickable Title: [High-CTR Hinglish Title]
Thumbnail Text: [EXACT 3-4 CAPITAL ENGLISH/HINGLISH WORDS]
Kyun chalega: [1 line reason]

(Isi tarah Topic 2, Topic 3, Topic 4, Topic 5 likho)

4. 🚀 READY-TO-PASTE SEO PACK (Topic 1 & Topic 2 ke liye):
- Topic 1 Description (3-4 lines with hashtags #BEU #Focus07 #BiharEngineering)
- Topic 1 Viral Tags (comma-separated 12 keywords)
- Topic 1 Pinned Comment (Telegram & Study Notes portal call-to-action ke saath)
- Topic 2 Description, Viral Tags & Pinned Comment
"""

    last_err = ""
    for model_name in get_working_models(client):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[thumb_image, prompt]
            )
            return response.text
        except Exception as e:
            last_err = str(e)
            continue

    raise RuntimeError(f"Gemini model error: {last_err}")


def create_thumbnails_batch(client, report_text):
    """Generate up to 3 1280x720 YouTube thumbnails with optional shivam.png cutout on the right."""
    thumb_matches = re.findall(r"Thumbnail Text:\s*(.+)", report_text, re.IGNORECASE)
    title_matches = re.findall(r"Clickable Title:\s*(.+)", report_text, re.IGNORECASE)

    if not thumb_matches:
        thumb_matches = ["BEU BIG UPDATE 2026!"]
    if not title_matches:
        title_matches = ["Bihar Engineering University Latest Update"]

    # Check if user uploaded transparent cutout 'shivam.png' in repo root
    cutout_img = None
    if os.path.exists("shivam.png"):
        try:
            raw_cutout = Image.open("shivam.png").convert("RGBA")
            target_h = 640
            aspect = raw_cutout.width / raw_cutout.height
            target_w = min(520, int(target_h * aspect))
            cutout_img = raw_cutout.resize((target_w, target_h), Image.LANCZOS)
        except Exception:
            cutout_img = None

    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    ]
    font_path = next((p for p in font_paths if os.path.exists(p)), None)
    badge_font = ImageFont.truetype(font_path, 36) if font_path else ImageFont.load_default()
    main_font = ImageFont.truetype(font_path, 76 if cutout_img else 86) if font_path else ImageFont.load_default()
    sub_font = ImageFont.truetype(font_path, 34) if font_path else ImageFont.load_default()

    themes = [
        ((14, 22, 48), (225, 25, 25), (255, 220, 0)),   # Navy + Red + Yellow
        ((32, 12, 42), (255, 95, 0), (0, 245, 212)),    # Dark Purple + Orange + Cyan
        ((15, 34, 26), (220, 38, 38), (255, 230, 50))   # Deep Emerald + Red + Gold
    ]

    generated_thumbs = []
    for idx in range(min(3, len(thumb_matches))):
        banner_text = re.sub(r'[^\w\s!?&/-]', '', thumb_matches[idx]).upper()[:36]
        topic_context = title_matches[idx] if idx < len(title_matches) else "BEU Bihar Update"
        base_rgb, badge_rgb, highlight_rgb = themes[idx % len(themes)]

        bg_img = None
        if idx == 0:
            # Generate AI studio background for #1 top topic
            try:
                img_prompt = (
                    f"Dramatic YouTube thumbnail background for Indian engineering college news: {topic_context}. "
                    "Dark moody studio lighting, glowing red and blue rim light, university campus silhouette, "
                    "no text, no words, no letters, 16:9 widescreen."
                )
                res = client.models.generate_images(
                    model="imagen-3.0-generate-002",
                    prompt=img_prompt,
                    config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="16:9")
                )
                if res.generated_images:
                    raw_bytes = res.generated_images[0].image.image_bytes
                    bg_img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA").resize((1280, 720))
            except Exception:
                bg_img = None

        if bg_img is None:
            bg_img = Image.new("RGBA", (1280, 720), (*base_rgb, 255))
            draw_bg = ImageDraw.Draw(bg_img)
            for y in range(720):
                factor = y / 720
                r = min(255, int(base_rgb[0] + factor * 40))
                g = min(255, int(base_rgb[1] + factor * 25))
                b = min(255, int(base_rgb[2] + factor * 55))
                draw_bg.line([(0, y), (1280, y)], fill=(r, g, b, 255))
            draw_bg.rectangle([0, 0, 1280, 18], fill=(*badge_rgb, 255))
            draw_bg.rectangle([0, 702, 1280, 720], fill=(*highlight_rgb, 255))

        overlay = Image.new("RGBA", (1280, 720), (0, 0, 0, 105))
        canvas = Image.alpha_composite(bg_img, overlay)

        # Paste Shivam's cutout on the right side if available
        if cutout_img is not None:
            x_pos = 1280 - cutout_img.width - 20
            y_pos = 720 - cutout_img.height
            canvas.alpha_composite(cutout_img, (x_pos, y_pos))

        draw = ImageDraw.Draw(canvas)

        # Top Breaking Badge
        draw.rounded_rectangle([55, 50, 510, 118], radius=12, fill=(*badge_rgb, 255))
        draw.text((78, 65), f"FOCUS 07 • TOPIC #{idx + 1}", font=badge_font, fill=(255, 255, 255, 255))

        # Wrap headline narrower if cutout is on right
        wrap_width = 14 if cutout_img else 19
        lines = textwrap.wrap(banner_text, width=wrap_width)[:3]
        y_cursor = 175
        for l_idx, line in enumerate(lines):
            t_color = (*highlight_rgb, 255) if l_idx % 2 == 0 else (255, 255, 255, 255)
            draw.text((61, y_cursor + 5), line, font=main_font, fill=(0, 0, 0, 240))
            draw.text((55, y_cursor), line, font=main_font, fill=t_color)
            y_cursor += 105

        # Bottom Strip
        strip_right = 740 if cutout_img else 1220
        draw.rounded_rectangle([55, 585, strip_right, 655], radius=12, fill=(*highlight_rgb, 255))
        strip_label = "BEU • BCECE • SBTE UPDATE" if cutout_img else "BEU • BCECE • POLYTECHNIC OFFICIAL UPDATE"
        draw.text((75, 603), strip_label, font=sub_font, fill=(15, 15, 15, 255))

        buf = io.BytesIO()
        canvas.convert("RGB").save(buf, format="JPEG", quality=92)
        buf.seek(0)
        generated_thumbs.append((buf, banner_text, idx + 1))

    return generated_thumbs


def send_telegram_message(text):
    clean_text = re.sub(r'<[^>]+>', '', text).replace('**', '').replace('##', '')
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    paragraphs = clean_text.split('\n\n')
    current_chunk = ""
    for p in paragraphs:
        if len(current_chunk) + len(p) + 2 < 3800:
            current_chunk += p + "\n\n"
        else:
            if current_chunk.strip():
                requests.post(url, json={"chat_id": CHAT_ID, "text": current_chunk.strip(), "disable_web_page_preview": True}, timeout=15)
            current_chunk = p + "\n\n"
    if current_chunk.strip():
        requests.post(url, json={"chat_id": CHAT_ID, "text": current_chunk.strip(), "disable_web_page_preview": True}, timeout=15)


def send_telegram_photo(image_buf, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("focus07_thumb.jpg", image_buf, "image/jpeg")}
    data = {"chat_id": CHAT_ID, "caption": caption}
    requests.post(url, data=data, files=files, timeout=25)


if __name__ == "__main__":
    channel_info, videos = get_channel_data()
    if not channel_info or not videos:
        send_telegram_message("⚠️ Focus 07 Bot Alert: YouTube channel data fetch nahi ho paya.")
    else:
        client = genai.Client(api_key=GEMINI_API_KEY)
        transcript = get_video_transcript(videos[0]["id"])
        trends_text = get_realtime_trends()
        notices_text = get_official_notices()

        report = generate_coach_report(client, channel_info, videos, transcript, trends_text, notices_text)
        send_telegram_message(report)

        thumbs = create_thumbnails_batch(client, report)
        for buf, b_text, num in thumbs:
            send_telegram_photo(buf, f"🖼️ Topic #{num} Thumbnail (1280x720)\n📌 {b_text}")

