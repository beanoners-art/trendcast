# -*- coding: utf-8 -*-
import os, re, secrets
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv

import engine, llm, render_carousel, publish, enrich, images

load_dotenv()

# ── 간단 비밀번호 인증 (미들웨어) ──────────────────
# APP_USERNAME / APP_PASSWORD 가 설정된 경우에만 활성화.
# /outputs (생성 이미지)는 인스타 발행용 공개 URL이 필요하므로 인증 제외.
import base64 as _b64
_PUBLIC_PREFIXES = ("/outputs",)

def _check_basic(header):
    user = os.environ.get("APP_USERNAME", "")
    pw   = os.environ.get("APP_PASSWORD", "")
    if not (user and pw):
        return True
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = _b64.b64decode(header[6:]).decode("utf-8")
        u, p = decoded.split(":", 1)
    except Exception:
        return False
    return secrets.compare_digest(u, user) and secrets.compare_digest(p, pw)
BASE = os.path.dirname(__file__)
OUT  = os.path.join(BASE, "outputs")
os.makedirs(OUT, exist_ok=True)

app = FastAPI(title="Trendcast")

@app.middleware("http")
async def _auth_mw(request: Request, call_next):
    path = request.url.path
    if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)
    if not _check_basic(request.headers.get("Authorization", "")):
        from fastapi.responses import Response
        return Response(status_code=401, content="인증이 필요합니다",
                        headers={"WWW-Authenticate": "Basic"})
    return await call_next(request)
app.mount("/static",  StaticFiles(directory=os.path.join(BASE,"static")), name="static")

@app.api_route("/outputs/{fname}", methods=["GET", "HEAD"])
def serve_output(fname: str):
    # 인스타/스레드가 가져갈 수 있는 공개 이미지 서빙 (인증 예외)
    # GET/HEAD 모두 허용 — Meta 이미지 수집기가 HEAD로 선점검(preflight)하기 때문.
    safe = os.path.basename(fname)
    p = os.path.join(OUT, safe)
    if os.path.isfile(p):
        media = "image/jpeg" if safe.lower().endswith((".jpg",".jpeg")) else "image/png"
        return FileResponse(p, media_type=media)
    return JSONResponse({"detail": "not found"}, status_code=404)

@app.get("/", response_class=HTMLResponse)
def home():
    return open(os.path.join(BASE,"static","index.html"), encoding="utf-8").read()

@app.get("/api/trends")
def trends(geo: str="US", category: str="전체", n: int=6, wiki_lang: str="en"):
    return {"items": engine.run(geo=geo, category=category, n=n, wiki_lang=wiki_lang)}

# ── generate ──────────────────────────────────────────────
def _generate_sync(t):
    sens     = t.get("sensitive", False)
    material = enrich.gather(t, lang=t.get("wiki_lang","en"))
    copy     = llm.localize(t, material=material, sensitive=sens)
    n_slides = len(copy.get("slides", []))
    title    = t.get("title","")
    cat      = t.get("category","기타")
    bg       = images.fetch_bg(title, cat)
    simgs    = images.fetch_slide_images(title, cat, n_slides)
    slug     = re.sub(r"[^a-z0-9]+"," ",title.lower())[:24].strip().replace(" ","-") or "trend"
    paths    = render_carousel.render(copy, OUT, sensitive=sens, slug=slug,
                                      bg_url=(bg or {}).get("url"), slide_imgs=simgs)
    urls     = ["/outputs/"+os.path.basename(p) for p in paths]
    src      = material.get("url","")
    caption  = (f"{copy['ko_title']}\n\n{copy.get('why_ko','')}\n\n"
                f"(사실 전달 · 출처 확인{' · '+src if src else ''})")
    return {"copy": copy, "images": urls, "caption": caption,
            "img_credit": bg, "bg_url": (bg or {}).get("url"),
            "slide_imgs": [ (s or {}).get("url") for s in simgs ]}

@app.post("/api/generate")
async def generate(req: Request):
    return await run_in_threadpool(_generate_sync, await req.json())

# ── re-render (editor apply) ──────────────────────────────
def _rerender_sync(t):
    copy     = {"ko_title": t.get("ko_title",""), "why_ko": t.get("why_ko",""),
                "slides": t.get("slides",[])}
    sens     = t.get("sensitive", False)
    bg_url   = t.get("bg_url") or t.get("img_url")
    simg_urls= t.get("slide_imgs") or []
    simgs    = [ (dict(url=u) if u else None) for u in simg_urls ]
    slug     = re.sub(r"[^a-z0-9]+"," ",t.get("ko_title","edit").lower())[:20].strip().replace(" ","-")+"-ed"
    paths    = render_carousel.render(copy, OUT, sensitive=sens, slug=slug,
                                      bg_url=bg_url, slide_imgs=simgs)
    return {"images": ["/outputs/"+os.path.basename(p) for p in paths]}

@app.post("/api/rerender")
async def rerender(req: Request):
    return await run_in_threadpool(_rerender_sync, await req.json())

# ── image search (editor swap) ────────────────────────────
@app.get("/api/images/search")
def image_search(q: str="", n: int=6):
    return {"results": images.search_images(q, n)}

# ── 인스타 규격 리사이즈 (발행용 1080px JPG) ──────────
def _make_publish_images(image_urls):
    """2x PNG → 인스타 규격 1080px JPG로 변환, /outputs에 저장, 상대경로 반환.
    발행마다 고유 파일명(pub_<token>_...)을 써서 Meta의 URL fetch 캐시를 우회한다.
    (같은 파일명을 재사용하면 Meta가 과거 실패 결과를 캐싱해 계속 9004를 반환할 수 있음)"""
    from PIL import Image
    import time
    token = f"{int(time.time())}{secrets.token_hex(3)}"  # 발행마다 유니크
    out = []
    for u in image_urls:
        fname = os.path.basename(u)
        src = os.path.join(OUT, fname)
        if not os.path.exists(src):
            out.append(u); continue
        try:
            im = Image.open(src).convert("RGB")
            # 인스타 4:5 권장, 가로 1080
            w, h = im.size
            target_w = 1080
            target_h = int(target_w * h / w)
            im = im.resize((target_w, target_h), Image.LANCZOS)
            pub_name = f"pub_{token}_" + os.path.splitext(fname)[0] + ".jpg"
            im.save(os.path.join(OUT, pub_name), "JPEG", quality=88)
            out.append("/outputs/" + pub_name)
        except Exception as e:
            print("[publish-resize] err", e)
            out.append(u)
    return out

# ── publish ───────────────────────────────────────────────
@app.post("/api/publish")
async def do_publish(req: Request):
    d    = await req.json()
    plat = d.get("platform","instagram")
    # 발행용 규격 이미지 생성 (인스타/스레드 규격)
    pub_imgs = await run_in_threadpool(_make_publish_images, d.get("images",[]))
    res  = (publish.publish_threads(pub_imgs, d.get("caption","")) if plat=="threads"
            else publish.publish_instagram(pub_imgs, d.get("caption","")))
    return JSONResponse(res)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT",8000)))
