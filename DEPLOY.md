# 배포 가이드 — GitHub + Railway

로컬에서 켤 필요 없이, GitHub에 올리면 Railway가 자동 빌드해서 **공개 URL로 24시간** 돌립니다.

## 0. 준비물
- GitHub 계정
- Railway 계정 (railway.app — GitHub으로 로그인)
- (선택) 카피 품질용 `ANTHROPIC_API_KEY`, 발행용 Meta 토큰

## 1. GitHub에 올리기  — 쉬운 방법(GitHub Desktop, 추천)
1. GitHub Desktop 설치 → 로그인
2. File → Add local repository → 압축 푼 `trendcast` 폴더 선택
   - "이 폴더는 저장소가 아니다" 뜨면 **create a repository** 클릭
3. 왼쪽 아래에 커밋 메시지(예: `init`) 입력 → **Commit to main**
4. 상단 **Publish repository** → 이름 정하고 (Private 체크 가능) → Publish

### (또는) 명령어로 올리기
```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<아이디>/<저장소>.git
git push -u origin main
```

## 2. Railway로 배포
1. railway.app → **New Project** → **Deploy from GitHub repo**
2. 방금 올린 저장소 선택 → Railway가 **Dockerfile을 자동 감지**해서 빌드 시작
   (첫 빌드는 크로미엄·폰트 설치로 몇 분 걸립니다)
3. 빌드가 끝나면 **Settings → Networking → Generate Domain** 클릭
   → `https://<이름>.up.railway.app` 공개 주소가 생깁니다. 그 주소로 접속!

> `$PORT`는 Railway가 자동 주입하고 Dockerfile이 그걸로 바인딩합니다. 따로 설정 불필요.

## 3. 환경변수 (선택 — Variables 탭에서 추가)
| 변수 | 용도 |
|---|---|
| `ANTHROPIC_API_KEY` | 해외 이슈 자연스러운 한국어 현지화 (없으면 템플릿) |
| `CLAUDE_MODEL` | 기본 `claude-sonnet-5` |
| `META_ACCESS_TOKEN` | 인스타/스레드 발행 토큰 |
| `IG_USER_ID` / `THREADS_USER_ID` | 대상 계정 ID |
| `PUBLIC_IMAGE_BASE` | 발행 시 이미지 공개 URL 베이스. Railway 주소 + 끝 슬래시 없이 (예: `https://xxx.up.railway.app`) |

변수 저장하면 Railway가 자동 재배포합니다.

## 4. 코드 수정 → 자동 반영
GitHub에 push(또는 GitHub Desktop에서 Commit→Push)하면 Railway가 감지해서 자동으로 다시 빌드·배포합니다.

## 주의점 (지금은 MVP라 감수, 나중에 개선)
- **파일 저장은 임시(ephemeral).** 재배포/재시작하면 `outputs/`의 PNG와 `snapshots.json`(속도 히스토리)이 초기화됩니다.
  - 속도 히스토리·이미지를 유지하려면 나중에 Railway **Volume** 또는 오브젝트 스토리지(S3/Cloudflare R2)로 옮기면 됩니다.
- **발행용 이미지 URL** — Meta Graph API는 공개 접근 가능한 이미지 URL이 필요합니다. `PUBLIC_IMAGE_BASE`를 Railway 주소로 두면 `/outputs/파일.png`가 공개로 열려 발행이 됩니다(단 임시 저장이라 재시작 전까지 유효).
- **메모리** — 크로미엄 렌더는 RAM을 씁니다. 생성이 잦아지면 Railway 플랜을 한 단계 올리세요.
- **비용** — Railway는 무료 영구가 아니라 크레딧/취미 플랜입니다. 사용량 확인하세요.
- **구글 트렌드 RSS는 비공식** — 과호출 시 레이트리밋. 운영 시 캐시·백오프 권장.

## 배포 후 점검
- `https://<주소>/` → 대시보드
- `https://<주소>/api/trends?geo=US&category=전체&n=6` → JSON 트렌드
- 카드 → "카드뉴스 만들기" → PNG 생성 → "인스타/스레드 예약"(토큰 없으면 dry-run)
