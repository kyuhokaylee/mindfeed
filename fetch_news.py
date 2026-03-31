import json, os, re, hashlib, time
from datetime import datetime, timezone
import feedparser
import requests

RSS_FEEDS = [
    {"name": "PsyPost", "url": "https://www.psypost.org/feed", "tag": "psych", "tagLabel": "심리학 / Psychology"},
    {"name": "BPS Research Digest", "url": "https://digest.bps.org.uk/feed/", "tag": "psych", "tagLabel": "심리학 / Psychology"},
    {"name": "arXiv – cs.AI", "url": "https://rss.arxiv.org/rss/cs.AI", "tag": "ai", "tagLabel": "AI 연구 / AI Research"},
    {"name": "arXiv – q-bio.NC", "url": "https://rss.arxiv.org/rss/q-bio.NC", "tag": "neuro", "tagLabel": "신경과학 / Neuroscience"},
    {"name": "Behavioral Scientist", "url": "https://behavioralscientist.org/feed/", "tag": "behav", "tagLabel": "행동과학 / Behavioral Science"},
    {"name": "ScienceDaily Mind", "url": "https://www.sciencedaily.com/rss/mind_brain.xml", "tag": "neuro", "tagLabel": "신경과학 / Neuroscience"},
]

MAX_ARTICLES = 20
MAX_PER_FEED = 4
MAX_NEW_SUMMARIZE = 6

def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text)
    for pat, rep in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&nbsp;"," ")]:
        text = text.replace(pat, rep)
    return re.sub(r"\s+", " ", text).strip()

def relative_time(dt):
    diff = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    h = int(diff.total_seconds() // 3600)
    if h < 1: return "방금 전 / Just now"
    if h < 24: return f"{h}시간 전 / {h}h ago"
    return f"{h//24}일 전 / {h//24}d ago"

def call_claude(prompt, api_key, max_tokens=1200):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"Content-Type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"},
        json={"model":"claude-haiku-4-5","max_tokens":max_tokens,"messages":[{"role":"user","content":prompt}]},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()

def generate_summary(article, api_key):
    prompt = f"""다음 뉴스를 아래 형식으로 작성하세요.

[한국어 요약]
6문장: 연구 배경, 방법, 결과(수치 포함), 의의, 한계.

[English Summary]
6 sentences: background, method, findings, significance, limitations.

[핵심 포인트]
- 포인트1 / Point 1
- 포인트2 / Point 2
- 포인트3 / Point 3
- 포인트4 / Point 4

제목: {article['title']}
내용: {article['summary']}"""
    try:
        resp = call_claude(prompt, api_key)
        ko = re.search(r'\[한국어 요약\]\s*([\s\S]*?)(?=\[English Summary\])', resp)
        en = re.search(r'\[English Summary\]\s*([\s\S]*?)(?=\[핵심 포인트\])', resp)
        kp = re.search(r'\[핵심 포인트\]\s*([\s\S]*?)$', resp)
        article['aiSummaryKo'] = ko.group(1).strip() if ko else ''
        article['aiSummaryEn'] = en.group(1).strip() if en else ''
        article['aiSummary'] = article['aiSummaryEn'] or article['summary']
        article['keyPoints'] = [p.strip() for p in re.findall(r'-\s*(.+)', kp.group(1))][:4] if kp else []
        if article['aiSummaryKo']:
            article['titleKo'] = call_claude(f"영어 제목을 한국어로 번역하세요. 번역문만 출력.\n\n{article['title']}", api_key, 100)
        print(f"    OK: {article['aiSummaryKo'][:40]}...")
    except Exception as e:
        print(f"    FAIL: {e}")
        article['aiSummaryKo'] = ''
        article['aiSummaryEn'] = article['summary']
        article['aiSummary'] = article['summary']
        article['keyPoints'] = []
    return article

def fetch_feed(feed_info, existing_ids):
    try:
        parsed = feedparser.parse(feed_info["url"])
        articles = []
        for entry in parsed.entries[:MAX_PER_FEED]:
            title = strip_html(entry.get("title","")).strip()
            link = entry.get("link","").strip()
            summary = strip_html(entry.get("summary", entry.get("description",""))).strip()
            if not title or not link: continue
            art_id = hashlib.md5(link.encode()).hexdigest()[:12]
            if art_id in existing_ids: continue
            try:
                from email.utils import parsedate_to_datetime
                time_str = relative_time(parsedate_to_datetime(entry.get("published","")))
            except:
                time_str = "최근 / Recent"
            articles.append({
                "id":art_id,"tag":feed_info["tag"],"tagLabel":feed_info["tagLabel"],
                "source":feed_info["name"],"time":time_str,
                "title":title,"titleKo":"","summary":summary[:600],
                "aiSummary":"","aiSummaryKo":"","aiSummaryEn":"",
                "keyPoints":[],"url":link,"featured":False,
            })
        return articles
    except Exception as e:
        print(f"  WARN {feed_info['name']}: {e}")
        return []

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY","")
    print(f"API키: {'있음 (' + api_key[:8] + '...)' if api_key else '없음 !!!'}")

    existing_articles, existing_ids = [], set()
    if os.path.exists("news.json"):
        try:
            with open("news.json","r",encoding="utf-8") as f:
                old = json.load(f)
            existing_articles = old.get("articles",[])
            existing_ids = {a["id"] for a in existing_articles}
            print(f"기존 {len(existing_articles)}개 로드")
        except: pass

    all_new = []
    for feed in RSS_FEEDS:
        print(f"수집: {feed['name']}")
        new = fetch_feed(feed, existing_ids)
        print(f"  신규 {len(new)}개")
        all_new.extend(new)

    print(f"총 신규: {len(all_new)}개")

    to_sum = all_new[:MAX_NEW_SUMMARIZE]
    if api_key and to_sum:
        print(f"Claude API 요약 ({len(to_sum)}개)...")
        for i, a in enumerate(to_sum):
            print(f"  [{i+1}/{len(to_sum)}] {a['title'][:50]}")
            to_sum[i] = generate_summary(a, api_key)
            time.sleep(0.5)
    else:
        print(f"요약 스킵 (API키없음={not api_key}, 신규없음={not to_sum})")

    all_articles = (to_sum + all_new[MAX_NEW_SUMMARIZE:] + existing_articles)[:MAX_ARTICLES]
    for i,a in enumerate(all_articles):
        a["featured"] = (i==0)

    with open("news.json","w",encoding="utf-8") as f:
        json.dump({"updated":datetime.now(timezone.utc).isoformat(),"total":len(all_articles),"articles":all_articles},f,ensure_ascii=False,indent=2)
    print(f"완료: {len(all_articles)}개")

if __name__ == "__main__":
    main()
