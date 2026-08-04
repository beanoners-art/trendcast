# -*- coding: utf-8 -*-
"""
카드뉴스 렌더 v4 — 매거진 에디토리얼 스타일.
- 통일 배경 이미지(블러+딤) 전 장 공통
- 제목 + 문단 본문(**볼드** → 액센트 하이라이트)
- 슬라이드별 삽입 사진 카드 (본문 위/아래)
- 하단 워터마크 (BRAND_HANDLE 환경변수, 기본 '트렌드 브리핑')
"""
import os, re, base64, html, requests
from playwright.sync_api import sync_playwright

IVORY, AMBER, DARK = "#F5EFE2", "#E8A63C", "#171009"

def _b64(url, timeout=12):
    if not url: return None
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "trendcast/0.3"})
        ct = r.headers.get("content-type", "")
        ext = "webp" if "webp" in ct else ("png" if "png" in ct else "jpeg")
        return f"data:image/{ext};base64,{base64.b64encode(r.content).decode()}"
    except Exception as e:
        print("[render] img dl err", e)
        return None

def _strip_html(text):
    """소스에서 딸려온 실제 HTML 태그·엔티티를 제거한다.
    네이트/네이버/카카오 등이 검색어를 <b>...</b>로 강조해 보내는 것을 정리.
    앱 자체의 **볼드** 마커는 건드리지 않는다(여기서는 태그만 제거)."""
    t = html.unescape(text or "")            # &amp; &quot; &lt;b&gt; 등 먼저 복원
    t = re.sub(r"</?[a-zA-Z][^>]*>", "", t)  # <b>,</b>,<br>,<div ...> 등 실제 태그 제거
    t = re.sub(r"[ \t]+", " ", t)            # 태그 제거로 생긴 중복 공백 정리
    return t.strip()

def _fmt_body(body):
    """**볼드** → 하이라이트 span, 줄바꿈 유지. (소스 HTML 태그는 먼저 제거)"""
    safe = _strip_html(body)                          # <b> 등 실제 태그 제거
    safe = safe.replace("<", "&lt;").replace(">", "&gt;")  # 남은 <,> 안전 이스케이프
    safe = re.sub(r"\*\*(.+?)\*\*", r'<b class="hl">\1</b>', safe)  # 앱 볼드 마커
    return safe.replace("\n", "<br>")

