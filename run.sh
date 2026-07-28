#!/usr/bin/env bash
set -e
pip install -r requirements.txt --break-system-packages
python -m playwright install chromium
# Pretendard 폰트 설치(한글 렌더 품질)
mkdir -p ~/.fonts && python - <<'PY'
import urllib.request,os
base="https://github.com/orioncactus/pretendard/raw/main/packages/pretendard/dist/public/static"
for w in ["Regular","Medium","SemiBold","Bold","ExtraBold","Black"]:
    p=os.path.expanduser(f"~/.fonts/Pretendard-{w}.otf")
    if not os.path.exists(p):
        urllib.request.urlretrieve(f"{base}/Pretendard-{w}.otf",p)
PY
fc-cache -f >/dev/null 2>&1 || true
uvicorn app:app --host 0.0.0.0 --port 8000
