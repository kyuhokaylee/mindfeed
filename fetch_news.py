#!/usr/bin/env python3
"""
MindFeed 뉴스 수집기 (Claude API 번역 버전)
"""

import json, os, re, hashlib, time
from datetime import datetime, timezone
import feedparser
import requests

RSS_FEEDS = [
    {"name": "PsyPost",              "url": "https://www.psypost.org/feed",                    "tag": "psych", "tagLabel": "심리학 / Psychology"},
    {"name": "BPS Research Digest",  "url": "https://digest.bps.org.uk/feed/",                 "tag": "psych", "tagLabel": "심리학 / Psychology"},
    {"name": "APA News",             "url": "https://www.apa.org/rss/news.xml",                 "tag": "psych", "tagLabel": "심리학 / Psychology"},
    {"name": "arXiv – cs.AI",        "url": "https://rss.arxiv.org/rss/cs.AI",                 "tag": "ai",    "tagLabel": "AI 연구 / AI Research"},
    {"name": "arXiv – cs.LG",        "url": "https://rss.arxiv.org/rss/cs.LG",                 "tag": "ai",    "tagLabel": "AI 연구 / AI Research"},
    {"name": "arXiv – q-bio.NC",     "url": "https://rss.arxiv.org/rss/q-bio.NC",              "tag": "neuro", "tagLabel": "신경과학 / Neuroscience"},
    {"name": "Behavioral Scientist", "url": "https://behavioralscientist.org/feed/",            "tag": "behav", "tagLabel": "행동과학 / Behavioral Science"},
    {"name": "ScienceDaily Mind",    "url": "https://www.sciencedaily.com/rss/mind_brain.xml",  "tag": "neuro", "tagLabel": "신경과학 / Neuroscience"},
]

MAX_ARTICLES      = 20
MAX_PER_FEED      = 4
MAX_NEW_SUMMARIZE = 8


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text)
    for pat, rep in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&nbsp;"," ")]:
        text = text.replace(pat, rep)
    return re.sub(r"\s+", " ", text).strip()


def relative_time(dt):
    diff = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    h = int(diff.total_seconds() // 3600)
    if h < 1:  return "방금 전 / Just now"
    if h < 24: return f"{h}시간 전 / {h}h ago"
    return f"{h//24}일 전 / {h//24}d ago"


def call_claude(prompt: str, api_key: str, max_tokens: int = 1200) -> str:
    """requests 라이브러리로 Claude API 호출"""
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["content"][0]["text"].strip()


def generate_summary(article: dict, api_key: str) -> dict:
    prompt = f"""다음 심리학/AI 뉴스 기사를 분석하고 아래 형식으로 정확히 작성하세요.

[한국어 요약]
6-8문장으로 작성: 연구 배경, 연구 방법(참가자 수·실험 설계), 핵심 결과(구체적 수치 포함), 연구 의의, 한계점을 포함. 일반인도 이해할 수 있게 쉽게 설명.

[English Summary]
6-8 sentences: Research background, methodology, key findings with specific numbers, significance, and limitations.

[핵심 포인트]
- 포인트1 / Point 1
- 포인트2 / Point 2
- 포인트3 / Point 3
- 포인트4 / Point 4

제목: {article['title']}
내용: {article['summary']}"""

    try:
        response = call_claude(prompt, api_key)
        ko_match = re.search(r'\[한국어 요약\]\s*([\s\S]*?)(?=\[English Summary\])', response)
        en_match = re.search(r'\[English Summary\]\s*([\s\S]*?)(?=\[핵심 포인트\])', response)
        kp_match = re.search(r'\[핵심 포인트\]\s*([\s\S]*?)$', response)

        article['aiSummaryKo'] = ko_match.group(1).strip() if ko_match else ''
        article['aiSummaryEn'] = en_match.group(1).strip() if en_match else ''
        article['aiSummary']   = article['aiSummaryEn'] or article['summary']

        if kp_match:
            points = re.findall(r'-\s*(.+)', kp_match.group(1))
            article['keyPoints'] = [p.strip() for p in points if p.strip()][:4]

        # 제목 한국어 번역
        if article['aiSummaryKo']:
            title_prompt = f"다음 영어 제목을 한국어로 자연스럽게 번역하세요. 번역문만 출력하세요.\n\n{article['title']}"
            article['titleKo'] = call_claude(title_prompt, api_key, max_tokens=100)

        print(f"    ✓ 요약 완료: {article['aiSummaryKo'][:30]}...")

    except Exception as e:
        print(f"    ⚠ 요약 실패: {e}")
        article['aiSummaryKo'] = ''
        article['aiSummaryEn'] = article['summary']
        article['aiSummary']   = article['summary']
        article['keyPoints']   = []

    return article


def fetch_feed(feed_info, existing_ids):
    try:
        parsed = feedparser.parse(feed_info["url"])
        articles = []
        for entry in parsed.entries[:MAX_PER_FEED]:
            title   = strip_html(entry.get("title", "")).strip()
            link    = entry.get("link", "").strip()
            summary = strip_html(entry.get("summary", entry.get("description", ""))).strip()
            if not title or not link: continue
            art_id = hashlib.md5(link.encode()).hexdigest()[:12]
            if art_id in existing_ids: continue
            try:
                from email.utils import parsedate_to_datetime
                time_str = relative_time(parsedate_to_datetime(entry.get("published", "")))
            except:
                time_str = "최근 / Recent"
            articles.append({
                "id": art_id, "tag": feed_info["tag"], "tagLabel": feed_info["tagLabel"],
                "source": feed_info["name"], "time": time_str,
                "title": title, "titleKo": "",
                "summary": summary[:600],
                "aiSummary": "", "aiSummaryKo": "", "aiSummaryEn": "",
                "keyPoints": [], "url": link, "featured": False,
            })
        return articles
    except Exception as e:
        print(f"  WARNING {feed_info['name']}: {e}")
        return []


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    # API 키 상태 출력
    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:]
        print(f"=== MindFeed 뉴스 수집 (API 키: {masked}) ===")
    else:
        print("=== ⚠ ANTHROPIC_API_KEY 없음 — 요약 없이 수집만 합니다 ===")

    existing_articles, existing_ids = [], set()
    if os.path.exists("news.json"):
        try:
            with open("news.json", "r", encoding="utf-8") as f:
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

    print(f"\n총 신규 기사: {len(all_new)}개")

    to_summarize = all_new[:MAX_NEW_SUMMARIZE]
    if api_key and to_summarize:
        print(f"Claude API 요약 생성 중 ({len(to_summarize)}개)...")
        for i, article in enumerate(to_summarize):
            print(f"  [{i+1}/{len(to_summarize)}] {article['title'][:60]}...")
            to_summarize[i] = generate_summary(article, api_key)
            time.sleep(0.5)
    elif not api_key:
        print("API 키 없음 — 요약 스킵")
    elif not to_summarize:
        print("신규 기사 없음 — 요약 스킵")

    all_articles = (to_summarize + all_new[MAX_NEW_SUMMARIZE:] + existing_articles)[:MAX_ARTICLES]
    for i, a in enumerate(all_articles):
        a["featured"] = (i == 0)

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump({
            "updated":  datetime.now(timezone.utc).isoformat(),
            "total":    len(all_articles),
            "articles": all_articles,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 완료: 총 {len(all_articles)}개")


if __name__ == "__main__":
    main()
