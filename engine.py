# -*- coding: utf-8 -*-
"""
트렌드 수집·점수화 엔진 (키리스 소스 중심)
흐름: 수집 → 소스내 정규화 → 이슈 클러스터링 → 트렌드지수(속도, 1차 게이트)
      → 관련성 × 소스교차 확신도 (2차 점수) → 카테고리/브랜드세이프티 태깅 → 랭킹

+ '커피' 카테고리: 실시간 트렌드에는 커피가 거의 안 잡히므로, 이 카테고리는
  파이프라인을 건너뛰고 커피 키워드로 네이버·카카오 뉴스를 직접 검색해 모은다.
"""
import requests, xml.etree.ElementTree as ET, datetime as dt, json, os, re, math
from difflib import SequenceMatcher

UA = {"User-Agent": "Mozilla/5.0 (trendcast/0.1)"}
STORE = os.path.join(os.path.dirname(__file__), "snapshots.json")

# ---------- 소스 ----------
def fetch_google_trends(geo="US"):
    """구글 트렌드 급상승(뜨는 중) — 키리스 RSS. approx_traffic = 대략 검색량."""
    out = []
    try:
        r = requests.get(f"https://trends.google.com/trending/rss?geo={geo}", headers=UA, timeout=8)
        root = ET.fromstring(r.content)
        ns = {"ht": "https://trends.google.com/trending/rss"}
        for it in root.findall(".//item"):
            title = (it.findtext("title") or "").strip()
            traf = it.findtext("ht:approx_traffic", default="0", namespaces=ns) or "0"
            mag = float(re.sub(r"[^\d]", "", traf) or 0)
            news = it.find("ht:news_item", ns)
            headline = news.findtext("ht:news_item_title", namespaces=ns) if news is not None else ""
            link = news.findtext("ht:news_item_url", namespaces=ns) if news is not None else ""
            if title:
                out.append(dict(title=title, source="google_trends", magnitude=mag,
                                headline=headline or "", url=link or "", geo=geo))
    except Exception as e:
        print("[google_trends] err", e)
    return out

def fetch_wikipedia(lang="en"):
    """위키피디아 급상승 조회수 — 키리스. 어제자 most-read."""
    out = []
    for back in (1, 2):
        d = (dt.date.today() - dt.timedelta(days=back)).strftime("%Y/%m/%d")
        try:
            r = requests.get(f"https://api.wikimedia.org/feed/v1/wikipedia/{lang}/featured/{d}",
                             headers=UA, timeout=8)
            arts = r.json().get("mostread", {}).get("articles", [])
            for a in arts[:25]:
                t = a.get("normalizedtitle") or a.get("title", "")
                if t and not t.startswith(("Special:", "Main Page", "Wikipedia:")):
                    out.append(dict(title=t, source="wikipedia", magnitude=float(a.get("views", 0)),
                                    headline=a.get("extract", "")[:160], url=a.get("content_urls", {})
                                    .get("desktop", {}).get("page", ""), geo="global"))
            if out:
                break
        except Exception as e:
            print("[wikipedia] err", e)
    return out

def fetch_gdelt(query="(economy OR politics OR sports OR culture)"):
    """GDELT 글로벌 뉴스 — 키리스(서버 불안정시 자동 생략)."""
    out = []
    try:
        p = dict(query=f"{query} sourcelang:eng", mode="artlist", maxrecords=40,
                 format="json", timespan="24h", sort="hybridrel")
        r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", params=p, headers=UA, timeout=8)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            for a in r.json().get("articles", []):
                t = (a.get("title") or "").strip()
                if t:
                    out.append(dict(title=t, source="gdelt", magnitude=1.0,
                                    headline=a.get("domain", ""), url=a.get("url", ""), geo="global"))
    except Exception as e:
        print("[gdelt] unavailable", e)
    return out  # GDELT는 기사 건수 기반 → 클러스터 단계에서 빈도로 환산

