#!/usr/bin/env python3
"""
MindFeed 뉴스 수집기
- PsyPost, APA, arXiv, BPS RSS 피드에서 최신 심리학/AI 기사를 수집
- Claude API로 한/영 AI 요약 자동 생성
- news.json 업데이트
"""

import json
import os
import time
import hashlib
from datetime import datetime, timezone

import feedparser
import requests
import anthropic

# ── 수집할 RSS 소스 ───────────────────────────────────────────────
RSS_FEEDS = [
    {
        "name": "PsyPost",
        "url": "https://www.psypost.org/feed",
        "tag": "psych",
        "tagLabel": "심리학 / Psychology",
    },
    {
        "name": "BPS Research Digest",
        "url": "https://digest.bps.org.uk/feed/",
        "tag": "psych",
        "tagLabel": "심리학 / Psychology",
    },
    {
        "name": "APA News",
        "url": "https://www.apa.org/rss/news.xml",
        "tag": "psych",
        "tagLabel": "심리학 / Psychology",
    },
    {
        "name": "arXiv – cs.AI",
        "url": "https://rss.arxiv.org/rss/cs.AI",
        "tag": "ai",
        "tagLabel": "AI 연구 / AI Research",
    },
    {
        "name": "arXiv – q-bio.NC (Neuroscience)",
        "url": "https://rss.arxiv.org/rss/q-bio.NC",
        "tag": "neuro",
        "tagLabel": "신경과학 / Neuroscience",
    },
    {
        "name": "Behavioral Scientist",
        "url": "https://behavioralscientist.org/feed/",
        "tag": "behav",
        "tagLabel": "행동과학 / Behavioral Science",
    },
]

MAX_ARTICLES   = 20   # 최대 기사 수
MAX_NEW_PER_RUN = 6   # 한 번 실행에 새로 추가할 최대 수 (API 비용 절약)
SUMMARY_MAX_TOKENS = 800


def fetch_feed(feed_info: dict) -> list[dict]:
    """RSS 피드에서 최신 기사 파싱"""
    try:
        parsed = feedparser.parse(feed_info["url"])
        articles = []
        for entry in parsed.entries[:5]:  # 피드당 최대 5개
            title = entry.get("title", "").strip()
            link  = entry.get("link", "").strip()
            summary = entry.get("summary", entry.get("description", "")).strip()
            # HTML 태그 간단 제거
            import re
            summary = re.sub(r"<[^>]+>", "", summary)[:600]

            published = entry.get("published", entry.get("updated", ""))
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(published)
                time_str = _relative_time(pub_dt)
            except Exception:
                time_str = "최근 / Recent"

            if not title or not link:
                continue

            articles.append({
                "id": hashlib.md5(link.encode()).hexdigest()[:12],
                "tag": feed_info["tag"],
                "tagLabel": feed_info["tagLabel"],
                "source": feed_info["name"],
                "time": time_str,
                "title": title,
                "summary": summary,
                "url": link,
                "aiSummary": None,
                "keyPoints": [],
                "featured": False,
            })
        return articles
    except Exception as e:
        print(f"  ⚠ {feed_info['name']} 수집 실패: {e}")
        return []


def _relative_time(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    diff = now - dt.astimezone(timezone.utc)
    h = int(diff.total_seconds() // 3600)
    if h < 1:
        return "방금 전 / Just now"
    if h < 24:
        return f"{h}시간 전 / {h}h ago"
    d = h // 24
    return f"{d}일 전 / {d}d ago"


def generate_summary(article: dict, client: anthropic.Anthropic) -> dict:
    """Claude API로 한/영 AI 요약 + 핵심 포인트 생성"""
    prompt = f"""다음 심리학/AI 뉴스 기사를 분석하고 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

제목: {article['title']}
내용: {article['summary']}

응답 형식 (JSON만):
{{
  "aiSummary_ko": "한국어 요약 3-4문장. 연구 방법, 핵심 결과, 의의를 포함.",
  "aiSummary_en": "English summary in 3-4 sentences. Include method, key findings, significance.",
  "keyPoints": [
    "핵심 포인트 1 / Key point 1",
    "핵심 포인트 2 / Key point 2",
    "핵심 포인트 3 / Key point 3",
    "핵심 포인트 4 / Key point 4"
  ]
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=SUMMARY_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # JSON 파싱
        import re
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            article["aiSummary"] = (
                data.get("aiSummary_ko", "") + "\n\n" + data.get("aiSummary_en", "")
            ).strip()
            article["keyPoints"] = data.get("keyPoints", [])
    except Exception as e:
        print(f"    ⚠ 요약 실패: {e}")
        article["aiSummary"] = article["summary"]
        article["keyPoints"] = []

    return article


def main():
    print("=== MindFeed 뉴스 수집 시작 ===")

    # 기존 news.json 로드
    existing_ids = set()
    existing_articles = []
    if os.path.exists("news.json"):
        try:
            with open("news.json", "r", encoding="utf-8") as f:
                old_data = json.load(f)
            existing_articles = old_data.get("articles", [])
            existing_ids = {a["id"] for a in existing_articles}
            print(f"기존 기사 {len(existing_articles)}개 로드")
        except Exception:
            pass

    # RSS 수집
    all_new = []
    for feed in RSS_FEEDS:
        print(f"수집 중: {feed['name']}")
        articles = fetch_feed(feed)
        new_articles = [a for a in articles if a["id"] not in existing_ids]
        print(f"  → 신규 {len(new_articles)}개")
        all_new.extend(new_articles)

    # AI 요약 생성 (새 기사만, 최대 MAX_NEW_PER_RUN개)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    to_summarize = all_new[:MAX_NEW_PER_RUN]

    if api_key and to_summarize:
        client = anthropic.Anthropic(api_key=api_key)
        print(f"\nAI 요약 생성 중 ({len(to_summarize)}개)...")
        for i, article in enumerate(to_summarize):
            print(f"  [{i+1}/{len(to_summarize)}] {article['title'][:50]}...")
            to_summarize[i] = generate_summary(article, client)
            time.sleep(0.5)  # API 레이트 리밋 방지

    # 첫 번째 기사를 featured로 설정
    all_articles = to_summarize + existing_articles
    for i, a in enumerate(all_articles):
        a["featured"] = (i == 0)

    # 최대 MAX_ARTICLES개만 유지
    all_articles = all_articles[:MAX_ARTICLES]

    # news.json 저장
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "total": len(all_articles),
        "articles": all_articles,
    }
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ news.json 업데이트 완료: {len(all_articles)}개 기사")
    print(f"  신규 추가: {len(to_summarize)}개")


if __name__ == "__main__":
    main()
