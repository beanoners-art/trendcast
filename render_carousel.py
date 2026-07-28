# -*- coding: utf-8 -*-
"""카드뉴스 렌더: 현지화된 카피 → 1080x1350 PNG (사실 전달형, 앞서 만든 디자인 시스템 재사용)."""
import os
from playwright.sync_api import sync_playwright

ESP, IVORY, AMBER, AMBER_D = "#241812", "#EFE7D6", "#E39B33", "#B8721C"

def _slide_html(i, n, text, theme, eyebrow, sensitive):
    dark = theme == "esp"
    bg, fg = (ESP, IVORY) if dark else (IVORY, ESP)
    muted = "rgba(239,231,214,.62)" if dark else "rgba(36,24,18,.58)"
    line = "rgba(239,231,214,.16)" if dark else "rgba(36,24,18,.13)"
    acc = AMBER if dark else AMBER_D
    parts = text.split("\n")
    head = parts[0]
    sub = parts[1] if len(parts) > 1 else ""
    flag = '<span class="flag">사실 전달</span>' if (sensitive and i == 0) else ""
    dots = "".join(f'<span class="dot {"cur" if k==i else ""}"></span>' for k in range(n))
    size = 88 if i == 0 else 60
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    *{{margin:0;box-sizing:border-box}}html,body{{width:1080px;height:1350px}}
    .s{{width:1080px;height:1350px;background:{bg};color:{fg};padding:100px 92px 84px;
      font-family:'Pretendard','Noto Sans CJK KR',sans-serif;display:flex;flex-direction:column;
      position:relative;overflow:hidden;-webkit-font-smoothing:antialiased}}
    .glow{{position:absolute;top:-160px;right:-160px;width:600px;height:600px;border-radius:50%;
      background:radial-gradient(circle,{('rgba(227,155,51,.22)' if dark else 'rgba(227,155,51,.13)')},transparent 68%)}}
    .top{{display:flex;justify-content:space-between;align-items:center;font-size:25px;font-weight:600;z-index:1}}
    .ser{{display:flex;align-items:center;gap:14px}}.ser::before{{content:"";width:16px;height:16px;
      border-radius:50%;background:{acc}}}
    .pg{{color:{muted};letter-spacing:.08em}}
    .mid{{flex:1;display:flex;flex-direction:column;justify-content:center;z-index:1}}
    .eye{{display:flex;gap:16px;align-items:center;font-size:26px;font-weight:700;color:{acc};
      letter-spacing:.12em;margin-bottom:32px}}.eye::before{{content:"";width:44px;height:2px;background:{acc}}}
    .flag{{margin-left:14px;font-size:20px;font-weight:700;color:{bg};background:{acc};
      padding:4px 14px;border-radius:20px;letter-spacing:0}}
    h1{{font-size:{size}px;font-weight:800;line-height:1.28;letter-spacing:-.015em;word-break:keep-all}}
    .sub{{margin-top:36px;font-size:36px;font-weight:500;line-height:1.5;color:{muted};
      word-break:keep-all;max-width:840px}}
    .foot{{display:flex;justify-content:space-between;align-items:center;z-index:1}}
    .dots{{display:flex;gap:12px}}.dot{{width:12px;height:12px;border-radius:50%;background:{line}}}
    .dot.cur{{background:{acc};width:34px;border-radius:6px}}
    .seal{{width:78px;height:78px;border-radius:50%;border:2px solid {fg};display:flex;
      align-items:center;justify-content:center;color:{fg};font-size:23px;font-weight:700;opacity:.85}}
    </style></head><body><div class="s"><div class="glow"></div>
    <div class="top"><span class="ser">트렌드 브리핑</span><span class="pg">{i+1:02d} / {n:02d}</span></div>
    <div class="mid"><div class="eye">{eyebrow}{flag}</div><h1>{head}</h1>
    {f'<p class="sub">{sub}</p>' if sub else ''}</div>
    <div class="foot"><div class="dots">{dots}</div><div class="seal">브리핑</div></div>
    </div></body></html>"""

def render(copy, out_dir, sensitive=False, slug="trend"):
    os.makedirs(out_dir, exist_ok=True)
    slides = copy["slides"]
    n = len(slides)
    eyebrows = ["오늘의 이슈"] + ["사실"] * (n - 2) + ["마무리"]
    themes = ["esp"] + ["ivory" if k % 2 else "esp" for k in range(1, n)]
    paths = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
        for i, text in enumerate(slides):
            pg.set_content(_slide_html(i, n, text, themes[i], eyebrows[i], sensitive),
                           wait_until="networkidle")
            fp = os.path.join(out_dir, f"{slug}_{i+1:02d}.png")
            pg.locator(".s").screenshot(path=fp)
            paths.append(fp)
        b.close()
    return paths