# ---------- 정규화 ----------
def percentile_normalize(items):
    """소스별로 magnitude를 0~100 백분위로 정규화(단위 차이 제거)."""
    by_src = {}
    for it in items:
        by_src.setdefault(it["source"], []).append(it)
    for src, group in by_src.items():
        vals = sorted(x["magnitude"] for x in group)
        n = len(vals)
        for it in group:
            rank = sum(1 for v in vals if v <= it["magnitude"])
            it["norm"] = round(100 * rank / max(n, 1), 1)
    return items

# ---------- 클러스터링(이슈 통합) ----------
def _key(t):
    return re.sub(r"[^a-z0-9가-힣 ]", "", t.lower()).strip()

def _sim(a, b):
    ka, kb = set(_key(a).split()), set(_key(b).split())
    jac = len(ka & kb) / max(len(ka | kb), 1)
    return max(jac, SequenceMatcher(None, _key(a), _key(b)).ratio())

def cluster(items, thresh=0.45):
    clusters = []
    for it in items:
        placed = False
        for c in clusters:
            if _sim(it["title"], c["title"]) >= thresh:
                c["items"].append(it)
                c["sources"].add(it["source"])
                if it["norm"] > c["norm"]:
                    c["norm"], c["title"] = it["norm"], it["title"]
                if it.get("headline") and not c["headline"]:
                    c["headline"] = it["headline"]
                if it.get("url") and not c["url"]:
                    c["url"] = it["url"]
                placed = True
                break
        if not placed:
            clusters.append(dict(title=it["title"], norm=it["norm"], headline=it.get("headline", ""),
                                 url=it.get("url", ""), sources={it["source"]}, items=[it],
                                 geo=it.get("geo", "")))
    return clusters

# ---------- 속도(velocity) + 포화 페널티: 스냅샷 비교 ----------
def load_store():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}

def save_store(s):
    json.dump(s, open(STORE, "w", encoding="utf-8"), ensure_ascii=False)

def apply_velocity(clusters):
    store = load_store()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for c in clusters:
        k = _key(c["title"])[:60]
        hist = store.get(k, {})
        prev = hist.get("norm")
        if prev is None:
            c["velocity"] = None          # 첫 관측 = 기준선(트렌드 RSS는 본질적으로 '뜨는 중')
            c["vboost"] = 1.15 if "google_trends" in c["sources"] else 1.0
        else:
            delta = (c["norm"] - prev) / max(prev, 1)
            c["velocity"] = round(delta, 3)
            c["vboost"] = max(0.5, min(2.0, 1 + delta))   # 상승=부스트, 하락=포화 페널티
        store[k] = {"norm": c["norm"], "ts": now}
    save_store(store)
    return clusters

# ---------- 카테고리 + 브랜드 세이프티 ----------
CATS = {
    "경제·금융": ["econom", "market", "stock", "inflation", "rate", "finance", "bank", "증시", "금리", "환율", "코스피", "경제"],
    "정치": ["election", "president", "senate", "parliament", "policy", "vote", "politician", "minister", "government", "congress", "lawmaker", "정치", "대통령", "선거", "국회", "법안", "총리", "장관", "정부", "의원"],
    "문화·연예": ["film", "movie", "music", "album", "actor", "singer", "series", "drama", "celebrit", "영화", "음악", "배우", "가수", "드라마", "아이돌"],
    "스포츠": ["match", "league", "cup", "goal", "player", "coach", "chelsea", "nba", "fifa", "축구", "야구", "농구", "리그", "감독", "선수"],
    "기술·IT": ["ai", "tech", "software", "chip", "startup", "robot", "인공지능", "반도체", "스타트업"],
    "커피": ["coffee", "espresso", "roast", "barista", "커피", "원두", "생두", "카페", "로스터", "로스팅", "스페셜티", "게이샤", "바리스타", "에스프레소"],
}
SENSITIVE = ["death", "died", "dead", "killed", "kill", "shot", "shooting", "accident", "crash",
             "disaster", "earthquake", "flood", "war", "attack", "victim", "사망", "숨져", "사고",
             "총격", "지진", "홍수", "전쟁", "참사", "피해자", "부상"]

