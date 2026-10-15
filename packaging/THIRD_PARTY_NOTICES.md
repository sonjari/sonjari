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
| Tauri / WebView2 런타임 | exe 에 링크 / OS 구성요소 | Apache-2.0 또는 MIT / Microsoft | https://tauri.app | ☐ 제출 전 |

스토어 설명 첫머리 공개 문구(정책 10.2.4) 초안: 「이 앱은 로컬 AI 엔진 Ollama 를 사용합니다. 없으면 첫 실행에서 설치할 수 있습니다.」
