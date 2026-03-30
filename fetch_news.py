#!/usr/bin/env python3
"""
MindFeed 뉴스 수집기 (완전 무료 버전)
- PsyPost, APA, arXiv, BPS RSS 피드에서 최신 심리학/AI 기사를 수집
- AI API 없이 추출적 요약(extractive summarization)으로 자동 요약
- news.json 업데이트
"""
 
import json, os, re, hashlib
from datetime import datetime, timezone
import feedparser
 
RSS_FEEDS = [
    {"name": "PsyPost",               "url": "https://www.psypost.org/feed",                       "tag": "psych", "tagLabel": "심리학 / Psychology"},
    {"name": "BPS Research Digest",   "url": "https://digest.bps.org.uk/feed/",                    "tag": "psych", "tagLabel": "심리학 / Psychology"},
    {"name": "APA News",              "url": "https://www.apa.org/rss/news.xml",                    "tag": "psych", "tagLabel": "심리학 / Psychology"},
    {"name": "arXiv – cs.AI",         "url": "https://rss.arxiv.org/rss/cs.AI",                    "tag": "ai",    "tagLabel": "AI 연구 / AI Research"},
    {"name": "arXiv – cs.LG",         "url": "https://rss.arxiv.org/rss/cs.LG",                    "tag": "ai",    "tagLabel": "AI 연구 / AI Research"},
    {"name": "arXiv – q-bio.NC",      "url": "https://rss.arxiv.org/rss/q-bio.NC",                 "tag": "neuro", "tagLabel": "신경과학 / Neuroscience"},
    {"name": "Behavioral Scientist",  "url": "https://behavioralscientist.org/feed/",               "tag": "behav", "tagLabel": "행동과학 / Behavioral Science"},
    {"name": "ScienceDaily Mind",     "url": "https://www.sciencedaily.com/rss/mind_brain.xml",     "tag": "neuro", "tagLabel": "신경과학 / Neuroscience"},
]
 
MAX_ARTICLES = 20
MAX_PER_FEED = 4
 
def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text)
    for entity, char in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&nbsp;"," "),("&#\d+;","")]:
        text = re.sub(entity, char, text)
    return re.sub(r"\s+", " ", text).strip()
 
def extractive_summary(text, n=3):
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 30]
    if not sentences:
        return text[:400]
    keywords = ["study","research","found","shows","suggests","reveals","participants",
                "results","effect","significant","percent","%","published","journal",
                "scientists","researchers","brain","cognitive","behavior","mental",
                "psychological","neural","AI","model","algorithm","GPT","연구","결과","발견"]
    def score(s):
        return sum(1.5 for kw in keywords if kw.lower() in s.lower())
    scored = sorted(enumerate(sentences), key=lambda x: score(x[1]), reverse=True)
    top = sorted([i for i,_ in scored[:n]])
    return " ".join(sentences[i] for i in top)
 
def extract_key_points(title, summary):
    points = []
    numbers = re.findall(r"\d+(?:\.\d+)?%|\d+\s*(?:participants?|people|patients?)", summary, re.I)
    for n in numbers[:2]:
        sent = next((s for s in re.split(r"[.!?]", summary) if n.split()[0] in s), "")
        if sent: points.append(sent.strip()[:80])
    for pat in [r"(randomized|RCT|meta-analysis|fMRI|survey|experiment|trial)[^.]*\.",
                r"(findings? suggest|results? show|study found|researchers? found)[^.]*\."]:
        m = re.search(pat, summary, re.I)
        if m: points.append(m.group().strip()[:80])
    sents = [s.strip() for s in re.split(r"[.!?]", summary) if len(s.strip()) > 20]
    while len(points) < 4 and sents:
        c = sents.pop(0)[:80]
        if c not in points: points.append(c)
    return points[:4]
 
def relative_time(dt):
    diff = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    h = int(diff.total_seconds() // 3600)
    if h < 1:  return "방금 전 / Just now"
    if h < 24: return f"{h}시간 전 / {h}h ago"
    return f"{h//24}일 전 / {h//24}d ago"
 
def fetch_feed(feed_info, existing_ids):
    try:
        parsed = feedparser.parse(feed_info["url"])
        articles = []
        for entry in parsed.entries[:MAX_PER_FEED]:
            title   = strip_html(entry.get("title","")).strip()
            link    = entry.get("link","").strip()
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
                "id": art_id, "tag": feed_info["tag"], "tagLabel": feed_info["tagLabel"],
                "source": feed_info["name"], "time": time_str,
                "title": title, "summary": summary[:300],
                "aiSummary": extractive_summary(summary),
                "keyPoints": extract_key_points(title, summary),
                "url": link, "featured": False,
            })
        return articles
    except Exception as e:
        print(f"  WARNING {feed_info['name']}: {e}")
        return []
 
def main():
    print("=== MindFeed 뉴스 수집 (무료 버전) ===")
    existing_articles, existing_ids = [], set()
    if os.path.exists("news.json"):
        try:
            with open("news.json","r",encoding="utf-8") as f:
                old = json.load(f)
            existing_articles = old.get("articles", [])
            existing_ids = {a["id"] for a in existing_articles}
            print(f"기존 {len(existing_articles)}개 로드")
        except: pass
 
    all_new = []
    for feed in RSS_FEEDS:
        print(f"수집: {feed['name']}")
        new = fetch_feed(feed, existing_ids)
        print(f"  신규 {len(new)}개")
        all_new.extend(new)
 
    all_articles = (all_new + existing_articles)[:MAX_ARTICLES]
    for i, a in enumerate(all_articles):
        a["featured"] = (i == 0)
 
    with open("news.json","w",encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(),
                   "total": len(all_articles), "articles": all_articles},
                  f, ensure_ascii=False, indent=2)
    print(f"완료: 총 {len(all_articles)}개 (신규 {len(all_new)}개)")
 
if __name__ == "__main__":
    main()
 