def _kw_hit(blob, tokens, kw):
    # 짧은 영문 키워드(ai 등)는 단어 경계로, 긴 키워드/한글은 부분일치 허용
    if kw.isascii() and len(kw) <= 4:
        return any(t == kw or t.startswith(kw) and len(t) - len(kw) <= 2 for t in tokens) or f" {kw} " in f" {blob} "
    return kw in blob

def tag(c):
    blob = (c["title"] + " " + c.get("headline", "")).lower()
    tokens = re.findall(r"[a-z0-9가-힣]+", blob)
    cat = "기타"
    for name, kws in CATS.items():
        if any(_kw_hit(blob, tokens, k) for k in kws):
            cat = name
            break
    c["category"] = cat
    c["sensitive"] = any(k in blob for k in SENSITIVE) or cat == "정치"
    return c

# ---------- 빅이슈 필터 ----------
BLACKLIST = [
    "weather","forecast","rain","snow","storm","hurricane","tornado",
    "flood warning","heat wave","blizzard","soaking","drought",
    "wordle","connections hint","nyt hint","crossword","puzzle answer",
    "daily horoscope","lottery","powerball","mega million",
    "county fair","state fair","traffic","road closure",
    "training camp","preseason","depth chart","mock draft",
    "rumor","spotted","dating","breakup","feud","beef",
    "sale","deal","coupon","discount","black friday",
    "how to watch","listen and follow","where to watch",
    "tips","tricks","guide to","tutorial",
]

def _is_blacklisted(title, headline=""):
    import re as _re
    blob = (title + " " + (headline or "")).lower()
    for kw in BLACKLIST:
        # 멀티워드 키워드는 부분일치, 단일 단어는 단어경계 적용
        if " " in kw:
            if kw in blob:
                return True
        else:
            if _re.search(r"\b" + _re.escape(kw) + r"\b", blob):
                return True
    return False

def _claude_bigissue_score(items):
    """Claude가 빅이슈 점수 0~10 채점. 키 없으면 전부 통과."""
    import os as _os, json as _json, re as _re2
    key = _os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        for c in items: c["big_score"] = 7
        return items
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=key)
        topics = "\n".join(
            f"{i+1}. {c['title']} | {c.get('headline','')[:80]}"
            for i, c in enumerate(items)
        )
        msg = client.messages.create(
            model=_os.environ.get("CLAUDE_MODEL","claude-sonnet-4-6"),
            max_tokens=300,
            system="""You are an editor for a KOREAN social media audience. Rate each topic 0-10 for how much KOREAN readers would care about it.
Low (0-4): foreign local weather, quiz answers, obscure regional events, minor gossip with no Korea relevance, foreign sports schedules.
High (7-10): major world politics/economy affecting Korea, global tech/AI, K-culture & entertainment, issues involving Korea/Asia, viral global stories, major disasters, big international sports.
Give a slight boost to topics relevant to Korea or Asia. Output ONLY a JSON array of integers. Example: [8,3,9,2,7]""",
            messages=[{"role":"user","content":f"Rate these:\n{topics}"}]
        )
        txt = "".join(b.text for b in msg.content if b.type=="text").strip()
        if not txt:
            raise ValueError("empty response")
        txt = _re2.sub(r"^```json|```$","",txt).strip()
        m = _re2.search(r"\[.*?\]", txt, _re2.S)
        txt = m.group(0) if m else txt
        scores = _json.loads(txt)
        for i, c in enumerate(items):
            c["big_score"] = scores[i] if i < len(scores) else 5
    except Exception as e:
        print("[bigissue] err", e)
        for c in items: c["big_score"] = 7
    return items

