import requests
import json
import os
import time
from datetime import datetime
import xml.etree.ElementTree as ET

# ===================== 설정 =====================
RULIWEB_RSS = "https://bbs.ruliweb.com/family/211/board/300015/rss"
PNEA_RSS = "https://pnea.net/feed/"
DISCORD_WEBHOOK_RULIWEB = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_WEBHOOK_PNEA = os.environ.get("DISCORD_WEBHOOK_URL_PNEA", "")
CHECK_INTERVAL = 300  # 5분마다
SEEN_FILE_RULIWEB = "seen_ruliweb.json"
SEEN_FILE_PNEA = "seen_pnea.json"
# ================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


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
        res = requests.get(url, headers=HEADERS, timeout=10)
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


def send_discord(webhook_url, post, footer):
    embed = {
        "title": post["title"],
        "url": post["link"],
        "color": 0x5865F2,
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


def check(rss_url, webhook_url, seen_file, name, footer):
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
            send_discord(webhook_url, post, footer)
            seen.add(post["id"])
            time.sleep(1)
        save_seen(seen_file, seen)
    else:
        print(f"[{name}] 새 글 없음")


def main():
    print("모니터링 시작!")
    while True:
        now = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{now}] 확인 중...")
        check(RULIWEB_RSS, DISCORD_WEBHOOK_RULIWEB, SEEN_FILE_RULIWEB, "루리웹", "루리웹 애니 정보")
        check(PNEA_RSS, DISCORD_WEBHOOK_PNEA, SEEN_FILE_PNEA, "pnea", "pnea.net")
        print(f"5분 후 다시 확인...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
