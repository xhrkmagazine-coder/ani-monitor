import requests
import json
import os
import time
from datetime import datetime
import xml.etree.ElementTree as ET
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ===================== 설정 =====================
RULIWEB_RSS = "https://bbs.ruliweb.com/family/211/board/300015/rss"
PNEA_RSS = "https://pnea.net/feed/"
ANIMECORNER_RSS = "https://animecorner.me/category/news/anime-news/feed/"
DISCORD_WEBHOOK_RULIWEB = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_WEBHOOK_PNEA = os.environ.get("DISCORD_WEBHOOK_URL_PNEA", "")
DISCORD_WEBHOOK_ANIMECORNER = os.environ.get("DISCORD_WEBHOOK_ANIMECORNER", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DISCORD_WEBHOOK_ANIME = os.environ.get("DISCORD_WEBHOOK_ANIME", "")
CHECK_INTERVAL = 300
SEEN_FILE_RULIWEB = "seen_ruliweb.json"
SEEN_FILE_PNEA = "seen_pnea.json"
SEEN_FILE_ANIMECORNER = "seen_animecorner.json"
# ================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}


def get_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


def load_seen(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(path, seen):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)


def fetch_rss(url):
    try:
        session = get_session()
        res = session.get(url, headers=HEADERS, timeout=30)
        res.raise_for_status()
        content = res.content.decode("utf-8").replace(' xmlns="', ' xmlnsx="')
        root = ET.fromstring(content.encode("utf-8"))
        channel = root.find("channel")
        if channel is None:
            for child in root:
                if "channel" in child.tag:
                    channel = child
                    break
        if channel is None:
            return []

        posts = []
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            author = (item.findtext("author") or "").strip()
            categories = [c.text for c in item.findall("category") if c.text]
            category = ", ".join(categories)
            post_id = link.strip("/").split("/")[-1]
            if not post_id or not title:
                continue
            posts.append({"id": post_id, "title": title, "link": link, "date": pub_date, "author": author, "category": category})
        return posts
    except Exception as e:
        print(f"[오류] RSS 불러오기 실패 ({url}): {e}")
        return []


def send_discord(webhook_url, post, footer, color=0x5865F2):
    embed = {
        "title": post["title"],
        "url": post["link"],
        "color": color,
        "fields": [],
        "footer": {"text": footer},
        "timestamp": datetime.utcnow().isoformat(),
    }
    if post.get("author"):
        embed["fields"].append({"name": "✍️ 작성자", "value": post["author"], "inline": True})
    if post.get("category"):
        embed["fields"].append({"name": "📂 카테고리", "value": post["category"], "inline": True})
    if post.get("date"):
        embed["fields"].append({"name": "🕐 시간", "value": post["date"], "inline": True})
    try:
        res = requests.post(webhook_url, json={"username": "알리미", "embeds": [embed]}, timeout=10)
        if res.status_code in (200, 204):
            print(f"[알림 전송] {post['title']}")
        else:
            print(f"[웹훅 오류] {res.status_code}")
    except Exception as e:
        print(f"[오류] {e}")


def check_rss(rss_url, webhook_url, seen_file, name, footer, color=0x5865F2):
    seen = load_seen(seen_file)
    posts = fetch_rss(rss_url)
    print(f"[{name}] {len(posts)}개 글 읽어옴")

    if not seen:
        seen = {p["id"] for p in posts}
        save_seen(seen_file, seen)
        print(f"[{name}] 초기화 완료")
        return

    new_posts = [p for p in posts if p["id"] not in seen]
    if new_posts:
        print(f"[{name}] 새 글 {len(new_posts)}개!")
        for post in reversed(new_posts):
            send_discord(webhook_url, post, footer, color)
            seen.add(post["id"])
            time.sleep(1)
        save_seen(seen_file, seen)
    else:
        print(f"[{name}] 새 글 없음")


def get_anime_info():
    now = datetime.now()
    next_month = now.month + 1 if now.month < 12 else 1
    next_year = now.year if now.month < 12 else now.year + 1
    month_str = f"{next_year}년 {next_month}월"

    prompt = f"""
당신은 애니메이션 전문가입니다.
{month_str} 방영 예정인 신작 애니메이션 10개를 조사해주세요.
https://animecorner.me 사이트와 트위터(X)의 최신 애니 관련 정보를 참고해주세요.

아래 JSON 형식으로만 답변해주세요. 다른 텍스트는 절대 포함하지 마세요:

{{
  "month": "{month_str}",
  "anime_list": [
    {{
      "rank": 1,
      "title": "애니 제목",
      "title_jp": "일본어 제목",
      "air_date": "방영일 (예: 2025년 4월 5일)",
      "ott": "시청 가능한 OTT (예: 넷플릭스, 라프텔, 애니플러스 등)",
      "description": "한 줄 소개 (흥미롭고 간결하게)"
    }}
  ]
}}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.7}}

    try:
        res = requests.post(url, json=payload, timeout=30)
        res.raise_for_status()
        data = res.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"[오류] Gemini 요청 실패: {e}")
        return None


def send_anime_report(anime_data):
    month = anime_data["month"]
    anime_list = anime_data["anime_list"]

    header = {"username": "덕후의 스케줄 알리미", "content": f"📅 **{month} 덕후의 스케줄** - 이번 달 주목할 신작 애니 10선!"}
    requests.post(DISCORD_WEBHOOK_ANIME, json=header, timeout=10)

    for anime in anime_list:
        embed = {
            "title": f"#{anime['rank']} {anime['title']}",
            "description": f"_{anime.get('title_jp', '')}_",
            "color": 0x5865F2,
            "fields": [
                {"name": "📺 방영일", "value": anime["air_date"], "inline": True},
                {"name": "🎬 OTT", "value": anime["ott"], "inline": True},
                {"name": "📝 한 줄 소개", "value": anime["description"], "inline": False},
            ],
            "footer": {"text": f"{month} 신작 애니 | 덕후의 스케줄"},
        }
        try:
            res = requests.post(DISCORD_WEBHOOK_ANIME, json={"username": "덕후의 스케줄 알리미", "embeds": [embed]}, timeout=10)
            if res.status_code in (200, 204):
                print(f"[전송] {anime['title']}")
        except Exception as e:
            print(f"[오류] {e}")
        time.sleep(1)

    print(f"[완료] {month} 리포트 전송 완료!")


def check_anime_report():
    now = datetime.now()
    if now.day == 28 and now.hour == 9 and now.minute < 5:
        print("[애니 리포트] 생성 시작!")
        anime_data = get_anime_info()
        if anime_data:
            send_anime_report(anime_data)


def main():
    print("모니터링 시작!")
    while True:
        now = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{now}] 확인 중...")
        check_rss(RULIWEB_RSS, DISCORD_WEBHOOK_RULIWEB, SEEN_FILE_RULIWEB, "루리웹", "루리웹 애니 정보", 0x5865F2)
        check_rss(PNEA_RSS, DISCORD_WEBHOOK_PNEA, SEEN_FILE_PNEA, "pnea", "pnea.net", 0xE24B4A)
        check_rss(ANIMECORNER_RSS, DISCORD_WEBHOOK_ANIMECORNER, SEEN_FILE_ANIMECORNER, "애니코너", "Anime Corner", 0x1D9E75)
        check_anime_report()
        print(f"5분 후 다시 확인...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