def _claude_translate_titles(items):
    """트렌드 카드 제목+헤드라인을 한국어로 번역. 개별 매칭 + 폴백."""
    import os as _os, json as _json, re as _re3
    key = _os.environ.get("ANTHROPIC_API_KEY", "")
    # 기본값: 원문 (실패해도 최소한 원문 유지)
    for c in items:
        c.setdefault("title_ko", c["title"])
        c.setdefault("headline_ko", c.get("headline", ""))
    if not key or not items:
        return items
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=key)
        print(f"[translate] calling model={_os.environ.get('CLAUDE_MODEL','claude-sonnet-4-6')} for {len(items)} items")
        entries = []
        for i, c in enumerate(items):
            hl = (c.get("headline") or "")[:100]
            entries.append(f'[{i}] 제목: {c["title"]}\n    요약: {hl}')
        lst = "\n".join(entries)
        msg = client.messages.create(
            model=_os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
            max_tokens=1500,
            system="""You translate news items into natural Korean for a Korean audience.
For EACH item you MUST translate BOTH the title AND the summary(요약) into Korean.
The summary must NOT stay in English — always translate it fully to Korean.
Keep proper nouns (people/brand/place names) in common Korean form.
Return EXACTLY one object per input index, in order, covering every index.
Output ONLY a JSON array, no other text:
[{"i":0,"title":"한국어 제목","headline":"한국어 요약 문장"},{"i":1,"title":"...","headline":"..."}]
Only use "" for headline if the original summary was truly empty.""",
            messages=[{"role": "user", "content": lst}]
        )
        txt = "".join(b.text for b in msg.content if b.type == "text").strip()
        print(f"[translate] raw response len={len(txt)} preview={txt[:120]!r}")
        txt = _re3.sub(r"^```json|```$", "", txt).strip()
        m = _re3.search(r"\[.*\]", txt, _re3.S)
        if m: txt = m.group(0)
        results = _json.loads(txt)
        print(f"[translate] parsed {len(results)} items for {len(items)} inputs")
        # 인덱스 기반 매칭 (순서 어긋나도 안전)
        by_i = {}
        for r in results:
            if isinstance(r, dict) and "i" in r:
                by_i[int(r["i"])] = r
        for i, c in enumerate(items):
            r = by_i.get(i)
            if r:
                if r.get("title"):    c["title_ko"] = r["title"]
                hk = (r.get("headline") or "").strip()
                # 번역된 요약이 있으면 사용, 없으면 빈값(영어 노출 방지)
                c["headline_ko"] = hk if hk else ""
            else:
                c["headline_ko"] = ""  # 매칭 실패 시 영어 대신 빈값
    except Exception as e:
        print("[translate] err", e)
    return items

# ---------- 점수 조립 ----------
def score(clusters, category=None):
    for c in clusters:
        tag(c)
        c["trend_index"] = round(c["norm"] * c["vboost"], 1)
        c["confidence"] = round(1 + 0.5 * (len(c["sources"]) - 1), 2)
        rel = 1.0 if not category or category == "전체" else (1.0 if c["category"] == category else 0.15)
        c["relevance"] = rel
        c["final"] = round(c["trend_index"] * c["confidence"] * rel, 1)
    # 1단계: 기본 필터
    kept = [c for c in clusters if (c["velocity"] is None or c["velocity"] > -0.3) and c["norm"] >= 5]
    # 2단계: 하드 블랙리스트
    kept = [c for c in kept if not _is_blacklisted(c["title"], c.get("headline",""))]
    return sorted(kept, key=lambda x: x["final"], reverse=True)

def why(c):
    """'왜 떴는지' — 사실 기반 근거만."""
    bits = []
    src_ko = {"google_trends": "구글 트렌드 급상승", "wikipedia": "위키피디아 조회 급증", "gdelt": "글로벌 뉴스 다수 보도"}
    for s in c["sources"]:
        bits.append(src_ko.get(s, s))
    gt = next((i for i in c["items"] if i["source"] == "google_trends"), None)
    if gt and gt["magnitude"]:
        bits.append(f"대략 검색량 {int(gt['magnitude']):,}+")
    wk = next((i for i in c["items"] if i["source"] == "wikipedia"), None)
    if wk and wk["magnitude"]:
        bits.append(f"위키 조회 {int(wk['magnitude']):,}")
    if c["velocity"] is not None:
        bits.append(f"상승률 {c['velocity']*100:+.0f}%")
    if len(c["sources"]) >= 2:
        bits.append("복수 소스 동시 신호")
    return " · ".join(bits)

