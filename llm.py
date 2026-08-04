# -*- coding: utf-8 -*-
"""
카피 생성 v3 — 에디토리얼 문단형.
슬라이드 구조: {"title": "...", "body": "문단 (**볼드** 마커 포함)", "img": true/false}
재료: Guardian 전문 + 위키 + NewsAPI + Reddit/HN 반응.
+ 인스타 캡션(caption): 기사 본문 기반 20줄 내외 상세 설명 + 해시태그.
"""
import os, json, re

MODEL = lambda: os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

SYS = """너는 한국 '경제·증시·부동산' 전문 매거진 에디터다. 주어진 재료(기사 전문·위키·
커뮤니티 반응)로 인스타그램 카드뉴스를 만든다. 톤은 '~습니다/~에요'를 섞은, 차분하고
신뢰감 있는 경제 에디토리얼체. 감정·과장 없이 사실과 숫자로 말한다.

[핵심 정체성] 이 계정은 "확인된 숫자로만 말하는 경제 계정"이다.
- 재료에 있는 구체 수치(지수·금리·시세·거래량·금액·%·순위·날짜)를 최우선으로 살린다.
- 숫자는 절대 지어내지 않는다. 재료에 없는 수치는 쓰지 않는다.

[key_numbers — 숫자 비교 카드용]
기사 재료에서 핵심 수치를 2~4개 뽑아 key_numbers 배열로 반환한다. 각 항목:
  {"value": "2,510.34", "label": "코스피 종가", "delta": "+1.2%"}
- value: 숫자 그 자체(단위 포함 가능: 2,510 / 3,200억 / 4.5% / 1위)
- label: 그 숫자가 뭔지 짧게 (8자 이내)
- delta: 증감/부가정보 있으면 (예: +1.2%, 전일比 -30p). 없으면 "" 또는 생략
재료에 숫자가 마땅치 않으면 key_numbers는 빈 배열 []로 둔다(억지로 만들지 않는다).

구성 (재료가 풍부하면 8~10장, 얕으면 최소 6장):
1. 표지: title만 강렬하게, body는 1~2문장 훅
2. 무슨 일: 사건 핵심을 문단으로
3~4. 상세 사실: 기관·숫자·타임라인 (재료의 구체 정보 총동원)
5~6. 배경·맥락: 어쩌다 이렇게 됐고 왜 중요한가 (시장/자산에 주는 의미)
7. 반응: 재료에 반응이 있으면 문단 (없으면 생략)
8. 전망 or 알아둘 점
9. 마무리: 요약 + 출처 확인 유도. 마지막 문장은 독자 참여 질문 (예: "여러분 생각은 어떤가요?")

[민감 주제 처리 — 중요]
사고·사망·재난·정치 등 민감 주제라도 카드 수나 분량을 줄이지 않는다. 우리는 사견 없이
재료의 사실만 전달하므로, 민감할수록 오히려 사실 관계(경위·시점·수치·경과·관계 기관)를
충분히·정확히 담는다. 일반 주제와 동일하게 재료가 풍부하면 8~10장을 만든다.
- 조정하는 것: 톤(자극적·선정적 묘사 배제, 중립·담담한 서술, 피해자 존중)
- 조정하지 않는 것: 카드 수, 문단 길이, 사실의 양
- 자극적 표현·추측·평가만 피하고, 확인된 사실은 빠짐없이 서술한다.

각 슬라이드 형식:
- title: 짧고 강한 헤드라인 (10~18자, 줄바꿈 가능: \\n 사용)
- body: 3~5문장의 문단. 핵심 단어·숫자는 **볼드**로 감싼다 (한 문단에 2~4개).
  재료에 있는 구체적 사실(기관명·인물·직책·날짜·금액·수치)을 반드시 살린다.
  재료에 없는 사실·숫자는 절대 지어내지 않는다.
- img: 이 슬라이드에 사진이 들어가면 좋은지 true/false

[인스타 캡션 — caption 필드]
카드뉴스와 별개로, 게시물 설명글(캡션)을 작성한다. 규칙:
- 기사 본문(재료)의 내용을 바탕으로 한 상세 설명. 카드 요약이 아니라 '본문을 안 봐도
  이해되는 완결된 글'로 쓴다.
- 분량: 18~22줄(줄바꿈 포함) 내외. 문단은 2~4개로 나누고 문단 사이 빈 줄을 넣는다.
- 첫 줄은 후킹 헤드라인 한 줄. 이후 문단에서 핵심 사실·배경·맥락·의미를 서술.
- 재료에 있는 구체 사실(기관·인물·날짜·금액·수치)을 최대한 반영. 없는 건 지어내지 않는다.
- 마지막 문단 뒤에 해시태그를 5~8개 넣는다. 형식은 공백 구분 한 줄(예: #경제 #증시).
  해시태그는 주제·분야에서 자연스럽게 뽑고, 과하거나 무관한 건 넣지 않는다.
- 캡션 안에는 HTML 태그를 쓰지 않는다. **볼드** 마커도 캡션에는 넣지 않는다(순수 텍스트).
- 출처 URL은 캡션에 직접 쓰지 않는다(코드가 맨 아래 자동으로 붙인다).

규칙:
- 직역·번역투 금지. 과장·클릭베이트 금지.
- 개인 평가·투자 권유·선동 금지. 사실·숫자 전달만. 민감 주제는 '톤'만 중립으로 하되, 분량·카드 수는 줄이지 않는다.
- 볼드는 **단어** 형식만 사용(슬라이드 body에만).

JSON만 출력:
{"ko_title":"...","why_ko":"...","caption":"18~22줄 캡션 + 해시태그","key_numbers":[{"value":"...","label":"...","delta":"..."}],"slides":[{"title":"...","body":"...","img":true}, ...]}"""

