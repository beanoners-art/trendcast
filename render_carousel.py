# -*- coding: utf-8 -*-
"""
카드뉴스 렌더 v3: Unsplash 배경 이미지 + 다크 오버레이 + 레이아웃 선택.
copy dict에 img_url(str|None), layout('dark'|'light'|'cobalt') 포함.
"""
import os, base64, requests
from playwright.sync_api import sync_playwright

ESP, IVORY, AMBER, AMBER_D, COBALT = "#1a120c", "#EFE7D6", "#E39B33", "#B8721C", "#2C43F0"

LAYOUTS = {
    "dark":   dict(bg=ESP,    fg=IVORY, acc=AMBER,   muted="rgba(239,231,214,.60)", line="rgba(239,231,214,.14)"),
    "light":  dict(bg=IVORY,  fg=ESP,   acc=AMBER_D,  muted="rgba(36,24,18,.55)",   line="rgba(36,24,18,.12)"),
    "cobalt": dict(bg=COBALT, fg=IVORY, acc=IVORY,    muted="rgba(239,231,214,.72)", line="rgba(239,231,214,.20)"),
}

def _img_b64(url):
    """Unsplash URL → base64 data URI (렌더 서버에서 외부 이미지 로드 보장)."""
    if not url: return None
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "trendcast/0.2"})
        ext = "jpeg"
        ct = r.headers.get("content-type","")
        if "webp" in ct: ext = "webp"
        elif "png" in ct: ext = "png"
        return f"data:image/{ext};base64,{base64.b64encode(r.content).decode()}"
    except Exception as e:
        print("[render] img fetch err", e)
        return None

def _slide_html(i, n, text, layout, img_b64, sensitive, eyebrow):
    t = LAYOUTS.get(layout, LAYOUTS["dark"])
    parts = text.split("\n", 1)
    head = parts[0].strip()
    sub  = parts[1].strip() if len(parts) > 1 else ""
    # bg: image with overlay OR solid colour
    if img_b64:
        bg_css = (f"background: linear-gradient(rgba(0,0,0,.52),rgba(0,0,0,.62)),"
                  f"url('{img_b64}') center/cover no-repeat; color:{t['fg']};")
        fg_override = IVORY
        muted_override = "rgba(239,231,214,.72)"
        acc = AMBER
        line = "rgba(239,231,214,.18)"
    else:
        bg_css = f"background:{t['bg']}; color:{t['fg']};"
        fg_override = t['fg']
        muted_override = t['muted']
        acc = t['acc']
        line = t['line']

    dots = "".join(
        f'<span class="dot {"cur" if k==i else ""}"></span>' for k in range(n))
    flag = f'<span class="flag">사실 전달</span>' if (sensitive and i == 0) else ""
    font_size = 92 if i == 0 else (72 if n > 6 else 80)

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    *{{margin:0;box-sizing:border-box}}html,body{{width:1080px;height:1350px}}
    .s{{width:1080px;height:1350px;{bg_css}
      font-family:'Pretendard','Noto Sans CJK KR',sans-serif;
      padding:96px 88px 80px;display:flex;flex-direction:column;
      overflow:hidden;-webkit-font-smoothing:antialiased;position:relative}}
    .glow{{position:absolute;top:-140px;right:-140px;width:560px;height:560px;border-radius:50%;
      background:radial-gradient(circle,rgba(227,155,51,.18),transparent 65%);pointer-events:none}}
    .top{{display:flex;justify-content:space-between;align-items:center;
      font-size:24px;font-weight:600;position:relative;z-index:1;color:{fg_override}}}
    .ser{{display:flex;align-items:center;gap:12px}}
    .ser::before{{content:"";width:14px;height:14px;border-radius:50%;background:{acc}}}
    .pg{{color:{muted_override};letter-spacing:.08em}}
    .mid{{flex:1;display:flex;flex-direction:column;justify-content:center;z-index:1}}
    .eye{{display:flex;gap:14px;align-items:center;font-size:25px;font-weight:700;
      color:{acc};letter-spacing:.12em;margin-bottom:28px}}
    .eye::before{{content:"";width:40px;height:2px;background:{acc}}}
    .flag{{margin-left:12px;font-size:18px;font-weight:700;
      background:{acc};color:{fg_override};padding:3px 12px;border-radius:20px}}
    h1{{font-size:{font_size}px;font-weight:800;line-height:1.26;
      letter-spacing:-.018em;word-break:keep-all;color:{fg_override}}}
    .sub{{margin-top:32px;font-size:34px;font-weight:500;line-height:1.55;
      color:{muted_override};word-break:keep-all;max-width:860px}}
    .foot{{display:flex;justify-content:space-between;align-items:center;z-index:1}}
    .dots{{display:flex;gap:10px}}
    .dot{{width:10px;height:10px;border-radius:50%;background:{line}}}
    .dot.cur{{background:{acc};width:30px;border-radius:5px}}
    .seal{{width:72px;height:72px;border-radius:50%;border:2px solid {fg_override};
      display:flex;align-items:center;justify-content:center;
      color:{fg_override};font-size:21px;font-weight:700;opacity:.82}}
    </style></head><body><div class="s"><div class="glow"></div>
    <div class="top"><span class="ser">트렌드 브리핑</span>
      <span class="pg">{i+1:02d} / {n:02d}</span></div>
    <div class="mid"><div class="eye">{eyebrow}{flag}</div>
      <h1>{head}</h1>
      {f'<p class="sub">{sub}</p>' if sub else ''}
    </div>
    <div class="foot"><div class="dots">{dots}</div>
      <div class="seal">브리핑</div></div>
    </div></body></html>"""

def render(copy, out_dir, sensitive=False, slug="trend",
           layout="dark", img_url=None):
    os.makedirs(out_dir, exist_ok=True)
    slides = copy["slides"]
    n = len(slides)
    eyebrows = (["오늘의 이슈"] +
                ["한 줄 요약","핵심 인물","역할·관계","숫자·규모","시점·일정",
                 "배경","왜 지금","알아둘 점","마무리"][:n-2] + ["마무리"])
    eyebrows = eyebrows[:n]
    # alternate layout for readability when image present
    layouts = []
    for k in range(n):
        if k == 0:
            layouts.append(layout)
        elif k % 3 == 2:
            layouts.append("cobalt" if layout == "dark" else "dark")
        else:
            layouts.append("light" if layout == "dark" else "dark")

    # download image once → base64 (so all slides share it)
    img_b64 = _img_b64(img_url) if img_url else None
    # cover uses image; inner slides use lighter overlay or no image alternating
    paths = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
        for i, text in enumerate(slides):
            # cover + every odd slide: show image bg; even inner: solid colour
            use_img = img_b64 if (i == 0 or i % 2 == 0) else None
            lyt = layouts[i]
            pg.set_content(_slide_html(i, n, text, lyt, use_img,
                                       sensitive, eyebrows[i]),
                           wait_until="networkidle")
            fp = os.path.join(out_dir, f"{slug}_{i+1:02d}.png")
            pg.locator(".s").screenshot(path=fp)
            paths.append(fp)
        b.close()
    return paths
