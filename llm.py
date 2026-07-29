# -*- coding: utf-8 -*-
"""
카피 생성 v3 — 에디토리얼 문단형.
슬라이드 구조: {"title": "...", "body": "문단 (**볼드** 마커 포함)", "img": true/false}
재료: Guardian 전문 + 위키 + NewsAPI + Reddit/HN 반응.
"""
import os, json, re

MODEL = lambda: os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

SYS = """너는 한국 매거진 에디터다. 주어진 재료(기사 전문·위키·커뮤니티 반응)로
인스타그램 카드뉴스를 만든다. 톤은 '~습니다/~에요'를 섞은 자연스러운 에디토리얼체.

각 슬라이드 형식:
- title: 짧고 강한 헤드라인 (10~18자, 줄바꿈 가능: \\n 사용)
- body: 4~7문장의 문단. 핵심 단어는 **볼드**로 감싼다 (한 문단에 2~4개).
  재료에 있는 구체적 사실(인물 이름·직책·날짜·금액·수치·기관명)을 반드시 살린다.
  재료에 없는 사실·숫자는 절대 지어내지 않는다.
- img: 이 슬라이드에 사진이 들어가면 좋은지 true/false

구성 (재료가 풍부하면 8~10장, 얕으면 6장):
1. 표지: title만 강렬하게, body는 1~2문장 훅
2. 무슨 일: 사건 핵심을 문단으로
3~4. 상세 사실: 인물·숫자·타임라인 (재료의 구체 정보 총동원)
5~6. 배경·맥락: 어쩌다 이렇게 됐고 왜 중요한가
7. 반응: 재료에 Reddit/HN 반응이 있으면 "커뮤니티에선 ~" 문단 (없으면 생략)
8. 전망 or 알아둘 점
9. 마무리: 요약 + 출처 확인 유도. 마지막 문장은 독자 참여 질문 (예: "여러분 생각은 어떤가요?")

규칙:
- 직역·번역투 금지. 과장·클릭베이트 금지.
- 개인 평가·선동 금지. 사실 전달만. 민감 주제(사고·사망·재난·정치)는 특히 중립.
- 볼드는 **단어** 형식만 사용.

JSON만 출력:
{"ko_title":"...","why_ko":"...","slides":[{"title":"...","body":"...","img":true}, ...]}"""

def _material_text(m):
    L = [f"제목: {m.get('title','')}"]
    if m.get("description"): L.append(f"설명: {m['description']}")
    if m.get("headline"):    L.append(f"트렌드 헤드라인: {m['headline']}")
    if m.get("lead"):        L.append(f"\n[위키 배경]\n{m['lead']}")
    for i, a in enumerate(m.get("guardian", [])[:3], 1):
        L.append(f"\n[기사{i}] {a['title']} ({a['section']}, {a['date']})\n{a['body'][:2000]}")
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
                f"위 재료로 에디토리얼 카드뉴스를 만들어라. 구체적 사실을 최대한 살려라.")
        msg = client.messages.create(model=MODEL(), max_tokens=3000,
                                     system=SYS, messages=[{"role": "user", "content": user}])
        txt = "".join(b.text for b in msg.content if b.type == "text")
        txt = re.sub(r"^```json|```$", "", txt.strip()).strip()
        data = json.loads(txt)
        if data.get("slides") and isinstance(data["slides"][0], dict):
            return data
    except Exception as e:
        print("[llm] err", e)
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
    return {"ko_title": t, "why_ko": material.get("headline", ""),
            "slides": slides[:10], "_fallback": True}

def localize(topic, material=None, sensitive=False):
    material = material or {"title": topic.get("title", ""),
                            "headline": topic.get("headline", "")}
    return _anthropic(material, sensitive) or _fallback(material, sensitive)
