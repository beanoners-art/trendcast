# -*- coding: utf-8 -*-
"""
Unsplash 분위기 이미지 수집.
- Claude(또는 폴백 로직)가 주제에 맞는 영어 키워드를 결정
- Unsplash API로 고해상도 사진 URL 반환
- UNSPLASH_ACCESS_KEY 없으면 카테고리별 기본 쿼리로 fallback
"""
import os, re, requests

UA = {"User-Agent": "trendcast/0.2"}
UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

# 카테고리별 기본 분위기 키워드 (키 없어도 동작하게 fallback)
CAT_QUERY = {
    "경제·금융": "finance stock market city",
    "정치":      "government parliament city architecture",
    "문화·연예": "cinema theater stage dramatic",
    "스포츠":    "stadium sports crowd action",
    "기술·IT":   "technology digital abstract neon",
    "기타":      "abstract minimal modern",
}

def _keyword_from_claude(title, category):
    """Claude가 주제 보고 Unsplash 검색 키워드 생성 (API키 있을 때)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=key)
        msg = client.messages.create(
            model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5"),
            max_tokens=60,
            system="You output ONLY a 2-4 word Unsplash search query in English that captures the visual mood/theme of the given topic. No explanation, no quotes, just the keywords.",
            messages=[{"role": "user", "content": f"Topic: {title}\nCategory: {category}"}]
        )
        kw = "".join(b.text for b in msg.content if b.type == "text").strip()
        kw = re.sub(r"[^a-z0-9 ]", "", kw.lower()).strip()
        return kw if kw else None
    except Exception as e:
        print("[unsplash] keyword err", e)
        return None

def fetch_image(title="", category="기타", orientation="portrait"):
    """
    Unsplash에서 주제에 맞는 이미지 URL 반환.
    Returns: dict(url, thumb, author, author_url) or None
    """
    if not UNSPLASH_KEY:
        return None   # 키 없으면 배경 없음 (코드가 graceful하게 처리)

    query = _keyword_from_claude(title, category) or CAT_QUERY.get(category, "abstract minimal")
    try:
        r = requests.get(
            "https://api.unsplash.com/photos/random",
            params=dict(query=query, orientation=orientation, content_filter="high"),
            headers={**UA, "Authorization": f"Client-ID {UNSPLASH_KEY}"},
            timeout=8
        )
        if r.status_code == 200:
            d = r.json()
            return dict(
                url=d["urls"]["regular"],      # ~1080px wide
                full=d["urls"]["full"],
                thumb=d["urls"]["small"],
                author=d["user"]["name"],
                author_url=d["user"]["links"]["html"],
                query_used=query,
            )
        print("[unsplash] status", r.status_code, r.text[:80])
    except Exception as e:
        print("[unsplash] fetch err", e)
    return None

def search_images(query, n=6):
    """편집기에서 이미지 교체 시 검색용."""
    if not UNSPLASH_KEY:
        return []
    try:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params=dict(query=query, per_page=n, orientation="portrait", content_filter="high"),
            headers={**UA, "Authorization": f"Client-ID {UNSPLASH_KEY}"},
            timeout=8
        )
        if r.status_code == 200:
            return [dict(url=p["urls"]["regular"], thumb=p["urls"]["small"],
                         author=p["user"]["name"]) for p in r.json().get("results", [])]
    except Exception as e:
        print("[unsplash] search err", e)
    return []
