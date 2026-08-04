# -*- coding: utf-8 -*-
"""
카드뉴스 렌더 v5 — 경제 시그니처 에디션.
- 통일 배경 이미지(블러+딤) 전 장 공통
- 제목 + 문단 본문(**볼드** → 액센트 하이라이트)
- 숫자 비교 카드 (key_numbers) — 표지 다음에 자동 삽입
- 모든 카드 공통 'FACT · 출처 명시' 시그니처 배지 (FACT_BADGE 환경변수)
- 슬라이드별 삽입 사진 카드 (본문 위/아래)
- 하단 워터마크 (BRAND_HANDLE 환경변수, 기본 '트렌드 브리핑')
"""
import os, re, base64, html, requests
from playwright.sync_api import sync_playwright

IVORY, AMBER, DARK = "#F5EFE2", "#E8A63C", "#171009"
UP, DOWN = "#4ADE80", "#F87171"   # 상승 초록 / 하락 빨강

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
    앱 자체의 **볼드** 마커는 건드리지 않는다(여기서는 태그만 제거)."""
    t = html.unescape(str(text) if text is not None else "")
    t = re.sub(r"</?[a-zA-Z][^>]*>", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()

def _esc(text):
    return _strip_html(text).replace("<", "&lt;").replace(">", "&gt;")

def _fmt_body(body):
    """**볼드** → 하이라이트 span, 줄바꿈 유지. (소스 HTML 태그는 먼저 제거)"""
    safe = _strip_html(body)
    safe = safe.replace("<", "&lt;").replace(">", "&gt;")
    safe = re.sub(r"\*\*(.+?)\*\*", r'<b class="hl">\1</b>', safe)
    return safe.replace("\n", "<br>")

def _numbers_block(nums):
    """key_numbers → 숫자 비교 그리드 HTML."""
    cells = ""
    for it in nums[:4]:
        val = _esc(it.get("value", ""))
        lab = _esc(it.get("label", ""))
        dlt = _esc(it.get("delta", "") or "")
        dcls = "up" if (dlt.startswith("+") or "▲" in dlt or "상승" in dlt) else \
               ("down" if (dlt.startswith("-") or "▼" in dlt or "하락" in dlt) else "")
        dhtml = f'<div class="ndelta {dcls}">{dlt}</div>' if dlt else ""
        cells += (f'<div class="ncell"><div class="nval">{val}</div>'
                  f'<div class="nlabel">{lab}</div>{dhtml}</div>')
    two = "two" if len(nums[:4]) >= 3 else "one"
    return f'<div class="ngrid {two}">{cells}</div>'

def _slide_html(i, n, slide, bg_b64, content_b64, watermark, sensitive, fact_badge):
    is_cover  = (i == 0)
    is_numbers = bool(slide.get("_numbers"))
    title = _esc(slide.get("title") or "").replace("\n", "<br>")
    fscale = float(slide.get("fontScale", 1.0))
    align  = slide.get("align", "left")
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

    if is_numbers:
        inner = f'<div class="ntitle">{title}</div>{_numbers_block(slide["_numbers"])}'
    else:
        body = _fmt_body(slide.get("body", ""))
        inner = (f'<h1>{title}{flag}</h1>'
                 f'{photo_html if slide.get("_photo_top") else ""}'
                 f'<p class="body">{body}</p>'
                 f'{photo_html if not slide.get("_photo_top") else ""}')

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
    .ntitle{{font-size:54px;font-weight:800;letter-spacing:-.02em;color:{IVORY};
      margin-bottom:48px;text-shadow:0 2px 20px rgba(0,0,0,.5)}}
    .ngrid{{display:grid;gap:26px;width:100%}}
    .ngrid.one{{grid-template-columns:1fr}}
    .ngrid.two{{grid-template-columns:1fr 1fr}}
    .ncell{{background:rgba(23,16,9,.42);border:1px solid rgba(232,166,60,.35);
      border-radius:18px;padding:38px 34px}}
    .nval{{font-size:76px;font-weight:800;line-height:1.05;letter-spacing:-.03em;
      color:{AMBER};text-shadow:0 2px 18px rgba(0,0,0,.4);word-break:keep-all}}
    .nlabel{{font-size:28px;font-weight:600;color:rgba(245,239,226,.9);margin-top:14px}}
    .ndelta{{display:inline-block;margin-top:16px;font-size:30px;font-weight:800;
      color:rgba(245,239,226,.85)}}
    .ndelta.up{{color:{UP}}} .ndelta.down{{color:{DOWN}}}
    .fact{{position:absolute;top:44px;right:44px;z-index:5;
      font-size:22px;font-weight:800;letter-spacing:.02em;
      color:{DARK};background:{AMBER};padding:8px 18px;border-radius:7px;
      box-shadow:0 3px 14px rgba(0,0,0,.35)}}
    .mid{{flex:1;display:flex;flex-direction:column;justify-content:center}}
    .foot{{display:flex;justify-content:space-between;align-items:center}}
    .wm{{font-size:24px;font-weight:700;color:rgba(245,239,226,.9);
      border-bottom:3px solid {AMBER};padding-bottom:4px}}
    .dots{{display:flex;gap:9px}}
    .dot{{width:10px;height:10px;border-radius:50%;background:rgba(245,239,226,.25)}}
    .dot.cur{{background:{AMBER};width:30px;border-radius:5px}}
    </style></head><body><div class="s">
      <span class="fact">{fact_badge}</span>
      <div class="mid">
        {inner}
      </div>
      <div class="foot"><span class="wm">{watermark}</span>
        <div class="dots">{dots}</div></div>
    </div></body></html>"""

