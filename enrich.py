# -*- coding: utf-8 -*-
"""
재료 수집 v3 — 기사 전문 + 커뮤니티 반응까지.
소스: Guardian(전문) > NYT(선택) > NewsAPI(발췌) / 위키 리드 / Reddit·HN(반응)
모든 소스는 실패해도 전체 파이프라인이 죽지 않게 graceful.
"""
import os, re, html, requests, urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (trendcast/0.3)"}

def _env(k): return os.environ.get(k, "")

def _clean_text(t):
    """HTML 태그·엔티티 제거 (검색 결과 정리용)."""
    t = html.unescape(t or "")
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"[ \t]+", " ", t).strip()

# 뉴스 검색을 오염시키는 커뮤니티/집계 노이즈 단어
_QUERY_NOISE = {
    "오늘자","오늘","뉴스","가져옴","가져왔다","가져와","실시간","속보","단독","공식",
    "근황","현재","방금","떴다","레전드","클라스","대박","실화","이거","이건","봐라",
    "보는","보기","모음","정리","요약","한눈에","네이트","네이버","다음","연예",
}

def _clean_query(q):
    """트렌드 제목에서 ㅋㅋ·이모지·노이즈를 걸러 뉴스 검색용 핵심 키워드만 남긴다.
    예: 'ㅋㅋㅋ 리센느 제나 오늘자 뉴스 가져옴ㅋㅋ' → '리센느 제나'"""
    t = re.sub(r"[ㄱ-ㅎㅏ-ㅣ]{1,}", " ", q or "")   # 자음/모음 반복(ㅋㅋ,ㅠㅠ 등)
    t = re.sub(r"[^\w\s]", " ", t)                    # 이모지·특수문자 제거(한글은 \w에 포함)
    toks, seen = [], set()
    for w in t.split():
        if len(w) < 2 or w in _QUERY_NOISE or w in seen:
            continue
        seen.add(w); toks.append(w)
    cleaned = " ".join(toks[:5]).strip()
    if cleaned:
        return cleaned
    # 전부 걸러졌으면 ㅋㅋ만 뺀 원문으로 폴백
    return re.sub(r"[ㄱ-ㅎㅏ-ㅣ]+", " ", q or "").strip() or (q or "")

# ── 위키피디아: 배경·인물·숫자 ─────────────────────────
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
        print("[wiki] summary", e)
    try:
        p = dict(action="query", prop="extracts", exintro=1, explaintext=1,
                 redirects=1, format="json", titles=title)
        r = requests.get(f"https://{lang}.wikipedia.org/w/api.php",
                         params=p, headers=UA, timeout=8)
        pages = r.json().get("query", {}).get("pages", {})
        out["lead"] = (list(pages.values())[0].get("extract", "") if pages else "")[:1800]
    except Exception as e:
        print("[wiki] lead", e)
    return out

# ── Guardian: 기사 전문 (핵심 재료) ────────────────────
def _short_q(query, maxlen=80):
    # 긴 제목 → 핵심 단어 위주로 축약 (Guardian 414 방지)
    q = re.sub(r"[^\w\s]", " ", query)
    words = [w for w in q.split() if len(w) > 2][:6]
    return " ".join(words)[:maxlen] or query[:maxlen]

def guardian_articles(query, n=3):
    key = _env("GUARDIAN_API_KEY")
    if not key:
        return []
    arts = []
    try:
        r = requests.get("https://content.guardianapis.com/search",
            params={"q": _short_q(query), "show-fields": "bodyText,headline",
                    "order-by": "relevance", "page-size": n, "api-key": key},
            headers=UA, timeout=10)
        if r.status_code == 200:
            for a in r.json().get("response", {}).get("results", [])[:n]:
                body = (a.get("fields", {}) or {}).get("bodyText", "")
                arts.append(dict(
                    title=a.get("webTitle", ""),
                    date=(a.get("webPublicationDate", "") or "")[:10],
                    section=a.get("sectionName", ""),
                    url=a.get("webUrl", ""),
                    body=body[:2500],       # 기사당 2500자까지
                ))
        else:
            print("[guardian] status", r.status_code, r.text[:80])
    except Exception as e:
        print("[guardian] err", e)
    return arts