# ---------- 커피 전용 수집 ────────────────────────────
# 커피 경제·산업·시장 + 스페셜티 위주 키워드 (국내)
COFFEE_KEYWORDS = [
    "스페셜티 커피", "원두 가격", "커피 시장", "커피 산업",
    "스페셜티 로스터리", "생두 수입", "게이샤 커피", "커피 프랜차이즈",
]
# 해외(영문) 커피 뉴스 검색 쿼리 — 원산지·시세·글로벌 트렌드·산업
COFFEE_QUERY_EN = ('("specialty coffee" OR "coffee price" OR "coffee production" OR '
                   '"coffee harvest" OR "arabica price" OR "coffee industry" OR '
                   '"coffee origin")')

def fetch_coffee_news(per_kw=3):
    """커피 키워드로 네이버·카카오 뉴스를 검색해 트렌드 항목으로 변환 (국내).
    키워드별로 라운드로빈 인터리브 → 특정 키워드 편중 방지, 제목 중복 제거."""
    per_lists = []
    for kw in COFFEE_KEYWORDS:
        got = fetch_naver_news(kw, n=per_kw)
        if not got:
            got = fetch_kakao_news(kw, n=per_kw)
        per_lists.append(got)
    items, seen = [], set()
    for row in range(per_kw):
        for lst in per_lists:
            if row < len(lst):
                it = lst[row]
                k = _key(it["title"])[:60]
                if k and k not in seen:
                    seen.add(k)
                    items.append(it)
    print(f"[coffee] 국내 수집 {len(items)}건")
    return items

def fetch_google_news_rss(query, lang="en", n=12):
    """구글 뉴스 RSS 검색 — 키리스·안정적. 해외(영문/일문) 뉴스 확보용."""
    import urllib.parse as _u
    hl, gl, ceid = ("en-US", "US", "US:en") if lang == "en" else ("ja", "JP", "JP:ja")
    out = []
    try:
        url = (f"https://news.google.com/rss/search?q={_u.quote(query)}"
               f"&hl={hl}&gl={gl}&ceid={ceid}")
        r = requests.get(url, headers=UA, timeout=8)
        root = ET.fromstring(r.content)
        for it in root.findall(".//item")[:n]:
            title = (it.findtext("title") or "").strip()
            link  = (it.findtext("link") or "").strip()
            srcel = it.find("source")
            src_name = (srcel.text or "").strip() if srcel is not None else ""
            if title:
                out.append(dict(title=title, source="google_news", magnitude=1.0,
                                headline=src_name, url=link, geo="global"))
    except Exception as e:
        print("[gnews] err", e)
    return out

def fetch_coffee_news_foreign(limit=10):
    """해외(영문) 커피 뉴스 — 구글 뉴스 RSS 우선(안정), GDELT 백업.
    원산지·시세·글로벌 트렌드·산업 커버."""
    raw = fetch_google_news_rss(
        "specialty coffee OR coffee price OR coffee production OR arabica OR coffee industry OR coffee origin",
        lang="en", n=limit + 4)
    if len(raw) < 3:                      # RSS가 부실하면 GDELT로 보강
        raw += fetch_gdelt(COFFEE_QUERY_EN)
    seen, uniq = set(), []
    for it in raw:
        k = _key(it["title"])[:60]
        if k and k not in seen:
            seen.add(k)
            uniq.append(it)
    print(f"[coffee] 해외 수집 {len(uniq)}건")
    return uniq[:limit]

_coffee_tr_cache = {}   # {원문제목: {"title_ko":..,"headline_ko":..}} — 재번역 방지

