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
def _generate_sync(t, lang="ko"):
    sens     = t.get("sensitive", False)
    material = enrich.gather(t, lang=t.get("wiki_lang","en"))
    copy     = llm.localize(t, material=material, sensitive=sens, lang=lang)
    n_slides = len(copy.get("slides", []))
    title    = t.get("title","")
    cat      = t.get("category","기타")
    bg       = images.fetch_bg(title, cat)
    simgs    = images.fetch_slide_images(title, cat, n_slides)
    slug     = re.sub(r"[^a-z0-9]+"," ",title.lower())[:24].strip().replace(" ","-") or "trend"
    paths    = render_carousel.render(copy, OUT, sensitive=sens, slug=slug,
                                      bg_url=(bg or {}).get("url"), slide_imgs=simgs, lang=lang)
    urls     = ["/outputs/"+os.path.basename(p) for p in paths]
    src      = material.get("url","")
    # LLM이 생성한 캡션(기사 본문 기반 + 해시태그) 사용, 없으면 폴백
    cap = (copy.get("caption") or "").strip()
    if not cap:
        cap = f"{copy.get('ko_title','')}\n\n{copy.get('why_ko','')}".strip()
    # 출처는 무조건 맨 아래 표시 (언어별 라벨)
    SRC_LABEL = {"ko": "📎 출처:", "ja": "📎 出典:", "en": "📎 Source:"}
    SRC_NONE  = {"ko": "📎 출처 확인", "ja": "📎 出典を確認", "en": "📎 Source"}
    label = SRC_LABEL.get(lang, SRC_LABEL["ko"])
    source_line = f"{label} {src}" if src else SRC_NONE.get(lang, SRC_NONE["ko"])
    # 인스타 캡션 2,200자 제한 안전장치 (출처 줄은 항상 보존)
    LIMIT = 2200
    room = LIMIT - len(source_line) - 2
    if len(cap) > room:
        cap = cap[:max(0, room)].rstrip()
    caption = f"{cap}\n\n{source_line}"
    return {"copy": copy, "images": urls, "caption": caption, "lang": lang, "src": src,
            "img_credit": bg, "bg_url": (bg or {}).get("url"),
            "slide_imgs": [ (s or {}).get("url") for s in simgs ]}

@app.post("/api/generate")
async def generate(req: Request):
    return await run_in_threadpool(_generate_sync, await req.json())

@app.post("/api/generate-lang")
async def generate_lang(req: Request):
    """언어 전환: 이미 생성된 카드를 대상 언어(ko|ja|en)로 '번역'한 뒤 같은 이미지로 재렌더.
    재료를 다시 수집하지 않으므로 폴백(한국어 고정) 문제가 없다."""
    d = await req.json()
    lang = d.get("lang", "ko")
    if lang not in ("ko", "ja", "en"):
        lang = "ko"
    return await run_in_threadpool(_relang_sync, d, lang)

def _relang_sync(d, lang="ko"):
    copy = d.get("copy") or {}
    # 대상 언어로 카드 텍스트 번역 (ko면 원본 그대로)
    if lang != "ko":
        copy = llm.translate_copy(copy, lang)
    sens   = d.get("sensitive", False)
    title  = d.get("title", "") or "trend"
    slug   = re.sub(r"[^a-z0-9]+"," ",title.lower())[:20].strip().replace(" ","-") + f"-{lang}"
    bg_url = d.get("bg_url")
    simg_urls = d.get("slide_imgs") or []
    simgs  = [ (dict(url=u) if u else None) for u in simg_urls ]
    paths  = render_carousel.render(copy, OUT, sensitive=sens, slug=slug,
                                    bg_url=bg_url, slide_imgs=simgs, lang=lang)
    urls   = ["/outputs/"+os.path.basename(p) for p in paths]
    # 캡션 재조립 (번역된 caption + 언어별 출처 라벨)
    src = d.get("src", "")
    cap = (copy.get("caption") or "").strip()
    if not cap:
        cap = f"{copy.get('ko_title','')}".strip()
    SRC_LABEL = {"ko": "📎 출처:", "ja": "📎 出典:", "en": "📎 Source:"}
    SRC_NONE  = {"ko": "📎 출처 확인", "ja": "📎 出典を確認", "en": "📎 Source"}
    label = SRC_LABEL.get(lang, SRC_LABEL["ko"])
    source_line = f"{label} {src}" if src else SRC_NONE.get(lang, SRC_NONE["ko"])
    LIMIT = 2200
    room = LIMIT - len(source_line) - 2
    if len(cap) > room:
        cap = cap[:max(0, room)].rstrip()
    caption = f"{cap}\n\n{source_line}"
    return {"copy": copy, "images": urls, "caption": caption, "lang": lang, "src": src,
            "img_credit": {"url": bg_url} if bg_url else None, "bg_url": bg_url,
            "slide_imgs": simg_urls}

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
def _ko_to_en(q: str) -> str:
    """한글 검색어를 영어로 번역 (Unsplash/Pexels는 영어 기반이라 한글은 결과가 빈약함).
    한글이 없으면 원문 그대로. 번역 실패 시에도 원문을 반환해 검색은 계속 동작."""
    if not q or not re.search(r"[가-힣]", q):
        return q
    try:
        import requests
        r = requests.get("https://translate.googleapis.com/translate_a/single",
                         params={"client": "gtx", "sl": "ko", "tl": "en",
                                 "dt": "t", "q": q}, timeout=8)
        data = r.json()
        en = "".join(seg[0] for seg in data[0] if seg and seg[0])
        return en.strip() or q
    except Exception as e:
        print("[img-search] 번역 실패, 원문 사용:", e)
        return q

