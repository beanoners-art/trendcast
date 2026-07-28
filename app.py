# -*- coding: utf-8 -*-
import os, re
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool
from dotenv import load_dotenv

import engine, llm, render_carousel, publish, enrich, images

load_dotenv()
BASE = os.path.dirname(__file__)
OUT  = os.path.join(BASE, "outputs")
os.makedirs(OUT, exist_ok=True)

app = FastAPI(title="Trendcast")
app.mount("/outputs", StaticFiles(directory=OUT),                     name="outputs")
app.mount("/static",  StaticFiles(directory=os.path.join(BASE,"static")), name="static")

@app.get("/", response_class=HTMLResponse)
def home():
    return open(os.path.join(BASE,"static","index.html"), encoding="utf-8").read()

@app.get("/api/trends")
def trends(geo: str="US", category: str="전체", n: int=6, wiki_lang: str="en"):
    return {"items": engine.run(geo=geo, category=category, n=n, wiki_lang=wiki_lang)}

# ── generate ──────────────────────────────────────────────
def _generate_sync(t):
    sens     = t.get("sensitive", False)
    layout   = t.get("layout", "dark")
    material = enrich.gather(t, lang=t.get("wiki_lang","en"))
    copy     = llm.localize(t, material=material, sensitive=sens)
    img      = images.fetch_image(t.get("title",""), t.get("category","기타"))
    img_url  = img["url"] if img else None
    slug     = re.sub(r"[^a-z0-9]+"," ",t.get("title","trend").lower())[:24].strip().replace(" ","-") or "trend"
    paths    = render_carousel.render(copy, OUT, sensitive=sens,
                                      slug=slug, layout=layout, img_url=img_url)
    urls     = ["/outputs/"+os.path.basename(p) for p in paths]
    src      = material.get("url","")
    caption  = (f"{copy['ko_title']}\n\n{copy.get('why_ko','')}\n\n"
                f"(사실 전달 · 출처 확인{' · '+src if src else ''})")
    return {"copy": copy, "images": urls, "caption": caption,
            "img_credit": img, "layout": layout}

@app.post("/api/generate")
async def generate(req: Request):
    return await run_in_threadpool(_generate_sync, await req.json())

# ── re-render (editor apply) ──────────────────────────────
def _rerender_sync(t):
    copy     = {"ko_title": t.get("ko_title",""), "why_ko": t.get("why_ko",""),
                "slides": t.get("slides",[])}
    img_url  = t.get("img_url")
    layout   = t.get("layout","dark")
    sens     = t.get("sensitive", False)
    slug     = re.sub(r"[^a-z0-9]+"," ",t.get("ko_title","edit").lower())[:20].strip().replace(" ","-")+"-ed"
    paths    = render_carousel.render(copy, OUT, sensitive=sens,
                                      slug=slug, layout=layout, img_url=img_url)
    return {"images": ["/outputs/"+os.path.basename(p) for p in paths]}

@app.post("/api/rerender")
async def rerender(req: Request):
    return await run_in_threadpool(_rerender_sync, await req.json())

# ── image search (editor swap) ────────────────────────────
@app.get("/api/images/search")
def image_search(q: str="", n: int=6):
    return {"results": images.search_images(q, n)}

# ── publish ───────────────────────────────────────────────
@app.post("/api/publish")
async def do_publish(req: Request):
    d    = await req.json()
    base = os.environ.get("PUBLIC_IMAGE_BASE","")
    urls = [base+u if base else u for u in d.get("images",[])]
    plat = d.get("platform","instagram")
    res  = (publish.publish_threads(urls, d.get("caption","")) if plat=="threads"
            else publish.publish_instagram(urls, d.get("caption","")))
    return JSONResponse(res)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT",8000)))