def _material_text(m):
    L = [f"제목: {m.get('title','')}"]
    if m.get("description"): L.append(f"설명: {m['description']}")
    if m.get("headline"):    L.append(f"트렌드 헤드라인: {m['headline']}")
    if m.get("lead"):        L.append(f"\n[위키 배경]\n{m['lead']}")
    for i, a in enumerate(m.get("guardian", [])[:3], 1):
        meta = ", ".join(x for x in [a.get("section",""), a.get("date","")] if x)
        head = a.get("title","")
        body = a.get("body","")
        L.append(f"\n[기사{i}] {head}" + (f" ({meta})" if meta else "") + f"\n{body[:2000]}")
    if m.get("news"):
        L.append("\n[추가 헤드라인]")
        for a in m["news"]:
            L.append(f"- [{a.get('date','')}] {a.get('domain','')}: {a.get('title','')} — {a.get('body','')[:150]}")
    if m.get("reddit"):
        L.append("\n[Reddit 반응]")
        for p in m["reddit"]:
            L.append(f"- r/{p['sub']} ({p['ups']:,}↑ {p['comments']:,}💬): {p['title'][:100]}")
    if m.get("hn"):
        L.append("\n[Hacker News 반응]")
        for h in m["hn"]:
            L.append(f"- ({h['points']}pts {h['comments']}💬): {h['title'][:100]}")
    return "\n".join(L)

def _anthropic(material, sensitive):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key: return None
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=key)
        user = (f"[재료]\n{_material_text(material)[:9000]}\n\n"
                f"[민감 주제] {sensitive}\n"
                f"위 재료로 에디토리얼 카드뉴스와 인스타 캡션을 만들어라. 구체적 사실을 최대한 살려라.")
        msg = client.messages.create(model=MODEL(), max_tokens=6000,
                                     system=SYS, messages=[{"role": "user", "content": user}])
        txt = "".join(b.text for b in msg.content if b.type == "text")
        data = _safe_json(txt)
        if data and data.get("slides") and isinstance(data["slides"][0], dict):
            return data
        print("[llm] parse failed, len=", len(txt))
    except Exception as e:
        print("[llm] err", e)
    return None

def _safe_json(txt):
    """마크다운 펜스 제거 + 잘린 JSON 복구 시도."""
    t = txt.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    # 1) 그대로 파싱
    try:
        return json.loads(t)
    except Exception:
        pass
    # 2) 잘린 경우: 마지막 완전한 슬라이드까지만 살려서 배열/객체 닫기
    try:
        # slides 배열에서 완결된 } 까지 자르기
        idx = t.rfind("},")
        if idx > 0:
            repaired = t[:idx+1] + "]}"
            return json.loads(repaired)
    except Exception:
        pass
    # 3) 객체 하나라도 건지기
    try:
        objs = re.findall(r'\{[^{}]*"title"[^{}]*"body"[^{}]*\}', t, re.S)
        slides = [json.loads(o) for o in objs]
        if slides:
            title = (re.search(r'"ko_title"\s*:\s*"([^"]+)"', t) or [None, ""])
            cap   = (re.search(r'"caption"\s*:\s*"((?:[^"\\]|\\.)*)"', t) or [None, ""])
            return {"ko_title": title[1] if isinstance(title, list) else "",
                    "why_ko": "",
                    "caption": (cap[1].encode().decode("unicode_escape")
                                if isinstance(cap, list) and cap[1] else ""),
                    "slides": slides}
    except Exception:
        pass
    return None

def _fallback(material, sensitive):
    """키 없음/실패 시: 재료 문장으로 구조화 슬라이드 구성."""
    src = ""
    for a in material.get("guardian", []):
        src += a.get("body", "") + " "
    src = src or material.get("lead", "") or material.get("headline", "")
    sents = [s.strip() for s in re.split(r"(?<=[.!?]) +", src) if len(s.strip()) > 30][:14]
    t = material.get("title", "")
    slides = [dict(title=t, body=(sents[0] if sents else "무슨 일이 있었는지 정리했습니다."), img=True)]
    # 2문장씩 묶어 문단화
    for i in range(1, len(sents)-1, 2):
        para = " ".join(sents[i:i+2])
        slides.append(dict(title=para[:20]+"…", body=para, img=(len(slides) % 2 == 0)))
        if len(slides) >= 9: break
    note = "사실 관계만 정리했습니다. 출처를 직접 확인하세요." if sensitive \
        else "핵심만 정리했습니다. 자세한 내용은 출처에서 확인하세요."
    slides.append(dict(title="마무리", body=note + " 여러분 생각은 어떤가요?", img=False))
    # 폴백 캡션: 앞 문장들을 이어붙여 상세 설명 구성 + 기본 해시태그
    body_para = " ".join(sents[:8]).strip()
    cap = (f"{t}\n\n{body_para}\n\n"
           "자세한 내용은 아래 출처에서 확인하세요.\n\n"
           "#트렌드 #이슈 #뉴스 #오늘의뉴스 #트렌드브리핑") if body_para else ""
    return {"ko_title": t, "why_ko": material.get("headline", ""),
            "caption": cap, "key_numbers": [], "slides": slides[:10], "_fallback": True}

def localize(topic, material=None, sensitive=False):
    material = material or {"title": topic.get("title", ""),
                            "headline": topic.get("headline", "")}
    return _anthropic(material, sensitive) or _fallback(material, sensitive)
