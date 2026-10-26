"""장표 결 고르기 — 요청 문장의 낱말을 결 꼬리표(용도 · 분위기 · 격식 · 어두움)에 대어 상위 셋을 고른다 (2026-10-25).

대표: 「모델 입장에서도 기준점이 있어야 고를 수 있다」. 임베딩 없이 낱말 → 꼬리표 점수로 고른다 — 왜 골랐는지 말할 수 있고, 잴 수 있다.
결 목록은 `slides_style.THEMES`(손 결 + 옮긴 원본 템플릿 18개 · `slide_themes/templates/index.json`).
5차의 「색만 옮긴 설계표 35개」는 걷어 냈다(대표 「템플릿이 별로」 — 원본 배치를 버리고 색만 가져와서).
"""

from __future__ import annotations

#: 손으로 쓴 결의 꼬리표(숨긴 forest · emerald · cobalt 는 고르기에 안 넣는다).
HAND_TAGS: dict[str, tuple[tuple[str, ...], tuple[str, ...], str, bool]] = {
    "paper": (("보고", "회의", "계획", "소개", "업무", "사업계획"), ("차분", "신뢰"), "보통", False),
    "ink": (("제품", "기술", "성능", "개발", "데이터"), ("기술적", "차분"), "보통", True),
}


def all_tags() -> dict[str, tuple[tuple[str, ...], tuple[str, ...], str, bool]]:
    from .slides_style import TEMPLATES

    tags = dict(HAND_TAGS)
    tags.update({key: (tuple(meta["uses"]), tuple(meta["moods"]), meta["formality"], bool(meta["dark"]))
                 for key, meta in TEMPLATES.items()})
    return tags


_USE_WORDS: dict[str, tuple[str, ...]] = {
    "투자": ("투자", "IR", "ir", "피칭", "피치", "VC", "시드", "시리즈", "엔젤", "펀딩"),
    # IR 이라고 콕 집은 말 — 우리 IR 결(ir-brief)만 이 꼬리표를 가진다(대표 10-25: 「IR 은 PPT 로 붙어야」).
    "IR": ("IR", "피치덱", "피치 덱", "투자 설명", "투자설명", "데모데이", "투자 유치", "투자유치",
           "발표 평가", "발표평가", "대면 평가", "대면평가"),
    "사업계획": ("사업계획", "사업 계획", "사업계획서", "창업", "비즈니스 모델"),
    "창업": ("창업", "스타트업"),
    "보고": ("보고", "현황", "실적", "결과 보고", "브리핑"),
    "주간": ("주간", "위클리", "주별"), "분기": ("분기", "쿼터", "QBR"), "운영": ("운영",),
    "회의": ("회의", "미팅", "안건", "워크숍"), "결재": ("결재", "품의", "내부 보고"),
    "소개": ("소개", "회사소개", "회사 소개", "서비스 소개", "제품 소개"),
    "브랜드": ("브랜드", "브랜딩"), "마케팅": ("마케팅", "홍보", "SNS", "인스타", "광고", "캠페인"),
    "캠페인": ("캠페인",), "광고": ("광고",),
    "제품": ("제품", "신제품", "서비스", "앱", "출시", "런칭", "기능"), "출시": ("출시", "런칭", "업데이트"),
    "기술": ("기술", "개발", "AI", "인공지능", "소프트웨어", "시스템", "아키텍처", "엔지니어"),
    "개발": ("개발", "코드", "서버"), "데이터": ("데이터", "지표", "대시보드", "통계"), "성능": ("성능", "속도", "벤치"),
    "설계": ("설계", "구조", "공학", "건축"),
    "강의": ("강의", "수업", "교육", "강좌", "학생", "교재", "튜토리얼"), "교육": ("교육", "학습", "연수"),
    "커리큘럼": ("커리큘럼", "교육과정", "교육 과정"), "온보딩": ("온보딩", "신입"),
    "연구": ("연구", "실험", "분석 결과"), "논문": ("논문", "저널"), "학회": ("학회", "컨퍼런스", "심포지엄"),
    "학위": ("학위", "졸업", "석사", "박사"), "심사": ("심사", "디펜스"), "세미나": ("세미나", "랩미팅"),
    "조사": ("조사", "리서치", "설문"), "리서치": ("리서치", "시장 조사"), "동향": ("동향", "트렌드", "뉴스"),
    "재무": ("재무", "매출", "손익", "예산", "회계", "결산"), "연간": ("연간", "연차", "올해"),
    "M&A": ("M&A", "인수", "합병", "밸류에이션"),
    "행사": ("행사", "축제", "파티", "송년", "신년", "시상", "기념"), "영업": ("영업", "세일즈"),
    "킥오프": ("킥오프", "출정"), "결산": ("결산", "회고", "돌아보"), "연말": ("연말", "송년", "한 해"),
    "디자인": ("디자인", "디자이너", "시안"), "포트폴리오": ("포트폴리오", "작품"), "전시": ("전시", "갤러리"),
    "영상": ("영상", "촬영", "영화", "콘셉트"), "기획": ("기획", "기획안", "아이디어"),
    "전략": ("전략", "컨설팅", "의사결정", "방향"), "임원": ("임원", "경영진", "이사회", "대표"),
    "목표": ("목표", "OKR", "KPI"), "성과": ("성과", "성장"), "프로젝트": ("프로젝트", "로드맵", "일정", "단계"),
    "환경": ("환경", "자연", "식물", "기후"), "웰니스": ("요가", "명상", "건강", "웰니스"),
    "공간": ("공간", "인테리어", "카페", "매장"), "라이프스타일": ("라이프", "패션", "뷰티"),
}
_MOOD_WORDS: dict[str, tuple[str, ...]] = {
    "차분": ("차분", "깔끔", "심플", "미니멀", "단정", "조용"), "깔끔": ("깔끔", "심플", "모던"),
    "신뢰": ("신뢰", "믿음", "전문적", "공식", "격식"),
    "힘있게": ("강렬", "임팩트", "힘 있", "힘있", "대담", "눈에 띄", "세게"),
    "따뜻하게": ("따뜻", "감성", "포근", "부드러"), "부드럽게": ("부드러", "파스텔"),
    "고급": ("고급", "럭셔리", "프리미엄", "세련"), "발랄": ("발랄", "귀여", "재밌", "유쾌", "밝게", "통통"),
    "친근": ("친근", "쉽게", "편하게"), "기술적": ("기술적", "테크", "개발자"),
}
_DARK_WORDS = ("어두운", "다크", "검은", "블랙")
_LIGHT_WORDS = ("밝은", "화이트", "흰 바탕", "흰바탕")
_FORMAL_WORDS = ("격식", "공식", "임원", "이사회", "심사", "투자자", "경영진")
_CASUAL_WORDS = ("가볍게", "편하게", "재밌게", "친구", "동아리", "파티")