def render(copy, out_dir, sensitive=False, slug="trend",
           bg_url=None, slide_imgs=None, layout=None, img_url=None):
    """
    copy["slides"]: [{"title","body","img"}] 또는 구버전 문자열 리스트도 수용.
    copy["key_numbers"]: [{"value","label","delta"}] → 표지 다음 숫자 비교 카드 자동 삽입.
    """
    os.makedirs(out_dir, exist_ok=True)
    slides = list(copy["slides"])
    if slides and isinstance(slides[0], str):
        slides = [dict(title=s.split("\n")[0],
                       body="\n".join(s.split("\n")[1:]), img=False) for s in slides]

    # 숫자 비교 카드: key_numbers가 2개 이상이면 표지(0) 다음에 삽입
    key_nums = copy.get("key_numbers") or []
    if isinstance(key_nums, list) and len(key_nums) >= 2:
        num_slide = {"_numbers": key_nums[:4], "title": "숫자로 보는 핵심", "img": False}
        slides.insert(1 if len(slides) >= 1 else 0, num_slide)

    n = len(slides)
    watermark  = os.environ.get("BRAND_HANDLE", "트렌드 브리핑")
    fact_badge = os.environ.get("FACT_BADGE", "FACT · 출처 명시")

    bg_b64 = _b64(bg_url or img_url)
    imgs_b64 = []
    src_idx = 0
    for k in range(n):
        s = slides[k]
        if s.get("_numbers"):
            imgs_b64.append(None)
            continue
        override = s.get("img_url")
        if override:
            imgs_b64.append(_b64(override))
        else:
            want = s.get("img") and slide_imgs and src_idx < len(slide_imgs) and slide_imgs[src_idx]
            imgs_b64.append(_b64(slide_imgs[src_idx]["url"]) if want else None)
        if "_photo_top" not in s:
            s["_photo_top"] = (k % 2 == 1)
        src_idx += 1

    paths = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
        for i, s in enumerate(slides):
            pg.set_content(_slide_html(i, n, s, bg_b64, imgs_b64[i],
                                       watermark, sensitive, fact_badge),
                           wait_until="networkidle")
            fp = os.path.join(out_dir, f"{slug}_{i+1:02d}.png")
            pg.locator(".s").screenshot(path=fp)
            paths.append(fp)
        b.close()
    return paths
