# -*- coding: utf-8 -*-
"""
카드뉴스 '알맹이'용 재료 수집.
주재료: 위키피디아 리드 섹션(인물·시점·숫자 다수) + REST summary description.
보강: GDELT 관련 뉴스 헤드라인/매체/날짜(best-effort, 실패 시 생략).
"""
import requests, urllib.parse

UA = {"User-Agent": "trendcast/0.2"}

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
        r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", params=p, headers=UA, timeout=8)
        pages = r.json().get("query", {}).get("pages", {})
        lead = list(pages.values())[0].get("extract", "") if pages else ""
        out["lead"] = lead[:1800]
    except Exception as e:
        print("[enrich] lead", e)
    return out

def related_news(query, n=5):
    news = []
    try:
        p = dict(query=f"{query} sourcelang:eng", mode="artlist", maxrecords=n,
                 format="json", timespan="7d", sort="hybridrel")
        r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc",
                         params=p, headers=UA, timeout=6)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            for a in r.json().get("articles", [])[:n]:
                news.append(dict(title=a.get("title", ""), domain=a.get("domain", ""),
                                 date=a.get("seendate", ""), url=a.get("url", "")))
    except Exception as e:
        print("[enrich] gdelt", e)
    return news

def gather(topic, lang="en"):
    """topic dict(title, headline, url, ...) → 재료 뭉치."""
    wiki = wiki_material(topic.get("title", ""), lang)
    q = topic.get("title", "")
    news = related_news(q)
    return {
        "title": topic.get("title", ""),
        "description": wiki["description"],
        "lead": wiki["lead"],
        "headline": topic.get("headline", ""),
        "news": news,
        "url": wiki["url"] or topic.get("url", ""),
        "has_body": bool(wiki["lead"] or news),
    }