def recommend(text: str, k: int = 3) -> list[dict[str, object]]:
    """요청 문장 → 결 상위 k 개와 까닭. 아무것도 안 걸리면 무난한 순서(paper · sidebar · runway)."""
    words = str(text or "")
    found_uses = {tag for tag, keys in _USE_WORDS.items() if any(key in words for key in keys)}
    found_moods = {tag for tag, keys in _MOOD_WORDS.items() if any(key in words for key in keys)}
    want_dark = any(word in words for word in _DARK_WORDS)
    want_light = any(word in words for word in _LIGHT_WORDS)
    formal = any(word in words for word in _FORMAL_WORDS)
    casual = any(word in words for word in _CASUAL_WORDS)
    fallback = ["paper", "editorial-forest", "emerald-editorial", "soft-editorial", "cobalt-grid"]
    scored = []
    for key, (uses, moods, formality, dark) in all_tags().items():
        hit_uses = [tag for tag in uses if tag in found_uses]
        hit_moods = [tag for tag in moods if tag in found_moods]
        score = 3 * len(hit_uses) + 2 * len(hit_moods)
        if want_dark:
            score += 2 if dark else -2
        if want_light and dark:
            score -= 3
        if formal:
            score += 1 if formality == "높음" else -1 if formality == "낮음" else 0
        if casual:
            score += 1 if formality == "낮음" else -1 if formality == "높음" else 0
        # 아무 말도 없으면 어두운 결 · 아주 강한 결은 뒤로(보고서에 갑자기 광고판이 나오지 않게).
        if not found_moods and not want_dark and (dark or key in {"peoples-platform", "sakura-chroma", "daisy-days", "scatterbrain"}):
            score -= 1
        reason = " · ".join(hit_uses + hit_moods) or ""
        order = fallback.index(key) if key in fallback else len(fallback)
        scored.append((score, -order, key, reason))
    scored.sort(reverse=True)
    picks = []
    for score, _, key, reason in scored[:k]:
        label, when = label_of(key)
        picks.append({"theme": key, "name": label, "when": when, "score": score,
                      "why": f"요청의 「{reason}」" if reason else "요청에 분명한 단서가 없어 무난한 결"})
    return picks


def label_of(key: str) -> tuple[str, str]:
    from .slides_style import THEMES

    label, when, _ = THEMES[key]
    return label, when
