# -*- coding: utf-8 -*-
"""
재료(위키 리드 + 관련 뉴스) → 숫자·인물·시점이 살아있는 한국어 카드뉴스 카피.
ANTHROPIC_API_KEY 있으면 Claude 실호출, 없으면 재료 기반 템플릿 폴백.
민감 주제는 '사실 전달만, 평가 없음' 모드.
"""
import os, json, re

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

SYS = """너는 한국어 카드뉴스 에디터다. 주어진 '재료'(위키 리드, 관련 뉴스)에서 구체적 사실을 뽑아
카드뉴스를 만든다.

원칙:
- 재료에 실제로 있는 인물·직책·날짜·숫자·작품명을 최대한 구체적으로 살린다. (예: 감독 이름, 출연진, 개봉 연도, 금액, 수치)
- 재료에 없는 사실·숫자는 절대 지어내지 않는다. 모르면 쓰지 않는다.
- 직역 금지, 자연스러운 한국어. 번역투 금지.
- 개인적 평가·추측·선동 금지. '이런 일이 있었다' 수준의 사실 전달.
- 민감 주제(사고·사망·재난·정치)는 특히 중립적 사실만.
- 과장·클릭베이트 금지.

분량(중요):
- 재료가 풍부하면 최대 10장까지 만든다.
- 재료가 얕으면 억지로 늘리지 말고 6장으로 줄인다. 같은 말 반복·빈 문장으로 채우기 금지.
- 즉 6~10장 사이에서 재료의 실제 정보량에 맞춰 자연스럽게 정한다.

슬라이드 구성(재료가 충분할 때 10장 예시, 부족하면 앞쪽 위주로 압축):
1) 표지: 무슨 이슈인지 한눈에 (제목 + 한 줄)
2) 한 줄 요약: 핵심을 한 문장으로
3) 핵심 인물/주체: 누가 (이름·직책 구체적으로)
4) 인물의 역할·관계: 그들이 무엇을 했나
5) 숫자·규모 팩트: 연도·수치·금액·규모
6) 시점·타임라인: 언제 일어났나/진행됐나
7) 배경: 어쩌다 이렇게 됐나
8) 왜 지금 화제인가
9) 알아둘 포인트: 놓치기 쉬운 사실
10) 마무리: 출처 확인 유도(평가 없음)

각 슬라이드는 '제목\\n부가설명' 형식 문자열. 제목은 짧게, 부가설명은 1문장.
반드시 아래 JSON만 출력. 다른 텍스트 금지.
{"ko_title":"...","why_ko":"...","slides":["...", "... (6~10개)"]}"""

def _material_text(m):
    lines = [f"제목: {m.get('title','')}"]
    if m.get("description"): lines.append(f"설명: {m['description']}")
    if m.get("headline"): lines.append(f"헤드라인: {m['headline']}")
    if m.get("lead"): lines.append(f"위키 리드:\n{m['lead']}")
    if m.get("news"):
        lines.append("관련 뉴스:")
        for a in m["news"]:
            lines.append(f" - [{a.get('date','')[:8]}] {a.get('domain','')}: {a.get('title','')}")
    return "\n".join(lines)

def _anthropic(material, sensitive):
    try:
        from anthropic import Anthropic
    except Exception:
        return None
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        client = Anthropic(api_key=key)
        user = (f"[재료]\n{_material_text(material)}\n\n"
                f"[민감 주제 여부] {sensitive}\n"
                f"위 재료에서 구체적 사실(인물·직책·연도·숫자)을 뽑아 카드뉴스로. "
                f"재료가 풍부하면 최대 10장, 얕으면 6장. 재료에 없는 건 쓰지 마라.")
        msg = client.messages.create(model=MODEL, max_tokens=1300,
                                     system=SYS, messages=[{"role": "user", "content": user}])
        txt = "".join(b.text for b in msg.content if b.type == "text")
        txt = re.sub(r"^```json|```$", "", txt.strip()).strip()
        data = json.loads(txt)
        if data.get("slides"):
            return data
    except Exception as e:
        print("[llm] anthropic err", e)
    return None

def _fallback(material, sensitive):
    """키 없을 때: 재료(위키 리드)를 문장 단위로 쪼개 재료량만큼만 슬라이드 구성(6~10)."""
    lead = material.get("lead", "") or material.get("headline", "")
    sents = re.split(r"(?<=[.!?]) +", lead)
    sents = [s.strip() for s in sents if len(s.strip()) > 20][:8]  # 최대 8개 사실
    t = material.get("title", "")
    note = "사실 관계만 정리했습니다. 출처를 직접 확인하세요." if sensitive \
        else "핵심만 정리했습니다. 자세한 내용은 출처에서 확인하세요."
    slides = [f"{t}\n무슨 일이 있었나"]
    for s in sents:
        head = s[:34] + ("…" if len(s) > 34 else "")
        slides.append(f"{head}\n{s}")
    # 재료가 얕으면 6장 미만일 수 있으니 최소 표지+마무리만 보장, 억지 반복 없음
    slides.append(note)
    return {"ko_title": t, "why_ko": material.get("headline", ""),
            "slides": slides[:10], "_fallback": True}

def localize(topic, material=None, sensitive=False):
    material = material or {"title": topic.get("title", ""), "headline": topic.get("headline", "")}
    return _anthropic(material, sensitive) or _fallback(material, sensitive)
