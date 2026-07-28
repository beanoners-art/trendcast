# Trendcast — 반자동 트렌드 카드뉴스 엔진

뜨는 속도(트렌드 지수)를 1차 기준으로 전 세계 이슈를 종합·추천하고,
사람이 1·2·3 중 골라 한국어 카드뉴스로 만들어 인스타/스레드로 예약 발행하는 **반자동** 홈페이지 앱.

## 지금 동작하는 것 (키 없이)
- **트렌드 수집·랭킹** — 구글 트렌드(급상승 RSS) + 위키피디아(급상승 조회수) + GDELT(서버 정상 시). 전부 키리스.
- **점수화** — 소스별 0~100 정규화 → 이슈 클러스터링 → 트렌드지수(크기×속도, 1차 게이트, 포화 페널티) → 소스교차 확신도 × 관련성(2차) → 랭킹.
- **속도(velocity)** — `snapshots.json`에 매 실행 스냅샷을 저장해 다음 실행 때 상승률을 계산(첫 실행=기준선).
- **카테고리 + 브랜드 세이프티** — 경제·금융/정치/문화·연예/스포츠/기술·IT/기타 자동 분류. 민감(사고·사망·재난·정치)은 **제외하지 않고 ‘사실 전달’ 배지**로 표시.
- **‘왜 떴는지’** — 어떤 신호가 켜졌는지 사실 근거만 표시.
- **카드뉴스 렌더** — 1080×1350 PNG 자동 생성(사실 전달형 디자인).
- **발행 dry-run** — 자격증명이 없으면 “무엇을 올릴지”만 반환(실제 발행 안 함).

## 키를 넣으면 켜지는 것
- `ANTHROPIC_API_KEY` → 해외 이슈를 **자연스러운 한국어로 현지화**하고 카피 품질 상승(없으면 템플릿 폴백).
- `META_ACCESS_TOKEN` / `IG_USER_ID` / `THREADS_USER_ID` / `PUBLIC_IMAGE_BASE` → **인스타·스레드 실제 발행**.
  - 인스타/스레드 발행은 Meta 개발자 앱 + 비즈니스/크리에이터 계정 + OAuth 토큰 + (권한에 따라) 앱 심사가 필요합니다. 이건 계정 소유자만 발급 가능하며, 코드는 실제 Graph API 호출까지 완성돼 있어 키만 꽂으면 동작합니다.
  - Graph API는 **공개 접근 가능한 이미지 URL**이 필요합니다(S3/CDN 등). 로컬 파일은 그대로 못 올립니다.

## 나중에 붙일 소스 (별도 요청)
- **YouTube Data API**(조회·좋아요·댓글), **Reddit API**(업보트·댓글), **네이버 데이터랩**(국내 검색 트렌드) — 무료지만 키/앱 등록 필요. `engine.py`의 `fetch_*` 패턴으로 어댑터만 추가하면 됩니다.
- 유료 제3자 소셜 데이터(틱톡·인스타 공개지표) — 예산 결정 후.

## 실행
```bash
cd trendcast
cp .env.example .env      # (선택) 키 입력
bash run.sh               # 의존성 설치 + 크로미엄/폰트 + 서버 기동
# http://localhost:8000
```
수동 실행:
```bash
pip install -r requirements.txt --break-system-packages
python -m playwright install chromium
uvicorn app:app --port 8000
python engine.py 전체     # CLI로 트렌드 랭킹만 확인
```

## 구조
```
app.py               FastAPI: /  /api/trends  /api/generate  /api/publish
engine.py            수집·정규화·클러스터·속도·점수·카테고리·세이프티
llm.py               현지화/카피 (Anthropic 실호출 or 템플릿 폴백)
render_carousel.py   카피 → 1080x1350 PNG (Playwright)
publish.py           인스타/스레드 Graph API 어댑터 (creds 없으면 dry-run)
static/index.html    대시보드(카테고리·지역 필터, 점수·근거, 생성, 발행)
snapshots.json       속도 계산용 스냅샷 저장(자동 생성)
outputs/             생성된 PNG
```

## 점수 로직 요약
```
trend_index = norm(소스내 백분위) × vboost(상승=부스트/하락=페널티)   # 1차 게이트
final       = trend_index × confidence(소스교차) × relevance(카테고리)  # 2차
# 하락(velocity<-0.3)·저점(norm<5) 제거
```
좋아요·댓글 부스트는 YouTube/Reddit 어댑터를 붙이면 `final`에 곱셈으로 합류하도록 설계돼 있습니다.

## 법적·안전 메모
- 남의 게시물 **원문 번역 재게시**는 저작권 문제 → 트렌드는 **입력 신호로만** 쓰고 한국어 **오리지널**로 재해석.
- 남의 계정 대량 자동 포스팅 미지원. **본인 계정 반자동**만.
- 민감 주제는 **사실 전달만**, 평가·추측 없음. 발행 여부는 사람이 최종 선택.
- 구글 트렌드 RSS는 비공식 → 레이트리밋 가능. 운영 시 캐시/백오프 권장.
