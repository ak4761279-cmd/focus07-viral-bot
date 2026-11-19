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
    """Fetch channel stats and latest 5 videos using either @Handle or UC... Channel ID."""
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
        
    return "\n".join(trends_summary) if trends_summary else "No sudden spike data; focus on ongoing admission, counselling, and semester exam updates."

def generate_coach_report(channel_info, videos):
    """Use Gemini Vision + Text to audit latest thumbnail, spoken script, channel SEO, and generate 5 viral topics."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    stats = channel_info.get("statistics", {})
    snippet = channel_info.get("snippet", {})
    
    latest_video = videos[0]
    latest_id = latest_video["id"]
    latest_title = latest_video["snippet"]["title"]
    latest_tags = latest_video["snippet"].get("tags", [])
    latest_views = latest_video["statistics"].get("viewCount", "0")
    
    thumbs = latest_video["snippet"]["thumbnails"]
    thumb_url = thumbs.get("maxres", thumbs.get("high", thumbs.get("default")))["url"]
    img_bytes = requests.get(thumb_url, timeout=15).content
    thumb_image = Image.open(io.BytesIO(img_bytes))
    
    transcript_text = get_video_transcript(latest_id)
    trends_data = get_realtime_trends()
    
    recent_list = "\n".join([
        f"- {v['snippet']['title']} (Views: {v['statistics'].get('viewCount', 0)})"
        for v in videos
    ])

    prompt = f"""
You are the personal YouTube Growth Coach for 'FOCUS-07' (Bihar Engineering, Polytechnic, Paramedical/Nursing & JEE educational channel run by Shivam).
Today's Date: {TODAY_STR}

CHANNEL STATS:
- Subscribers: {stats.get('subscriberCount')}
- Total Views: {stats.get('viewCount')}
- Channel Description: {snippet.get('description', '')[:300]}

RECENT 5 VIDEOS:
{recent_list}

LATEST VIDEO DETAILS:
- Title: {latest_title}
- Views: {latest_views}
- Tags Count: {len(latest_tags)} ({', '.join(latest_tags[:8])})
- Spoken Transcript Snippet: {transcript_text}

REAL-TIME GOOGLE TRENDS (INDIA - LAST 7 DAYS):
{trends_data}

TASK:
Analyze the attached thumbnail image of the latest video along with its spoken transcript, title, tags, and channel stats. Write a crisp, practical, high-impact Telegram report in Hinglish (Hindi + English mix) under 3500 characters using clean HTML bold/italic tags (<b>, <i>) ONLY (no markdown asterisks ** or ##).

Include these 4 sections strictly:
1. 🖼️ <b>LATEST THUMBNAIL AUDIT (10 me se Score)</b>: Text readability on mobile, color contrast, face/emotion/curiosity, aur 2 exact fixes.
2. 🎙️ <b>VIDEO SPEAKING & HOOK AUDIT</b>: Transcript ke base par batao ki shuru ke 30 second ka hook kaisa tha, bolne ki clarity/energy kaisi thi, aur CTA (Subscribe/WhatsApp group) sahi jagah tha ya nahi.
3. ⚠️ <b>CHANNEL & SEO KAMIYA (ACTIONABLE FIXES)</b>: Recent 5 videos aur tags/description dekh kar 3 badi kamiya jo views rok rahi hain.
4. 🔥 <b>AAJ KE 5 VIRAL VIDEO TOPICS ({TODAY_STR})</b>: Bihar Engineering, Polytechnic, Paramedical/Nursing aur JEE students ke liye 5 exact clickable titles + unka 1-line thumbnail text idea.
"""

    for model_name in ["gemini-3.8-flash", "gemini-flash-latest"]:
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
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=15)

if __name__ == "__main__":
    ch_info, vids = get_channel_data()
    if not ch_info or not vids:
        send_telegram_message("⚠️ Focus 07 Bot Alert: YT_CHANNEL_ID ya YT_API_KEY check karein, channel data fetch nahi ho paya.")
    else:
        report = generate_coach_report(ch_info, vids)
        send_telegram_message(report)
