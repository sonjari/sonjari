# Third-party notices (packaging)

설치 파일·스토어 패키지에 **같이 실리거나 사용자가 버튼으로 받게 하는** 제3자 소프트웨어 목록.
공개 제출 전에 각 항목의 LICENSE 원문을 이 파일 아래에 붙인다(원문 확인 날짜와 함께).

| 구성요소 | 어떻게 실리나 | 라이선스 | 출처 | 원문 붙임 |
|---|---|---|---|---|
| Ollama (`ollama-windows-amd64.zip`) | 동봉하지 않음 — 첫 실행에서 사용자가 「Ollama 설치」를 누르면 공식 GitHub 릴리스에서 받고 `sha256sum.txt`·자산 digest 와 대조 | MIT | https://github.com/ollama/ollama | ☐ 제출 전 |
| CPython 3.11 | 백엔드 런타임으로 동봉(포장 시험판은 개발 PC 설치본 사본) | PSF License | https://www.python.org | ☐ 제출 전 |
| 파이썬 의존성(`.venv` site-packages) | 동봉 | 패키지별 — SBOM 으로 목록화 필요 | `uv.lock` | ☐ SBOM |
| 스킬 묶음 `addyosmani` (22종, `.md` 만) | 동봉 — `skills/vendor/addyosmani/`, 원본 LICENSE·`SOURCE.json`(커밋 be4e44a9) 같이 둠 | MIT | https://github.com/addyosmani/agent-skills | ☑ 폴더 안 LICENSE |
| 스킬 묶음 `tech-leads-club` (70종, `.md` 만) | 동봉 — `skills/vendor/tech-leads-club/`, 원본 LICENSE·`SOURCE.json`(커밋 0ab82f64) | MIT(코드) · SKILL.md 는 CC-BY-4.0 표기 — 출처 표시 유지 | https://github.com/tech-leads-club/agent-skills | ☑ 폴더 안 LICENSE · ☐ CC-BY 표시 문구 화면 |
| Hermes Agent (코드 일부 옮김) | 소스에 포함 — `src/alture_jarvis/messaging/base.py`(어댑터 틀 · 긴 글 나누기), `discord_adapter.py` · `onboarding.py`(설계를 본떠 다시 씀). base.py 머리에 저작권 · 허가 문구 원문 | MIT (Copyright (c) 2025 Nous Research) | https://github.com/NousResearch/hermes-agent | ☑ base.py 머리 |
| discord.py (+ aiohttp) | `.venv` 에 동봉 — 디스코드 다리(`alture_jarvis.messaging`)만 쓴다 | MIT (discord.py) · Apache-2.0 (aiohttp) | https://github.com/Rapptz/discord.py | ☐ 제출 전 |
| 앤트로픽 `frontend-design` 스킬(생각만 옮김) | 소스에 포함되지 않음 — 「생성된 페이지의 흔한 티」 목록을 장표용으로 줄여 한국어로 다시 씀(`src/alture_jarvis/slides.py` 의 `GUIDE` · `design_tells`) | Apache-2.0 (Copyright Anthropic, PBC) | https://github.com/anthropics/skills/tree/main/skills/frontend-design | ☐ 제출 전(NOTICE · 바꾼 점 적기) |
| f42gh/anti-ai-slop-design (생각만 옮김) | 소스에 포함되지 않음 — 안티패턴 목록을 장표용으로 다시 씀(`slides.py`) | MIT (Copyright (c) 2026 f42) | https://github.com/f42gh/anti-ai-slop-design | ☐ 제출 전 |
| zarazhangrui/frontend-slides (생각만 옮김) | 소스에 포함되지 않음 — 「주제 · 분위기로 스타일을 고른다」를 윈도우 기본 글꼴로 다시 짠 결 넷(`slides_style.py`) | MIT (Copyright (c) 2025 Zara Zhang) | https://github.com/zarazhangrui/frontend-slides | ☐ 제출 전 |
| Akxan/ppt-agent-skill 스타일 예시 8장 · 디자인 플레이북 | 동봉 — `src/alture_jarvis/slide_styles/`(원본 그대로, `LICENSE` · `SOURCE.md` 같이 둠). 예전 길(완성 HTML)의 참고 자료 — 2026-10-25 부터 모델에게 보이지 않음 | MIT (Copyright (c) 2025 sunbigfly) | https://github.com/Akxan/ppt-agent-skill | ☑ 폴더 안 LICENSE |
| zarazhangrui/beautiful-html-templates 템플릿 18개 | 동봉 — `src/alture_jarvis/slide_themes/templates/`(HTML · CSS 를 1280×720 · 윈도우 글꼴로 옮김, `LICENSE` · `SOURCE.md` 같이 둠, 만드는 스크립트 `scripts/port_slide_templates.py`). 손 결 다섯(`slide_themes/*.css`)은 그 배치 문법을 보고 새로 씀 | MIT (Copyright (c) 2026 Zara Zhang) | https://github.com/zarazhangrui/beautiful-html-templates (커밋 e5e204f) | ☑ 폴더 안 LICENSE |
| lewislulu/html-ppt-skill (생각만 옮김) | 소스에 포함되지 않음 — 「가까운 틀을 복사해 내용만 바꾼다」 · 이웃한 장 같은 배치 금지(`slides.py` GUIDE) | MIT (Copyright (c) 2026 lewis) | https://github.com/lewislulu/html-ppt-skill (커밋 fd16290) | ☐ 제출 전 |
| andyqiu847-ai/high-quality-slides (생각만 옮김) | 소스에 포함되지 않음 — 제목은 주장문 · 목록을 그림으로 · 마지막 장은 요청 한 줄 · 막대는 값 이름표(`slides.py` GUIDE · 배치 틀) | MIT (Copyright (c) 2026 Andy) | https://github.com/andyqiu847-ai/high-quality-slides (커밋 30a90be) | ☐ 제출 전 |
| Hasasasa/html-to-editable-pptx (생각만 옮김) | 소스에 포함되지 않음 — PPTX 굽기의 줄 간격 고정 점 · 맞춤 방향으로 상자 넓히기 · 글 조각마다 글꼴(`slides.py` build_pptx) | MIT (Copyright (c) 2026 Phil) | https://github.com/Hasasasa/html-to-editable-pptx (커밋 17c1dbb) | ☐ 제출 전 |
| 한글 오픈 글꼴 6종(프리텐다드 · IBM Plex Sans KR · 페이퍼로지 · 고운돋움 · 고운바탕 · SUIT) | 동봉 — `src/alture_jarvis/slide_themes/fonts/`(만든 곳이 배포한 파일 그대로 · 서브셋 없음 · 예약 이름 없는 고운 둘만 woff2 로 꼴 바꿈, 글꼴마다 옆에 `OFL.txt`, 출처 · 바이트 · sha256 은 `fonts.json`). 손 결 다섯의 장 그리기 · PDF · PPTX(쓴 글자만 심음 — OFL FAQ 1.12)에 쓴다 | SIL OFL 1.1 — 예약 이름: Pretendard · Plex · SUIT (페이퍼로지 · 고운 둘은 없음) | github.com/orioncactus/pretendard (v1.3.9) · github.com/IBM/plex (@ibm/plex-sans-kr 1.1.0) · github.com/Freesentation/paperlogy (freesentation.blog/paperlogyfont) · github.com/google/fonts ofl/gowundodum · gowunbatang · github.com/sun-typeface/SUIT (v2.0.5) | ☑ 글꼴 옆 OFL.txt |
| Tauri / WebView2 런타임 | exe 에 링크 / OS 구성요소 | Apache-2.0 또는 MIT / Microsoft | https://tauri.app | ☐ 제출 전 |

스토어 설명 첫머리 공개 문구(정책 10.2.4) 초안: 「이 앱은 로컬 AI 엔진 Ollama 를 사용합니다. 없으면 첫 실행에서 설치할 수 있습니다.」
