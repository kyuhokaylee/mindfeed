#!/usr/bin/env python3
"""
MindFeed 뉴스 수집기 (완전 무료 버전 + MyMemory 한국어 번역)
- RSS 8개 소스에서 최신 심리학/AI 기사 수집
- 추출적 요약 후 MyMemory API로 한국어 자동 번역
- news.json 업데이트
"""

import json, os, re, hashlib, time
from datetime import datetime, timezone
import feedparser
import urllib.request
import urllib.parse

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

MAX_ARTICLES = 20
MAX_PER_FEED = 4
TRANSLATE_MAX_CHARS = 400  # MyMemory 무료 한도 고려


# ── 유틸 ──────────────────────────────────────────────────────────
def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text)
    for pat, rep in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&nbsp;"," ")]:
        text = text.replace(pat, rep)
    text = re.sub(r"&#\d+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


def extractive_summary(text, n=4):
    """핵심 키워드 기반 문장 추출"""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 30]
    if not sentences:
        return text[:500]
    keywords = [
        "study","research","found","shows","suggests","reveals","participants",
        "results","effect","significant","percent","%","published","journal",
        "scientists","researchers","brain","cognitive","behavior","mental",
        "psychological","neural","AI","model","algorithm","GPT","according",
        "associated","increased","decreased","compared","analysis","trial",
    ]
    def score(s):
        return sum(1.5 for kw in keywords if kw.lower() in s.lower())
    scored = sorted(enumerate(sentences), key=lambda x: score(x[1]), reverse=True)
    top = sorted([i for i,_ in scored[:n]])
    return " ".join(sentences[i] for i in top)


def extract_key_points(summary):
    """핵심 수치·결론 문장 추출"""
    points = []
    for pat in [
        r"(\d+(?:\.\d+)?%[^.]*\.)",
        r"(\d+\s*(?:participants?|patients?|people|subjects?)[^.]*\.)",
        r"((?:findings?|results?|study|researchers?)[^.]*(?:suggest|show|found|reveal)[^.]*\.)",
        r"((?:randomized|RCT|meta-analysis|fMRI|placebo)[^.]*\.)",
    ]:
        m = re.search(pat, summary, re.I)
        if m:
            candidate = m.group(1).strip()[:90]
            if candidate not in points:
                points.append(candidate)
    sents = [s.strip() for s in re.split(r"[.!?]", summary) if len(s.strip()) > 25]
    while len(points) < 4 and sents:
        c = sents.pop(0)[:90]
        if c not in points:
            points.append(c)
    return points[:4]


# ── MyMemory 번역 (완전 무료, 키 불필요) ─────────────────────────
def translate_ko(text: str) -> str:
    """MyMemory API로 영→한 번역. 실패 시 원문 반환."""
    if not text:
        return text
    # 400자 초과 시 자르기 (MyMemory 무료 한도)
    text_cut = text[:TRANSLATE_MAX_CHARS]
    try:
        params = urllib.parse.urlencode({
            "q": text_cut,
            "langpair": "en|ko",
            "de": "mindfeed@example.com",  # 이메일 입력 시 하루 한도 5000→10000자
        })
        url = f"https://api.mymemory.translated.net/get?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "MindFeed/1.0"})
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode())
        translated = data.get("responseData", {}).get("translatedText", "")
        if translated and translated.upper() != text_cut.upper():
            return translated
    except Exception as e:
        print(f"    번역 실패: {e}")
    return text  # 실패 시 원문