def _run_coffee(n=6):
    """'커피' 카테고리 — 해외(구글뉴스/GDELT)를 메인 베이스로, 국내(네이버·카카오)는 보조.
    해외 기사는 제목을 한국어로 번역해 노출. 번역은 캐시해서 매번 재호출하지 않는다."""
    frn = fetch_coffee_news_foreign(limit=n)   # 필요한 만큼만 (번역 부담↓)
    dom = fetch_coffee_news()                  # 한국어 기사 (보조)

    # 해외 번역: 캐시에 있으면 재사용, 없는 것만 Claude로 번역
    if frn:
        todo = []
        for c in frn:
            hit = _coffee_tr_cache.get(c["title"])
            if hit:
                c["title_ko"] = hit["title_ko"]
                c["headline_ko"] = hit["headline_ko"]
            else:
                todo.append(c)
        if todo:
            try:
                translated = _claude_translate_titles(todo)
                for c in translated:
                    _coffee_tr_cache[c["title"]] = {
                        "title_ko": c.get("title_ko", c["title"]),
                        "headline_ko": c.get("headline_ko", c.get("headline", "")),
                    }
            except Exception as e:
                print("[coffee] 해외 번역 실패:", e)
                for c in todo:
                    c.setdefault("title_ko", c["title"])
                    c.setdefault("headline_ko", c.get("headline", ""))
        # 캐시 크기 제한 (메모리 보호)
        if len(_coffee_tr_cache) > 300:
            for k in list(_coffee_tr_cache)[:150]:
                _coffee_tr_cache.pop(k, None)
    # 국내는 이미 한국어
    for c in dom:
        c.setdefault("title_ko", c["title"])
        c.setdefault("headline_ko", c.get("headline", ""))

    # 해외를 앞에(메인), 국내는 뒤에(보조) — 제목 중복 제거
    mixed, seen = [], set()
    for it in frn + dom:
        k = _key(it["title"])[:60]
        if k and k not in seen:
            seen.add(k)
            mixed.append(it)

    out = []
    for rank, c in enumerate(mixed[:n], 1):
        blob = (c["title"] + " " + c.get("headline", "")).lower()
        sensitive = any(k in blob for k in SENSITIVE)
        src = c.get("source", "")
        is_foreign = src in ("gdelt", "google_news")
        src_ko = {"naver_news": "네이버 뉴스", "kakao_news": "카카오 뉴스",
                  "gdelt": "해외 뉴스", "google_news": "해외 뉴스"}.get(src, src)
        out.append(dict(
            rank=rank, title=c["title"],
            title_ko=c.get("title_ko", c["title"]),
            headline=c.get("headline", ""),
            headline_ko=c.get("headline_ko", c.get("headline", "")),
            url=c.get("url", ""),
            category="커피", sensitive=sensitive,
            trend_index=round(50 - rank, 1), confidence=1.0,
            final=round(50 - rank, 1), velocity=None,
            sources=[src] if src else ["naver_news"],
            geo=c.get("geo", "KR"),
            wiki_lang=("en" if is_foreign else "ko"),
            why=f"{src_ko} · 커피 키워드 검색" + (" · 해외" if is_foreign else ""),
        ))
    return out

# ---------- 파이프라인 진입점 ----------
# 지역 프리셋: 한국 관심사 중심으로 다국가 혼합
REGION_PRESETS = {
    "GLOBAL_KR": [("KR", "ko"), ("KR", "en"), ("US", "en"), ("GB", "en"), ("JP", "en")],
    "US":  [("US", "en")],
    "KR":  [("KR", "ko"), ("KR", "en")],
    "GB":  [("GB", "en")],
    "JP":  [("JP", "ja"), ("JP", "en")],
}
KR_NAVER_ENABLED = True   # 네이버/카카오 국내 소스 사용 여부

