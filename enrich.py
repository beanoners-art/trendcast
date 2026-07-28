# -*- coding: utf-8 -*-
"""
카드뉴스 '알맹이'용 재료 수집.
주재료: 위키피디아 리드 섹션(인물·시점·숫자 다수) + REST summary description.
뉴스: NewsAPI(키 있으면 우선) → GDELT(best-effort 폴백).
"""
import os, requests, urllib.parse

UA = {"User-Agent": "trendcast/0.2"}
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")

def wiki_material(title, lang="en"):
    out = {"description": "", "lead": "", "url": ""}
    try:
        t = urllib.parse.quote(title.replace(" ", "_"))
        r = requests.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{t}",
                         headers=UA, timeout=8)
        if r.status_code == 200:
            d = r.json()
            out["description"] = d.get("description", "") or ""
            out["url"] = d.get("content_urls", {}).get("desktop", {}).get("page", "")
    except Exception as e:
        print("[enrich] summary", e)
    try:
        p = dict(action="query", prop="extracts", exintro=1, explaintext=1,
                 redirects=1, format="json", titles=title)
        r = requests.get(f"https://{lang}.wikipedia.org/w/api.php",
                         params=p, headers=UA, timeout=8)
        pages = r.json().get("query", {}).get("pages", {})
        lead = list(pages.values())[0].get("extract", "") if pages else ""
        out["lead"] = lead[:1800]
    except Exception as e:
        print("[enrich] lead", e)
    return out

def _news_newsapi(query, n=6):
    """NewsAPI — 키 있을 때 우선. 제목+description+content(200자) 반환."""
    if not NEWSAPI_KEY:
        return []
    news = []
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params=dict(q=query, language="en", sortBy="publishedAt",
                        pageSize=n, apiKey=NEWSAPI_KEY),
            headers=UA, timeout=10
        )
        if r.status_code == 200:
            for a in r.json().get("articles", [])[:n]:
                body = " ".join(filter(None, [
                    a.get("description", "") or "",
                    (a.get("content", "") or "").split("[+")[0].strip()
                ]))
                news.append(dict(
                    title=a.get("title", ""),
                    domain=(a.get("source", {}) or {}).get("name", ""),
                    date=(a.get("publishedAt", "") or "")[:10],
                    url=a.get("url", ""),
                    body=body[:400],
                ))
        else:
            print("[newsapi] status", r.status_code, r.text[:80])
    except Exception as e:
        print("[newsapi] err", e)
    return news

def _news_gdelt(query, n=5):
    """GDELT — 키리스 폴백."""
    news = []
    try:
        p = dict(query=f"{query} sourcelang:eng", mode="artlist",
                 maxrecords=n, format="json", timespan="7d", sort="hybridrel")
        r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc",
                         params=p, headers=UA, timeout=6)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            for a in r.json().get("articles", [])[:n]:
                news.append(dict(title=a.get("title", ""),
                                 domain=a.get("domain", ""),
                                 date=(a.get("seendate", "") or "")[:8],
                                 url=a.get("url", ""), body=""))
    except Exception as e:
        print("[gdelt] err", e)
    return news

def related_news(query, n=6):
    """NewsAPI 우선, 없으면 GDELT."""
    result = _news_newsapi(query, n)
    if not result:
        result = _news_gdelt(query, n)
    return result

def gather(topic, lang="en"):
    """topic dict → 재료 뭉치(위키 리드 + 뉴스 본문)."""
    wiki = wiki_material(topic.get("title", ""), lang)
    news = related_news(topic.get("title", ""))
    return {
        "title":       topic.get("title", ""),
        "description": wiki["description"],
        "lead":        wiki["lead"],
        "headline":    topic.get("headline", ""),
        "news":        news,
        "url":         wiki["url"] or topic.get("url", ""),
        "has_body":    bool(wiki["lead"] or news),
    }