def _slide_html(i, n, slide, bg_b64, content_b64, watermark, sensitive):
    title = _strip_html(slide.get("title") or "") \
                .replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    body  = _fmt_body(slide.get("body", ""))
    is_cover = (i == 0)
    fscale = float(slide.get("fontScale", 1.0))
    align  = slide.get("align", "left")   # left | center
    tsize = int((96 if is_cover else 64) * fscale)
    bsize = int((34 if is_cover else 30) * fscale)

    bg_layer = (f"background:linear-gradient(rgba(23,16,9,.55),rgba(23,16,9,.72)),"
                f"url('{bg_b64}') center/cover no-repeat;") if bg_b64 else \
               f"background:{DARK};"

    photo_html = ""
    if content_b64:
        photo_html = f'''<div class="photo"><img src="{content_b64}">
        <span class="pcredit">출처 · Pexels/Unsplash</span></div>'''

    flag = '<span class="flag">사실 전달</span>' if (sensitive and is_cover) else ""
    dots = "".join(f'<span class="dot {"cur" if k==i else ""}"></span>' for k in range(n))

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    *{{margin:0;box-sizing:border-box}}html,body{{width:1080px;height:1350px}}
    .s{{width:1080px;height:1350px;{bg_layer}color:{IVORY};
      font-family:'Pretendard','Noto Sans CJK KR',sans-serif;
      padding:88px 84px 72px;display:flex;flex-direction:column;
      overflow:hidden;-webkit-font-smoothing:antialiased;position:relative;
      text-align:{align}}}
    h1{{font-size:{tsize}px;font-weight:800;line-height:1.22;letter-spacing:-.02em;
      word-break:keep-all;color:{IVORY};
      text-shadow:0 2px 24px rgba(0,0,0,.45);margin-bottom:34px}}
    .flag{{display:inline-block;font-size:20px;font-weight:700;vertical-align:middle;
      background:{AMBER};color:{DARK};padding:5px 16px;border-radius:20px;
      margin-left:14px;letter-spacing:0}}
    .body{{font-size:{bsize}px;font-weight:500;line-height:1.72;
      word-break:keep-all;color:rgba(245,239,226,.94);
      text-shadow:0 1px 12px rgba(0,0,0,.5);max-width:900px;
      margin-left:{'auto' if align=='center' else '0'};margin-right:{'auto' if align=='center' else '0'}}}
    .hl{{color:{AMBER};font-weight:800}}
    .photo{{margin:36px 0 8px;position:relative;border-radius:14px;overflow:hidden;
      box-shadow:0 10px 40px rgba(0,0,0,.45)}}
    .photo img{{width:100%;height:430px;object-fit:cover;display:block}}
    .pcredit{{position:absolute;right:12px;bottom:10px;font-size:17px;
      color:rgba(255,255,255,.85);text-shadow:0 1px 6px rgba(0,0,0,.8)}}
    .mid{{flex:1;display:flex;flex-direction:column;justify-content:center}}
    .foot{{display:flex;justify-content:space-between;align-items:center}}
    .wm{{font-size:24px;font-weight:700;color:rgba(245,239,226,.9);
      border-bottom:3px solid {AMBER};padding-bottom:4px}}
    .dots{{display:flex;gap:9px}}
    .dot{{width:10px;height:10px;border-radius:50%;background:rgba(245,239,226,.25)}}
    .dot.cur{{background:{AMBER};width:30px;border-radius:5px}}
    </style></head><body><div class="s">
      <div class="mid">
        <h1>{title}{flag}</h1>
        {photo_html if slide.get("_photo_top") else ""}
        <p class="body">{body}</p>
        {photo_html if not slide.get("_photo_top") else ""}
      </div>
      <div class="foot"><span class="wm">{watermark}</span>
        <div class="dots">{dots}</div></div>
    </div></body></html>"""

def render(copy, out_dir, sensitive=False, slug="trend",
           bg_url=None, slide_imgs=None, layout=None, img_url=None):
    """
    copy["slides"]: [{"title","body","img"}] 또는 구버전 문자열 리스트도 수용.
    bg_url: 통일 배경. slide_imgs: 슬라이드별 삽입 사진 [dict|None].
    """
    os.makedirs(out_dir, exist_ok=True)
    slides = copy["slides"]
    # 구버전(문자열) 호환
    if slides and isinstance(slides[0], str):
        slides = [dict(title=s.split("\n")[0],
                       body="\n".join(s.split("\n")[1:]), img=False) for s in slides]
    n = len(slides)
    watermark = os.environ.get("BRAND_HANDLE", "트렌드 브리핑")

    bg_b64 = _b64(bg_url or img_url)
    imgs_b64 = []
    for k in range(n):
        s = slides[k]
        # 편집기에서 교체한 개별 이미지 URL 우선
        override = s.get("img_url")
        if override:
            imgs_b64.append(_b64(override))
        else:
            want = s.get("img") and slide_imgs and k < len(slide_imgs) and slide_imgs[k]
            imgs_b64.append(_b64(slide_imgs[k]["url"]) if want else None)
        # 사진 위치: 편집기 지정 우선, 없으면 번갈아
        if "_photo_top" not in s:
            s["_photo_top"] = (k % 2 == 1)

    paths = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
        for i, s in enumerate(slides):
            pg.set_content(_slide_html(i, n, s, bg_b64, imgs_b64[i],
                                       watermark, sensitive),
                           wait_until="networkidle")
            fp = os.path.join(out_dir, f"{slug}_{i+1:02d}.png")
            pg.locator(".s").screenshot(path=fp)
            paths.append(fp)
        b.close()
    return paths