def run(geo="GLOBAL_KR", category="전체", n=6, wiki_lang="en"):
    # '커피' 카테고리는 실시간 트렌드에 안 잡히므로 전용 뉴스 검색으로 분기
    if category == "커피":
        return _run_coffee(n)

    regions = REGION_PRESETS.get(geo, [(geo, wiki_lang)])
    raw = []
    seen_geo = set()
    for g, lang in regions:
        raw += fetch_google_trends(g)
        if lang not in seen_geo:
            raw += fetch_wikipedia(lang)
            seen_geo.add(lang)
    raw += fetch_gdelt()
    # 국내 소스: KR 지역이 포함된 경우 네이버·카카오 추가
    is_kr = any(g == "KR" for g, _ in regions)
    if is_kr:
        raw += fetch_naver_datalab()
        raw += fetch_naver_news("오늘 주요 뉴스 이슈")
        raw += fetch_kakao_news("오늘 화제")
    raw = percentile_normalize(raw)
    clusters = cluster(raw)
    clusters = apply_velocity(clusters)
    ranked = score(clusters, None if category in (None, "전체") else category)
    # 3단계: Claude 빅이슈 스코어링 (상위 15개만 채점해서 API 절약)
    candidates = ranked[:15]
    candidates = _claude_bigissue_score(candidates)
    ranked = [c for c in candidates if c.get("big_score", 7) >= 7] + ranked[15:]
    ranked = sorted(ranked[:20], key=lambda x: (x.get("big_score",5), x["final"]), reverse=True)
    top = ranked[:n]
    try:
        top = _claude_translate_titles(top)
    except Exception as e:
        print("[translate] failed:", e)
        for c in top:
            c.setdefault("title_ko", c["title"])
            c.setdefault("headline_ko", c.get("headline",""))
    out = []
    for i, c in enumerate(top, 1):
        out.append(dict(
            rank=i, title=c["title"], title_ko=c.get("title_ko", c["title"]),
            headline=c.get("headline", ""),
            headline_ko=c.get("headline_ko", c.get("headline","")),
            url=c.get("url", ""),
            category=c["category"], sensitive=c["sensitive"],
            trend_index=c["trend_index"], confidence=c["confidence"],
            final=c["final"], velocity=c["velocity"], sources=sorted(c["sources"]),
            why=why(c),
        ))
    return out

if __name__ == "__main__":
    import sys
    cat = sys.argv[1] if len(sys.argv) > 1 else "전체"
    for r in run(category=cat, n=8):
        flag = "⚠사실전달" if r["sensitive"] else "  "
        print(f"{r['rank']}. [{r['category']}]{flag} {r['title']}  (지수 {r['trend_index']} · 확신 {r['confidence']} · 최종 {r['final']})")
        print(f"    왜: {r['why']}")


# ── 네이버 데이터랩: 국내 검색 트렌드 ─────────────────
def fetch_naver_datalab():
    """네이버 데이터랩으로 국내 인기 검색어 그룹 트렌드 수집."""
    import os as _os, datetime as _dt
    cid = _os.environ.get("NAVER_CLIENT_ID","")
    sec = _os.environ.get("NAVER_CLIENT_SECRET","")
    if not (cid and sec):
        return []
    today = _dt.date.today()
    start = (today - _dt.timedelta(days=7)).strftime("%Y-%m-%d")
    end   = today.strftime("%Y-%m-%d")
    # 국내 주요 키워드 그룹 (트렌드 신호)
    groups = [
        {"groupName":"경제·증시","keywords":["코스피","환율","금리","증시","주식"]},
        {"groupName":"정치","keywords":["대통령","국회","정부","선거","여당","야당"]},
        {"groupName":"연예·문화","keywords":["드라마","영화","아이돌","K팝","콘서트"]},
        {"groupName":"스포츠","keywords":["야구","축구","NBA","EPL","올림픽"]},
        {"groupName":"IT·기술","keywords":["AI","반도체","삼성","애플","카카오"]},
    ]
    out = []
    try:
        hdrs = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec,
                "Content-Type": "application/json", "User-Agent": "trendcast/0.3"}
        r = requests.post("https://openapi.naver.com/v1/datalab/search",
            json={"startDate": start, "endDate": end, "timeUnit": "date",
                  "keywordGroups": groups},
            headers=hdrs, timeout=12)
        if r.status_code == 200:
            for res in r.json().get("results", []):
                name = res.get("title","")
                data = res.get("data",[])
                if not data: continue
                # 최근 3일 평균 vs 그 이전 4일 평균 → 상승률 계산
                recent  = [d["ratio"] for d in data[-3:]]
                earlier = [d["ratio"] for d in data[:4]]
                avg_r = sum(recent)/len(recent)   if recent  else 0
                avg_e = sum(earlier)/len(earlier) if earlier else 0
                velocity = (avg_r - avg_e) / max(avg_e, 1)
                out.append(dict(title=name, source="naver_datalab",
                                magnitude=avg_r * (1 + velocity),
                                headline=f"네이버 국내 검색 트렌드 · 최근 지수 {avg_r:.1f}",
                                geo="KR"))
        else:
            print("[naver_datalab] status", r.status_code, r.text[:80])
    except Exception as e:
        print("[naver_datalab] err", e)
    return out


