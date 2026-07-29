# -*- coding: utf-8 -*-
"""
발행 어댑터 (반자동). 실제 발행은 자격증명 필요.
필요 환경변수: META_ACCESS_TOKEN, IG_USER_ID, THREADS_USER_ID, PUBLIC_IMAGE_BASE
"""
import os, requests

GRAPH   = "https://graph.facebook.com/v21.0"
THREADS = "https://graph.threads.net/v1.0"

def _creds():
    return dict(token=os.environ.get("META_ACCESS_TOKEN"),
                ig=os.environ.get("IG_USER_ID"),
                th=os.environ.get("THREADS_USER_ID"),
                base=(os.environ.get("PUBLIC_IMAGE_BASE","") or "").rstrip("/"))

def _abs(url, base):
    """상대경로 이미지 URL을 공개 절대 URL로."""
    if url.startswith("http"):
        return url
    if base:
        return base + url if url.startswith("/") else f"{base}/{url}"
    return url  # base 없으면 그대로 (실패 유도 → 에러 메시지로 안내)

def _err(resp):
    """Graph API 에러 메시지를 사람이 읽을 수 있게 추출."""
    try:
        j = resp.json()
        if "error" in j:
            e = j["error"]
            return f"{e.get('message','')} (code {e.get('code','')})"
    except Exception:
        pass
    return resp.text[:200]

def publish_instagram(image_urls, caption):
    c = _creds()
    if not (c["token"] and c["ig"]):
        return {"status": "dry_run", "platform": "instagram",
                "reason": "META_ACCESS_TOKEN / IG_USER_ID 미설정",
                "would_post": {"caption": caption, "images": image_urls}}
    if not c["base"]:
        return {"status": "error", "platform": "instagram",
                "error": "PUBLIC_IMAGE_BASE 미설정 — 인스타는 공개 이미지 URL이 필요합니다. "
                         "Railway에 PUBLIC_IMAGE_BASE=https://<앱주소> 를 추가하세요."}
    urls = [_abs(u, c["base"]) for u in image_urls]
    print("[publish-ig] image urls:", urls)
    try:
        # 1) 각 이미지 캐러셀 아이템 컨테이너
        children = []
        for u in urls:
            r = requests.post(f"{GRAPH}/{c['ig']}/media",
                data={"image_url": u, "is_carousel_item": "true",
                      "access_token": c["token"]}, timeout=30)
            j = r.json()
            print(f"[publish-ig] container resp for {u}: {j}")
            if "id" not in j:
                return {"status": "error", "platform": "instagram",
                        "error": f"이미지 컨테이너 생성 실패: {_err(r)}", "image": u,
                        "hint": "이미지 URL이 공개 접근 가능한지, JPG인지 확인"}
            children.append(j["id"])
        # 2) 캐러셀 컨테이너
        r = requests.post(f"{GRAPH}/{c['ig']}/media",
            data={"media_type": "CAROUSEL", "children": ",".join(children),
                  "caption": caption, "access_token": c["token"]}, timeout=30)
        j = r.json()
        if "id" not in j:
            return {"status": "error", "platform": "instagram",
                    "error": f"캐러셀 생성 실패: {_err(r)}"}
        cont = j["id"]
        # 3) 발행
        pub = requests.post(f"{GRAPH}/{c['ig']}/media_publish",
            data={"creation_id": cont, "access_token": c["token"]}, timeout=30)
        pj = pub.json()
        if "id" not in pj:
            return {"status": "error", "platform": "instagram",
                    "error": f"발행 실패: {_err(pub)}"}
        return {"status": "published", "platform": "instagram", "result": pj}
    except Exception as e:
        return {"status": "error", "platform": "instagram", "error": str(e)}

def publish_threads(image_urls, text):
    c = _creds()
    if not (c["token"] and c["th"]):
        return {"status": "dry_run", "platform": "threads",
                "reason": "META_ACCESS_TOKEN / THREADS_USER_ID 미설정",
                "would_post": {"text": text, "images": image_urls}}
    urls = [_abs(u, c["base"]) for u in image_urls]
    try:
        r = requests.post(f"{THREADS}/{c['th']}/threads",
            data={"media_type": "IMAGE", "image_url": urls[0],
                  "text": text, "access_token": c["token"]}, timeout=30)
        j = r.json()
        if "id" not in j:
            return {"status": "error", "platform": "threads",
                    "error": f"스레드 컨테이너 실패: {_err(r)}"}
        pub = requests.post(f"{THREADS}/{c['th']}/threads_publish",
            data={"creation_id": j["id"], "access_token": c["token"]}, timeout=30)
        pj = pub.json()
        if "id" not in pj:
            return {"status": "error", "platform": "threads",
                    "error": f"스레드 발행 실패: {_err(pub)}"}
        return {"status": "published", "platform": "threads", "result": pj}
    except Exception as e:
        return {"status": "error", "platform": "threads", "error": str(e)}