# ── 상대 시간 ─────────────────────────────────────────────────────
def relative_time(dt):
    diff = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    h = int(diff.total_seconds() // 3600)
    if h < 1:  return "방금 전 / Just now"
    if h < 24: return f"{h}시간 전 / {h}h ago"
    return f"{h//24}일 전 / {h//24}d ago"


# ── RSS 수집 ─────────────────────────────────────────────────────
def fetch_feed(feed_info, existing_ids):
    try:
        parsed = feedparser.parse(feed_info["url"])
        articles = []
        for entry in parsed.entries[:MAX_PER_FEED]:
            title   = strip_html(entry.get("title", "")).strip()
            link    = entry.get("link", "").strip()
            summary = strip_html(entry.get("summary", entry.get("description", ""))).strip()
            if not title or not link:
                continue
            art_id = hashlib.md5(link.encode()).hexdigest()[:12]
            if art_id in existing_ids:
                continue
            try:
                from email.utils import parsedate_to_datetime
                time_str = relative_time(parsedate_to_datetime(entry.get("published", "")))
            except:
                time_str = "최근 / Recent"

            # 영어 요약 추출
            en_summary = extractive_summary(summary, n=4)
            key_points_en = extract_key_points(summary)

            articles.append({
                "_en_summary":    en_summary,       # 번역용 임시 필드
                "_key_points_en": key_points_en,    # 번역용 임시 필드
                "id":       art_id,
                "tag":      feed_info["tag"],
                "tagLabel": feed_info["tagLabel"],
                "source":   feed_info["name"],
                "time":     time_str,
                "title":    title,
                "summary":  summary[:300],
                "url":      link,
                "featured": False,
            })
        return articles
    except Exception as e:
        print(f"  WARNING {feed_info['name']}: {e}")
        return []


# ── 번역 처리 ────────────────────────────────────────────────────
def translate_articles(articles):
    """새 기사들의 요약·제목·핵심포인트를 한국어로 번역"""
    for i, a in enumerate(articles):
        print(f"  번역 중 [{i+1}/{len(articles)}] {a['title'][:50]}...")

        en_sum   = a.pop("_en_summary", "")
        kp_en    = a.pop("_key_points_en", [])

        # 제목 번역
        title_ko = translate_ko(a["title"])
        time.sleep(0.3)

        # 요약 번역
        summary_ko = translate_ko(en_sum)
        time.sleep(0.3)

        # 핵심 포인트 번역 (최대 4개)
        key_points_ko = []
        for kp in kp_en[:4]:
            kp_ko = translate_ko(kp)
            key_points_ko.append(f"{kp_ko} / {kp}")
            time.sleep(0.2)

        a["titleKo"]    = title_ko
        a["aiSummary"]  = en_sum           # 영어 원문 (앱 폴백용)
        a["aiSummaryKo"] = summary_ko      # 한국어 번역
        a["aiSummaryEn"] = en_sum          # 영어 원문
        a["keyPoints"]  = key_points_ko

    return articles


# ── 메인 ─────────────────────────────────────────────────────────
def main():
    print("=== MindFeed 뉴스 수집 (무료 + MyMemory 번역) ===")

    existing_articles, existing_ids = [], set()
    if os.path.exists("news.json"):
        try:
            with open("news.json", "r", encoding="utf-8") as f:
                old = json.load(f)
            existing_articles = old.get("articles", [])
            existing_ids = {a["id"] for a in existing_articles}
            print(f"기존 {len(existing_articles)}개 로드")
        except:
            pass

    all_new = []
    for feed in RSS_FEEDS:
        print(f"수집: {feed['name']}")
        new = fetch_feed(feed, existing_ids)
        print(f"  신규 {len(new)}개")
        all_new.extend(new)

    if all_new:
        print(f"\n번역 시작: {len(all_new)}개 기사")
        all_new = translate_articles(all_new)

    all_articles = (all_new + existing_articles)[:MAX_ARTICLES]
    for i, a in enumerate(all_articles):
        a["featured"] = (i == 0)
        # 임시 번역 필드 정리
        a.pop("_en_summary", None)
        a.pop("_key_points_en", None)

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump({
            "updated":  datetime.now(timezone.utc).isoformat(),
            "total":    len(all_articles),
            "articles": all_articles,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 완료: 총 {len(all_articles)}개 (신규 {len(all_new)}개)")


if __name__ == "__main__":
    main()