# ── 네이버 뉴스 검색: 실시간 국내 뉴스 헤드라인 ─────────
def fetch_naver_news(query="오늘 주요 뉴스", n=10):
    """네이버 뉴스 검색 API — 국내 기사 제목·링크."""
    import os as _os
    cid = _os.environ.get("NAVER_CLIENT_ID","")
    sec = _os.environ.get("NAVER_CLIENT_SECRET","")
    if not (cid and sec):
        return []
    out = []
    try:
        r = requests.get("https://openapi.naver.com/v1/search/news.json",
            params={"query": query, "display": n, "sort": "date"},
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec,
                     "User-Agent": "trendcast/0.3"},
            timeout=10)
        if r.status_code == 200:
            import re as _re2, html as _html2
            def _nc(t):
                t = _html2.unescape(t or "")
                return _re2.sub(r"<[^>]+>","",t).strip()
            for item in r.json().get("items", [])[:n]:
                title = _nc(item.get("title",""))
                desc  = _nc(item.get("description",""))
                if title:
                    out.append(dict(title=title, source="naver_news",
                                    magnitude=50.0,
                                    headline=desc[:100], geo="KR",
                                    url=item.get("originallink","")))
        elif r.status_code == 401:
            print("[naver_news] 401 — developers.naver.com 앱 설정에서 '검색' API를 사용 API에 추가하세요")
        else:
            print("[naver_news] status", r.status_code)
    except Exception as e:
        print("[naver_news] err", e)
    return out


# ── 카카오 뉴스 검색: 국내 뉴스 보완 ─────────────────────
def fetch_kakao_news(query="오늘 뉴스", n=5):
    """카카오 검색 API — 뉴스 검색."""
    import os as _os
    key = _os.environ.get("KAKAO_REST_API_KEY","")
    if not key:
        return []
    out = []
    try:
        r = requests.get("https://dapi.kakao.com/v2/search/web",
            params={"query": query + " 뉴스", "size": n},
            headers={"Authorization": f"KakaoAK {key}",
                     "User-Agent": "trendcast/0.3"},
            timeout=10)
        if r.status_code == 200:
            import re as _re3, html as _html3
            def _kc(t):
                t = _html3.unescape(t or "")
                return _re3.sub(r"<[^>]+>","",t).strip()
            for d in r.json().get("documents",[])[:n]:
                title = _kc(d.get("title",""))
                if title:
                    out.append(dict(title=title, source="kakao_news",
                                    magnitude=45.0,
                                    headline=_kc(d.get("contents",""))[:100],
                                    geo="KR", url=d.get("url","")))
        else:
            print("[kakao_news] status", r.status_code)
    except Exception as e:
        print("[kakao_news] err", e)
    return out
