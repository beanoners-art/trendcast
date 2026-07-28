# -*- coding: utf-8 -*-
"""
발행 어댑터 (반자동: 사람이 선택/승인 후 호출).
실제 발행은 계정 소유자의 자격증명이 있어야 동작한다. 없으면 dry-run으로
'무엇을 올릴지'만 반환한다. 남의 계정 대량 자동 포스팅은 지원하지 않는다.

필요 환경변수(.env):
  META_ACCESS_TOKEN   : 장기 사용자 토큰
  IG_USER_ID          : 인스타 비즈니스/크리에이터 계정 ID
  THREADS_USER_ID     : 스레드 계정 ID
  PUBLIC_IMAGE_BASE   : 이미지가 공개 접근 가능한 URL 베이스 (Graph API는 공개 URL 필요)
"""
import os, requests

GRAPH = "https://graph.facebook.com/v21.0"
THREADS = "https://graph.threads.net/v1.0"

def _creds():
    return dict(token=os.environ.get("META_ACCESS_TOKEN"),
                ig=os.environ.get("IG_USER_ID"),
                th=os.environ.get("THREADS_USER_ID"),
                base=os.environ.get("PUBLIC_IMAGE_BASE"))

def publish_instagram(image_urls, caption):
    """인스타 캐러셀 발행: 1) 각 이미지 컨테이너 2) 캐러셀 컨테이너 3) publish."""
    c = _creds()
    if not (c["token"] and c["ig"]):
        return {"status": "dry_run", "platform": "instagram",
                "reason": "META_ACCESS_TOKEN / IG_USER_ID 미설정",
                "would_post": {"caption": caption, "images": image_urls}}
    try:
        children = []
        for u in image_urls:
            r = requests.post(f"{GRAPH}/{c['ig']}/media",
                              data={"image_url": u, "is_carousel_item": "true", "access_token": c["token"]})
            children.append(r.json()["id"])
        r = requests.post(f"{GRAPH}/{c['ig']}/media",
                          data={"media_type": "CAROUSEL", "children": ",".join(children),
                                "caption": caption, "access_token": c["token"]})
        cont = r.json()["id"]
        pub = requests.post(f"{GRAPH}/{c['ig']}/media_publish",
                            data={"creation_id": cont, "access_token": c["token"]})
        return {"status": "published", "platform": "instagram", "result": pub.json()}
    except Exception as e:
        return {"status": "error", "platform": "instagram", "error": str(e)}

def publish_threads(image_urls, text):
    c = _creds()
    if not (c["token"] and c["th"]):
        return {"status": "dry_run", "platform": "threads",
                "reason": "META_ACCESS_TOKEN / THREADS_USER_ID 미설정",
                "would_post": {"text": text, "images": image_urls}}
    try:
        # 단일 이미지(또는 대표 1장) 예시. 캐러셀은 CAROUSEL 타입으로 확장.
        r = requests.post(f"{THREADS}/{c['th']}/threads",
                          data={"media_type": "IMAGE", "image_url": image_urls[0],
                                "text": text, "access_token": c["token"]})
        cid = r.json()["id"]
        pub = requests.post(f"{THREADS}/{c['th']}/threads_publish",
                            data={"creation_id": cid, "access_token": c["token"]})
        return {"status": "published", "platform": "threads", "result": pub.json()}
    except Exception as e:
        return {"status": "error", "platform": "threads", "error": str(e)}