# ── NewsAPI: 최신 헤드라인 보조 ────────────────────────
def newsapi_articles(query, n=4):
    key = _env("NEWSAPI_KEY")
    if not key:
        return []
    arts = []
    try:
        r = requests.get("https://newsapi.org/v2/everything",
            params=dict(q=query, language="en", sortBy="publishedAt",
                        pageSize=n, apiKey=key), headers=UA, timeout=10)
        if r.status_code == 200:
            for a in r.json().get("articles", [])[:n]:
                body = " ".join(filter(None, [
                    a.get("description", "") or "",
                    (a.get("content", "") or "").split("[+")[0].strip()]))
                arts.append(dict(title=a.get("title", ""),
                                 domain=(a.get("source", {}) or {}).get("name", ""),
                                 date=(a.get("publishedAt", "") or "")[:10],
                                 url=a.get("url", ""), body=body[:300]))
    except Exception as e:
        print("[newsapi] err", e)
    return arts

# ── Reddit: 대중 반응 (OAuth 우선, 공개 JSON 폴백) ────
_reddit_token = {"val": None}

def _reddit_auth():
    """client_credentials OAuth → 토큰. 자격증명 없으면 None."""
    cid, sec = _env("REDDIT_CLIENT_ID"), _env("REDDIT_CLIENT_SECRET")
    if not (cid and sec):
        return None
    if _reddit_token["val"]:
        return _reddit_token["val"]
    try:
        r = requests.post("https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(cid, sec),
            headers={"User-Agent": "trendcast/0.3 by trendcast-app"},
            timeout=8)
        if r.status_code == 200:
            tok = r.json().get("access_token")
            _reddit_token["val"] = tok
            return tok
        print("[reddit] auth status", r.status_code, r.text[:80])
    except Exception as e:
        print("[reddit] auth err", e)
    return None

def reddit_reactions(query, n=5):
    posts = []
    tok = _reddit_auth()
    try:
        if tok:
            r = requests.get("https://oauth.reddit.com/search",
                params=dict(q=query, sort="top", t="week", limit=n),
                headers={"Authorization": f"Bearer {tok}",
                         "User-Agent": "trendcast/0.3 by trendcast-app"},
                timeout=8)
        else:
            r = requests.get("https://www.reddit.com/search.json",
                params=dict(q=query, sort="top", t="week", limit=n),
                headers={"User-Agent": "Mozilla/5.0 (research; trendcast/0.3)"},
                timeout=8)
        if r.status_code == 200:
            for c in r.json().get("data", {}).get("children", [])[:n]:
                d = c.get("data", {})
                posts.append(dict(title=d.get("title", ""), ups=d.get("ups", 0),
                                  comments=d.get("num_comments", 0),
                                  sub=d.get("subreddit", "")))
        else:
            print("[reddit] status", r.status_code)
    except Exception as e:
        print("[reddit] err", e)
    return posts

# ── Hacker News: 기술·경제 커뮤니티 반응 (키리스) ──────
def hn_reactions(query, n=4):
    hits = []
    try:
        r = requests.get("https://hn.algolia.com/api/v1/search",
            params=dict(query=query, tags="story", hitsPerPage=n),
            headers=UA, timeout=8)
        if r.status_code == 200:
            for h in r.json().get("hits", [])[:n]:
                hits.append(dict(title=h.get("title", "") or "",
                                 points=h.get("points", 0) or 0,
                                 comments=h.get("num_comments", 0) or 0))
    except Exception as e:
        print("[hn] err", e)
    return hits