@app.get("/api/images/search")
def image_search(q: str="", n: int=6):
    q_en = _ko_to_en(q)               # 한글이면 영어로 번역 후 검색
    return {"results": images.search_images(q_en, n)}

# ── 발행 이미지 외부 호스팅 (imgbb) ───────────────────
def _upload_to_imgbb(filepath, tries=4):
    """발행용 JPG를 imgbb에 올려 Meta가 확실히 가져갈 수 있는 직접 URL을 반환.
    실패 시 백오프 두고 재시도(무료 한도/스로틀 대비). 최종 실패면 None.

    railway 도메인(*.up.railway.app)을 Meta가 fetch 못 하는 문제(9004)를 우회하기 위한 것.
    6장 연속 업로드 중 일부가 실패하면 railway로 폴백돼 그 이미지에서 9004가 나므로,
    여기서 확실히 올리는 게 중요하다. imgbb는 Meta가 안정적으로 가져가는 CDN."""
    key = os.environ.get("IMGBB_API_KEY")
    if not key:
        return None
    import base64, requests, time
    try:
        with open(filepath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception as e:
        print("[imgbb] 파일 읽기 실패:", e); return None
    for attempt in range(tries):
        try:
            r = requests.post("https://api.imgbb.com/1/upload",
                              data={"key": key, "image": b64}, timeout=60)
            j = r.json()
            if j.get("success"):
                url = j["data"]["url"]           # 직접 이미지 URL (예: https://i.ibb.co/.../x.jpg)
                print(f"[imgbb] 업로드 성공 (try {attempt+1}): {url}")
                return url
            print(f"[imgbb] 업로드 실패 (try {attempt+1}/{tries}):", j.get("error") or j)
        except Exception as e:
            print(f"[imgbb] 에러 (try {attempt+1}/{tries}):", e)
        time.sleep(2 * (attempt + 1))            # 2s, 4s, 6s 백오프
    return None

# ── 인스타 규격 리사이즈 (발행용 1080px JPG) ──────────
def _make_publish_images(image_urls):
    """2x PNG → 인스타 규격 1080px JPG로 변환.
    IMGBB_API_KEY가 있으면 imgbb에 올려 그 URL을 쓰고(권장),
    없으면 /outputs 로컬 URL로 폴백한다.
    파일명은 발행마다 유니크(pub_<token>_...)라 Meta URL 캐시도 우회.

    반환: {"urls": [...], "error": str|None}
      - imgbb 키가 설정돼 있는데 업로드에 최종 실패하면, railway URL로 폴백하면
        어차피 9004가 나므로 폴백하지 않고 error를 담아 반환한다(원인 명확화)."""
    from PIL import Image
    import time
    use_imgbb = bool(os.environ.get("IMGBB_API_KEY"))
    token = f"{int(time.time())}{secrets.token_hex(3)}"  # 발행마다 유니크
    out = []
    for idx, u in enumerate(image_urls):
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
            local_path = os.path.join(OUT, pub_name)
            im.save(local_path, "JPEG", quality=88)
            if use_imgbb:
                if idx > 0:
                    time.sleep(0.7)              # 연속 업로드 스로틀 회피
                hosted = _upload_to_imgbb(local_path)
                if not hosted:
                    # railway 폴백은 9004가 나므로, 폴백 대신 명확히 실패 처리
                    return {"urls": [], "error": (
                        f"imgbb 업로드 실패({idx+1}번째 이미지). 무료 한도/스로틀 가능성. "
                        "잠시 후 재시도하거나 IMGBB_API_KEY 확인.")}
                out.append(hosted)
            else:
                out.append("/outputs/" + pub_name)
        except Exception as e:
            print("[publish-resize] err", e)
            out.append(u)
    return {"urls": out, "error": None}

# ── 카드 전체 다운로드 (인스타 규격 1080 JPG · ZIP) ────
def _build_zip(image_urls):
    """편집 화면의 카드(2x PNG)를 인스타 규격 1080px JPG로 리사이즈해 ZIP 바이트로 묶는다."""
    import io, zipfile
    from PIL import Image
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, u in enumerate(image_urls, 1):
            src = os.path.join(OUT, os.path.basename(u))
            if not os.path.exists(src):
                continue
            try:
                im = Image.open(src).convert("RGB")
                w, h = im.size
                tw = 1080
                th = int(tw * h / w)
                im = im.resize((tw, th), Image.LANCZOS)
                ib = io.BytesIO()
                im.save(ib, "JPEG", quality=90)
                zf.writestr(f"card_{i:02d}.jpg", ib.getvalue())
                count += 1
            except Exception as e:
                print("[zip] err", e)
    buf.seek(0)
    return buf.getvalue(), count

@app.post("/api/download-zip")
async def download_zip(req: Request):
    from fastapi.responses import Response
    d = await req.json()
    data, count = await run_in_threadpool(_build_zip, d.get("images", []))
    if count == 0:
        return JSONResponse({"error": "다운로드할 카드가 없습니다. 먼저 카드를 생성하세요."},
                            status_code=400)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition":
                             'attachment; filename="trendcast_cards.zip"'})

