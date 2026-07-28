# -*- coding: utf-8 -*-
"""
해외 트렌드 → 자연스러운 한국어 현지화 + 카드뉴스 카피 생성.
ANTHROPIC_API_KEY 있으면 Claude 실호출, 없으면 템플릿 폴백(키 없이도 동작).
민감(sensitive) 주제는 '사실 전달만, 평가 없음' 모드로 강제.
"""
import os, json, re

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

SYS = """너는 한국어 카드뉴스 에디터다. 해외에서 뜨는 이슈를 한국 독자에게 자연스럽게 전달한다.
규칙:
- 직역이 아니라 현지화. 어색한 번역투 금지.
- 사실만 전달. 개인적 평가·추측·선동 금지. '이런 일이 있었다' 수준.
- 민감 주제(사고·사망·재난·정치)는 특히 중립적 사실 전달만.
- 과장·클릭베이트·근거 없는 수치 금지.
반드시 아래 JSON만 출력한다. 다른 텍스트 금지.
{"ko_title": "...", "why_ko": "...", "slides": ["표지 문구","사실1","사실2","사실3","마무리(출처 확인 유도, 평가 없음)"]}"""

def _anthropic(topic, sensitive):
    try:
        from anthropic import Anthropic
    except Exception:
        return None
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        client = Anthropic(api_key=key)
        user = (f"원제목: {topic['title']}\n헤드라인: {topic.get('headline','')}\n"
                f"카테고리: {topic.get('category','')}\n민감: {sensitive}\n"
                f"왜 떴는지(신호): {topic.get('why','')}\n"
                f"이 이슈를 한국어 5장 카드뉴스 카피로. 사실 전달만.")
        msg = client.messages.create(model=MODEL, max_tokens=800,
                                     system=SYS, messages=[{"role": "user", "content": user}])
        txt = "".join(b.text for b in msg.content if b.type == "text")
        txt = re.sub(r"^```json|```$", "", txt.strip()).strip()
        return json.loads(txt)
    except Exception as e:
        print("[llm] anthropic err", e)
        return None

def _fallback(topic, sensitive):
    t = topic["title"]
    head = topic.get("headline", "")
    note = "사실 관계만 정리했습니다. 출처를 직접 확인하고 판단하세요." if sensitive \
        else "핵심만 짧게 정리했습니다. 자세한 내용은 출처에서 확인하세요."
    return {
        "ko_title": t,                       # 키 없으면 원문 유지(+ 번역 필요 안내)
        "why_ko": topic.get("why", ""),
        "slides": [
            f"{t}\n무슨 일이 있었나",
            head[:70] or "지금 여러 소스에서 동시에 언급되는 이슈입니다.",
            f"주요 신호: {topic.get('why','')}",
            "관련 보도가 이어지고 있습니다.",
            note,
        ],
        "_fallback": True,
    }

def localize(topic, sensitive=False):
    return _anthropic(topic, sensitive) or _fallback(topic, sensitive)
