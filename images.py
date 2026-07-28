# -*- coding: utf-8 -*-
"""
Unsplash 분위기 이미지 수집.
키를 모듈 로드 시점이 아니라 매 호출 시점에 읽어서
Railway 환경변수 변경 후 재배포 없이도 반영.
"""
import os, re, requests

UA = {"User-Agent": "trendcast/0.2"}

CAT_QUERY = {
    "경제·금융": "finance stock market trading",
    "정치":      "government capitol building politics",
    "문화·연예": "cinema stage spotlight dramatic",
    "스포츠":    "stadium sports crowd action",
    "기술·IT":   "technology digital abstract neon",
    "기타":      "abstract minimal modern",
}

def _key():
    return os.environ.get("UNSPLASH_ACCESS_KEY", "")

def _keyword_from_claude(title, category):
    """Claude가 주제 보고 Unsplash 키워드 2~4단어 생성."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
            max_tokens=30,
            system="Output ONLY 2-4 English words for an Unsplash photo search that captures the visual mood of the topic. No explanation, no quotes.",
            messages=[{"role": "user", "content": f"Topic: {title}\nCategory: {category}"}]
        )
        kw = "".join(b.text for b in msg.content if b.type == "text").strip()
        kw = re.sub(r"[^a-z0-9 ]", "", kw.lower()).strip()
        return kw or None
    except Exception as e:
        print("[unsplash] keyword err", e)
        return None

def fetch_image(title="", category="기타", orientation="portrait"):
    """Unsplash 랜덤 이미지 URL 반환. 키 없으면 None."""
    key = _key()
    if not key:
        print("[unsplash] UNSPLASH_ACCESS_KEY not set")
        return None
    query = _keyword_from_claude(title, category) or CAT_QUERY.get(category, "abstract minimal")
    print(f"[unsplash] fetching: query='{query}'")
    try:
        r = requests.get(
            "https://api.unsplash.com/photos/random",
            params=dict(query=query, orientation=orientation, content_filter="high"),
            headers={**UA, "Authorization": f"Client-ID {key}"},
            timeout=10
        )
        if r.status_code == 200:
            d = r.json()
            return dict(
                url=d["urls"]["regular"],
                full=d["urls"]["full"],
                thumb=d["urls"]["small"],
                author=d["user"]["name"],
                author_url=d["user"]["links"]["html"],
                query_used=query,
            )
        print("[unsplash] status", r.status_code, r.text[:120])
    except Exception as e:
        print("[unsplash] fetch err", e)
    return None

def search_images(query, n=6):
    """편집기 이미지 교체용 검색."""
    key = _key()
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params=dict(query=query, per_page=n, orientation="portrait", content_filter="high"),
            headers={**UA, "Authorization": f"Client-ID {key}"},
            timeout=10
        )
        if r.status_code == 200:
            return [dict(url=p["urls"]["regular"], thumb=p["urls"]["small"],
                         author=p["user"]["name"]) for p in r.json().get("results", [])]
    except Exception as e:
        print("[unsplash] search err", e)
    return []