# ── publish ───────────────────────────────────────────────
@app.post("/api/publish")
async def do_publish(req: Request):
    d    = await req.json()
    plat = d.get("platform","instagram")
    # 발행용 규격 이미지 생성 (인스타/스레드 규격)
    made = await run_in_threadpool(_make_publish_images, d.get("images",[]))
    pub_imgs = made.get("urls", [])
    if made.get("error"):
        return JSONResponse({"status": "error", "platform": plat,
                             "error": f"이미지 호스팅 실패: {made['error']}"})
    res  = (publish.publish_threads(pub_imgs, d.get("caption","")) if plat=="threads"
            else publish.publish_instagram(pub_imgs, d.get("caption","")))
    return JSONResponse(res)

# ── 자동 발행 (매일 09:00 KST, 완전 자동) ───────────────
def auto_publish_job():
    """한국 전체 트렌드에서 1건을 골라 생성→발행까지 자동으로 수행한다.
    무인 발행이므로 민감(sensitive) 이슈는 건너뛰고 첫 비민감 항목을 사용."""
    print("[auto] 자동 발행 시작", flush=True)
    try:
        items = engine.run(geo="KR", category="전체", n=6, wiki_lang="ko")
        if not items:
            print("[auto] 트렌드 없음, 중단")
            return {"status": "error", "error": "트렌드 없음"}
        # 민감 이슈는 무인 발행에서 제외
        item = next((it for it in items if not it.get("sensitive")), items[0])
        item.setdefault("wiki_lang", "ko")
        item.setdefault("category", "전체")
        print(f"[auto] 선택 트렌드: {item.get('title')}")
        gen  = _generate_sync(item)
        made = _make_publish_images(gen["images"])
        if made.get("error"):
            print("[auto] 이미지 호스팅 실패:", made["error"])
            return {"status": "error", "error": made["error"]}
        res = publish.publish_instagram(made["urls"], gen["caption"])
        print("[auto] 발행 결과:", res.get("status"), res.get("error", ""))
        return res
    except Exception as e:
        import traceback; traceback.print_exc()
        print("[auto] 예외:", e)
        return {"status": "error", "error": str(e)}

@app.on_event("startup")
def _start_scheduler():
    # AUTO_PUBLISH=0 으로 끄면 스케줄러 비활성 (기본 켜짐)
    if os.environ.get("AUTO_PUBLISH", "1") != "1":
        print("[auto] AUTO_PUBLISH!=1 → 스케줄러 비활성")
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        sched = BackgroundScheduler(timezone="UTC")
        # 00:00 UTC == 09:00 KST (KST=UTC+9, 서머타임 없음)
        sched.add_job(auto_publish_job, CronTrigger(hour=0, minute=0),
                      id="daily_ig", misfire_grace_time=3600, coalesce=True,
                      max_instances=1)
        sched.start()
        app.state.scheduler = sched
        print("[auto] 스케줄러 시작 — 매일 09:00 KST(=00:00 UTC) 자동 발행")
    except Exception as e:
        print("[auto] 스케줄러 시작 실패:", e)

@app.post("/api/auto-publish-now")
async def auto_publish_now():
    """자동 발행 흐름을 지금 즉시 1회 실행 (테스트용). 9시까지 안 기다려도 됨."""
    res = await run_in_threadpool(auto_publish_job)
    return JSONResponse(res)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT",8000)))
