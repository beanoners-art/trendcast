# -*- coding: utf-8 -*-
"""
이미지 수집 v2 — Pexels + Unsplash 병행.
- fetch_bg(): 전 장에 깔릴 통일 배경 1장
- fetch_content_images(): 슬라이드 본문에 삽입할 사진 여러 장 (키워드별)
키는 호출 시점에 읽음(재배포 없이 반영).
"""
import os, re, requests

UA = {"User-Agent": "trendcast/0.3"}

def _ukey(): return os.environ.get("UNSPLASH_ACCESS_KEY", "")
def _pkey(): return os.environ.get("PEXELS_API_KEY", "")

CAT_QUERY = {
    "경제·금융": "finance city skyline night",
    "정치":      "capitol architecture columns",
    "문화·연예": "cinema spotlight stage",
    "스포츠":    "stadium lights crowd",
    "기술·IT":   "technology abstract circuit",
    "기타":      "abstract texture minimal",
}

def _pexels_search(query, n=3, orientation="portrait"):
    key = _pkey()
    if not key: return []
    try:
        r = requests.get("https://api.pexels.com/v1/search",
            params=dict(query=query, per_page=n, orientation=orientation),
            headers={**UA, "Authorization": key}, timeout=10)
        if r.status_code == 200:
            return [dict(url=p["src"]["large"], thumb=p["src"]["medium"],
                         author=p.get("photographer",""), src="pexels")
                    for p in r.json().get("photos", [])]
        print("[pexels] status", r.status_code, r.text[:80])
    except Exception as e:
        print("[pexels] err", e)
    return []

def _unsplash_search(query, n=3, orientation="portrait"):
    key = _ukey()
    if not key: return []
    try:
        r = requests.get("https://api.unsplash.com/search/photos",
            params=dict(query=query, per_page=n, orientation=orientation,
                        content_filter="high"),
            headers={**UA, "Authorization": f"Client-ID {key}"}, timeout=10)
        if r.status_code == 200:
            return [dict(url=p["urls"]["regular"], thumb=p["urls"]["small"],
                         author=p["user"]["name"], src="unsplash")
                    for p in r.json().get("results", [])]
        print("[unsplash] status", r.status_code, r.text[:80])
    except Exception as e:
        print("[unsplash] err", e)
    return []

def search_images(query, n=6, orientation="portrait"):
    """Pexels + Unsplash 합산 검색 (편집기 교체용으로도 사용)."""
    out = _pexels_search(query, n//2 + 1, orientation) + \
          _unsplash_search(query, n//2 + 1, orientation)
    return out[:n]

def _claude_keywords(title, category, n_slides):
    """Claude가 배경 1개 + 슬라이드용 키워드 목록 생성."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key: return None
    try:
        from anthropic import Anthropic
        import json as _json
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
            max_tokens=250,
            system=("For a Korean card-news carousel about the given topic, output photo search "
                    "keywords. JSON only: {\"bg\": \"2-4 words for one unified atmospheric background\", "
                    "\"slides\": [\"2-4 words each, one per content slide, varied and specific to that "
                    "slide's likely content\"]}. English keywords. No text/logo/person-closeup subjects."),
            messages=[{"role": "user",
                       "content": f"Topic: {title}\nCategory: {category}\nSlides: {n_slides}"}])
        txt = "".join(b.text for b in msg.content if b.type == "text").strip()
        txt = re.sub(r"^```json|```$", "", txt).strip()
        return _json.loads(txt)
    except Exception as e:
        print("[imgkw] err", e)
        return None

def fetch_bg(title="", category="기타"):
    """통일 배경 1장."""
    kw = None
    plan = _claude_keywords(title, category, 1)
    if plan: kw = plan.get("bg")
    kw = kw or CAT_QUERY.get(category, "abstract texture")
    res = search_images(kw, 2, "portrait")
    print(f"[bg] query='{kw}' → {len(res)} results")
    return res[0] if res else None

def fetch_slide_images(title="", category="기타", n_slides=8):
    """슬라이드 본문 삽입용 사진 계획: 슬라이드별 키워드 → 사진 1장씩."""
    plan = _claude_keywords(title, category, n_slides)
    kws = (plan or {}).get("slides") or []
    # 부족하면 카테고리 기본으로 채움
    base = CAT_QUERY.get(category, "abstract minimal")
    while len(kws) < n_slides:
        kws.append(base)
    out = []
    for kw in kws[:n_slides]:
        res = search_images(kw, 1, "landscape")
        out.append(res[0] if res else None)
    got = sum(1 for x in out if x)
    print(f"[slide-imgs] {got}/{n_slides} images")
    return out
