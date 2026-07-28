# 크로미엄 + 브라우저 의존성이 미리 깔린 Playwright 공식 이미지
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# 한글 폰트: Noto CJK(안전 폴백) + Pretendard(디자인용)
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /usr/share/fonts/opentype/pretendard \
    && for w in Regular Medium SemiBold Bold ExtraBold Black; do \
         curl -sSL -o /usr/share/fonts/opentype/pretendard/Pretendard-$w.otf \
         "https://github.com/orioncactus/pretendard/raw/main/packages/pretendard/dist/public/static/Pretendard-$w.otf"; \
       done \
    && fc-cache -f

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway가 주입하는 $PORT 로 바인딩 (로컬은 8000)
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
