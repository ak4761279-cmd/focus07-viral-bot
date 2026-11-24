import os
import io
import requests
from datetime import datetime, timezone, timedelta
from PIL import Image
from pytrends.request import TrendReq
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai

# Environment Secrets
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
YT_API_KEY = os.environ.get("YT_API_KEY")
YT_CHANNEL_ID = os.environ.get("YT_CHANNEL_ID", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

IST = timezone(timedelta(hours=5, minutes=30))
TODAY_STR = datetime.now(IST).strftime("%d %b %Y (%A)")


def get_channel_data():
    """Fetch channel stats and latest 5 videos using either @handle or UC... Channel ID."""
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
    """Fetch spoken Hindi/English transcript of the latest video."""
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
            return "Transcript/Captions available nahi hain (Auto-captions off ya audio unclear ho sakta hai)."


def get_realtime_trends():
    """Fetch real-time rising searches in India for Focus 07 niche."""
    keywords = [
        "Bihar Engineering",
        "Bihar Polytechnic",
        "Bihar Paramedical",
        "BCECE",
        "JEE Mains"
    ]
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

    return "\n".join(trends_summary) if trends_summary else "No sudden spike; focus on ongoing BEU/BCECE/DCECE exam & counselling cycle."


def get_working_models(client):
    """Auto-discover available Gemini Flash models from API so 404 never happens."""
    candidates = [
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-3.0-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash"
    ]
    try:
        for m in client.models.list():
            name = getattr(m, "name", "")
            if "flash" in name and "lite" not in name and "8b" not in name:
                clean_name = name.replace("models/", "")
                if clean_name not in candidates:
                    candidates.insert(0, clean_name)
    except Exception:
        pass
    return candidates


def generate_coach_report(channel_info, videos, transcript, trends_text):
    """Send channel stats, thumbnail image, transcript, and trends to Gemini."""
    client = genai.Client(api_key=GEMINI_API_KEY)

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

LATEST VIDEO TRANSCRIPT (Spoken Content):
{transcript}

GOOGLE REAL-TIME RISING TRENDS (India):
{trends_text}

TUMHARA KAAM (Hinglish mein, seedha aur actionable, Telegram HTML format mein sirf <b> aur <i> tags use karke, koi markdown ** ya # nahi):
1. <b>📊 CHANNEL SNAPSHOT</b>: Subscribers, total views aur recent 5 videos ka short performance review.
2. <b>🖼️ THUMBNAIL & HOOK AUDIT</b>: Attached latest thumbnail image aur spoken transcript ke base par batao kya visual ya opening hook weak hai aur exact kya sudhaar karein.
3. <b>⚠️ KAMIYA (ACTIONABLE FIXES)</b>: Recent 5 videos mein CTR, title, ya topic selection ki 3 concrete kamiya aur unka fix.
4. <b>🔥 AAJ KE 5 VIRAL VIDEO TOPICS ({TODAY_STR})</b>: Bihar Engineering, Polytechnic, BCECE/DCECE students ke liye 5 high-demand video ideas, har ek ke liye:
   - Clickable Hinglish Title
   - Thumbnail Text (3-4 words)
   - Kyun chalega (1 line)
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


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunks = [text[i:i+3900] for i in range(0, len(text), 3900)]
    for chunk in chunks:
        payload = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        res = requests.post(url, json=payload, timeout=15)
        if not res.ok:
            # Fallback without HTML parsing if special characters break tags
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=15)


if __name__ == "__main__":
    channel_info, videos = get_channel_data()
    if not channel_info or not videos:
        send_telegram_message("⚠️ Focus 07 Bot Alert: YouTube channel data fetch nahi ho paya. YT_CHANNEL_ID ya YT_API_KEY check karein.")
    else:
        transcript = get_video_transcript(videos[0]["id"])
        trends_text = get_realtime_trends()
        report = generate_coach_report(channel_info, videos, transcript, trends_text)
        send_telegram_message(report)

