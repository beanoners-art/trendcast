# -*- coding: utf-8 -*-
"""
트렌드 수집·점수화 엔진 (키리스 소스 중심)
흐름: 수집 → 소스내 정규화 → 이슈 클러스터링 → 트렌드지수(속도, 1차 게이트)
      → 관련성 × 소스교차 확신도 (2차 점수) → 카테고리/브랜드세이프티 태깅 → 랭킹
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
        txt = _re2.sub(r"^```json|```$","",txt).strip()
        scores = _json.loads(txt)
        for i, c in enumerate(items):
            c["big_score"] = scores[i] if i < len(scores) else 5
    except Exception as e:
        print("[bigissue] err", e)
        for c in items: c["big_score"] = 7
    return items

def _claude_translate_titles(items):
    """트렌드 카드 제목을 짧은 한국어로 번역. 키 없으면 원문 유지."""
    import os as _os, json as _json, re as _re3
    key = _os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or not items:
        for c in items: c["title_ko"] = c["title"]
        return items
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=key)
        lst = "\n".join(f"{i+1}. {c['title']}" for i, c in enumerate(items))
        msg = client.messages.create(
            model=_os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
            max_tokens=600,
            system="Translate each item to a short natural Korean title (keep proper nouns; people/brand names can stay or use common Korean form). Output ONLY a JSON array of strings, same order.",
            messages=[{"role": "user", "content": lst}]
        )
        txt = "".join(b.text for b in msg.content if b.type == "text").strip()
        txt = _re3.sub(r"^```json|```$", "", txt).strip()
        kos = _json.loads(txt)
        for i, c in enumerate(items):
            c["title_ko"] = kos[i] if i < len(kos) else c["title"]
    except Exception as e:
        print("[translate] err", e)
        for c in items: c["title_ko"] = c["title"]
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

# ---------- 파이프라인 진입점 ----------
# 지역 프리셋: 한국 관심사 중심으로 다국가 혼합
REGION_PRESETS = {
    "GLOBAL_KR": [("KR", "ko"), ("KR", "en"), ("US", "en"), ("GB", "en"), ("JP", "en")],
    "US":  [("US", "en")],
    "KR":  [("KR", "ko"), ("KR", "en")],
    "GB":  [("GB", "en")],
    "JP":  [("JP", "ja"), ("JP", "en")],
}

def run(geo="GLOBAL_KR", category="전체", n=6, wiki_lang="en"):
    # 다지역 수집: geo가 프리셋이면 여러 나라 트렌드+위키를 합침
    regions = REGION_PRESETS.get(geo, [(geo, wiki_lang)])
    raw = []
    seen_geo = set()
    for g, lang in regions:
        raw += fetch_google_trends(g)
        if lang not in seen_geo:
            raw += fetch_wikipedia(lang)
            seen_geo.add(lang)
    raw += fetch_gdelt()
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
    top = _claude_translate_titles(top)   # 제목 한글화
    out = []
    for i, c in enumerate(top, 1):
        out.append(dict(
            rank=i, title=c["title"], title_ko=c.get("title_ko", c["title"]),
            headline=c.get("headline", ""), url=c.get("url", ""),
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