# ── 국내 뉴스 ──────────────────────────────────────────
def naver_news_articles(query, n=5):
    """네이버 뉴스 검색 — 국내 기사 제목·요약 (enrich 재료용)."""
    cid = _env("NAVER_CLIENT_ID")
    sec = _env("NAVER_CLIENT_SECRET")
    if not (cid and sec): return []
    arts = []
    try:
        r = requests.get("https://openapi.naver.com/v1/search/news.json",
            params={"query": query, "display": n, "sort": "sim"},
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec,
                     "User-Agent": "trendcast/0.3"}, timeout=10)
        if r.status_code == 200:
            for item in r.json().get("items", [])[:n]:
                title = _clean_text(item.get("title",""))
                desc  = _clean_text(item.get("description",""))
                if title:
                    arts.append(dict(title=title, domain="네이버뉴스", section="",
                                     date="", url=item.get("originallink",""),
                                     body=desc[:300]))
        elif r.status_code == 401:
            print("[naver_news_enrich] 401 — 네이버 앱에 '검색' API 권한을 추가하세요 (developers.naver.com)")
        else:
            print("[naver_news_enrich] status", r.status_code)
    except Exception as e:
        print("[naver_news_enrich] err", e)
    return arts


def kakao_news_articles(query, n=4):
    """카카오 웹 검색 — 국내 기사 제목·요약."""
    key = _env("KAKAO_REST_API_KEY")
    if not key: return []
    arts = []
    try:
        r = requests.get("https://dapi.kakao.com/v2/search/web",
            params={"query": query + " 뉴스", "size": n},
            headers={"Authorization": f"KakaoAK {key}",
                     "User-Agent": "trendcast/0.3"}, timeout=10)
        if r.status_code == 200:
            for d in r.json().get("documents",[])[:n]:
                title = _clean_text(d.get("title",""))
                body  = _clean_text(d.get("contents",""))   # <b> 등 제거
                if title:
                    arts.append(dict(title=title, domain="카카오", section="",
                                     date="", url=d.get("url",""),
                                     body=body[:300]))
        else:
            print("[kakao_enrich] status", r.status_code)
    except Exception as e:
        print("[kakao_enrich] err", e)
    return arts


# ── 통합 ───────────────────────────────────────────────
def gather(topic, lang="en"):
    title = topic.get("title", "")
    is_kr = (topic.get("geo","") == "KR" or
             any(s in topic.get("sources",[]) for s in ("naver_datalab","naver_news","kakao_news")))
    # 국내 트렌드는 커뮤니티식 제목이 많아 검색어를 정제해서 사용
    q_kr = _clean_query(title) if is_kr else title
    if is_kr and q_kr != title:
        print(f"[gather] 검색어 정제: '{title}' → '{q_kr}'")

    wiki      = wiki_material(title, lang)
    # 국내 트렌드는 Guardian(영문)이 무의미하므로 스킵 (414/빈결과 방지)
    guardian  = [] if is_kr else guardian_articles(title)
    newsapi   = newsapi_articles(title, 2) if guardian else (newsapi_articles(title) if not is_kr else [])
    naver  = naver_news_articles(q_kr) if is_kr else []
    kakao  = kakao_news_articles(q_kr) if is_kr and len(naver) < 2 else []
    reddit = [] if is_kr else reddit_reactions(title)
    hn     = [] if is_kr else hn_reactions(title)

    all_articles = guardian + naver + kakao
    total_body = sum(len(a.get("body","")) for a in all_articles)
    print(f"[gather] guardian={len(guardian)} naver={len(naver)} kakao={len(kakao)} "
          f"newsapi={len(newsapi)} reddit={len(reddit)} hn={len(hn)} "
          f"wiki={len(wiki['lead'])}ch body={total_body}ch")
    return {
        "title": title,
        "description": wiki["description"],
        "lead": wiki["lead"],
        "headline": topic.get("headline", ""),
        "guardian": all_articles,   # llm.py는 'guardian' 키를 기사 재료로 사용
        "news": newsapi,
        "reddit": reddit,
        "hn": hn,
        "url": (all_articles[0]["url"] if all_articles and all_articles[0].get("url")
                else (wiki["url"] or topic.get("url", ""))),
        "has_body": bool(wiki["lead"] or all_articles or newsapi),
    }


def _naver_search_available():
    """네이버 앱에 검색 API가 활성화됐는지 확인."""
    import os as _os
    return bool(_os.environ.get("NAVER_CLIENT_ID") and
                _os.environ.get("NAVER_CLIENT_SECRET") and
                _os.environ.get("NAVER_SEARCH_ENABLED","true").lower() != "false")
