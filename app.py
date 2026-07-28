# -*- coding: utf-8 -*-
import os, re
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool
from dotenv import load_dotenv

import engine, llm, render_carousel, publish

load_dotenv()
BASE = os.path.dirname(__file__)
OUT = os.path.join(BASE, "outputs")
os.makedirs(OUT, exist_ok=True)

app = FastAPI(title="Trendcast")
app.mount("/outputs", StaticFiles(directory=OUT), name="outputs")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")

@app.get("/", response_class=HTMLResponse)
def home():
    return open(os.path.join(BASE, "static", "index.html"), encoding="utf-8").read()

@app.get("/api/trends")
def trends(geo: str = "US", category: str = "전체", n: int = 6, wiki_lang: str = "en"):
    return {"items": engine.run(geo=geo, category=category, n=n, wiki_lang=wiki_lang)}

def _generate_sync(t):
    sens = t.get("sensitive", False)
    copy = llm.localize(t, sensitive=sens)
    slug = re.sub(r"[^a-z0-9]+", "-", t.get("title", "trend").lower())[:24] or "trend"
    paths = render_carousel.render(copy, OUT, sensitive=sens, slug=slug)
    urls = ["/outputs/" + os.path.basename(p) for p in paths]
    caption = f"{copy['ko_title']}\n\n{copy.get('why_ko','')}\n\n(사실 전달 · 출처 확인)"
    return {"copy": copy, "images": urls, "caption": caption}

@app.post("/api/generate")
async def generate(req: Request):
    t = await req.json()
    return await run_in_threadpool(_generate_sync, t)

@app.post("/api/publish")
async def do_publish(req: Request):
    d = await req.json()
    base = os.environ.get("PUBLIC_IMAGE_BASE", "")
    urls = [base + u if base else u for u in d.get("images", [])]
    plat = d.get("platform", "instagram")
    if plat == "threads":
        res = publish.publish_threads(urls, d.get("caption", ""))
    else:
        res = publish.publish_instagram(urls, d.get("caption", ""))
    return JSONResponse(res)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
