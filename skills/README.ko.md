# 스킬 — 밖에서 가져온 지식

`recipes/` 가 **사이트를 다루는 절차**(실행 가능한 단계)라면, 여기는 **일을 다루는 지식**
(산문)이다. 둘은 같은 규율을 따른다 — 출처를 적고, 등급을 매기고, 확정 전에는 안 쓴다.

## 쓰이고 있다 (2026-08-29 최신화)

이 문단은 예전에 "로더가 없다"고 적혀 있었다. 지금은 `skills.py` 가 로더이고,
두 갈래로 모델에 닿는다:

1. **`skill_list` · `skill_read` 도구** — 모델이 스스로 훑고 읽는다.
   2026-08-29 에 이 둘을 **코드 프로필에도** 넣었다. 그전에는 코워크만 부를 수
   있었고 코드 모드는 못 불렀다 — 같은 저장소에서 한쪽 문만 잠겨 있었다.
2. **`SKILL_TRIGGERS_KO` 결정론 주입**(`runtime._skill_instruction`) — 한국어
   낱말이 걸리면 프롬프트에 스킬 노트를 붙인다. 새로 받은 영어 스킬에는 아직
   트리거가 없다. 즉 지금은 1번으로만 닿는다.

## 출처와 라이선스 (2026-08-21 수확)

| 폴더 | 출처 | 라이선스 | 수 |
|---|---|---|---|
| `vendor/marketing/` | [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) | MIT | 28 |
| `vendor/thinking/` | [tjboudreaux/cc-thinking-skills](https://github.com/tjboudreaux/cc-thinking-skills) | MIT | 28 |
| `vendor/writing/` | [blader/humanizer](https://github.com/blader/humanizer) | MIT | 1 |
| `vendor/anthropic/` | [anthropics/skills](https://github.com/anthropics/skills) | Apache 2.0 | 4 |
| `vendor/engineering/` | [obra/superpowers](https://github.com/obra/superpowers) | MIT | 14 |
| `vendor/devstack/` | [Mindrally/skills](https://github.com/Mindrally/skills) | Apache 2.0 | 12 |

각 폴더의 `LICENSE` / `LICENSE.txt` 를 **지우지 말 것.** MIT·Apache 2.0 둘 다
저작권 고지 보존이 조건이다.

## ★ 가져오지 않은 것과 그 이유

- **`docx` · `pdf` · `pptx` · `xlsx` (Anthropic)** — Apache 2.0 이 **아니다.**
  라이선스에 "Services 밖으로 추출하거나 복사본을 보관하지 말 것", "파생물 금지",
  "제3자에게 배포 금지"가 명문화돼 있다. 비상업 이용이어도 해당된다. **넣지 말 것.**
- **`realkimbarrett/advertising-skills`** (광고 12종, 품질은 좋음) — 라이선스 파일이
  없다. 기본값은 전부 저작권 보유이므로 허가 없이 못 쓴다. 쓰려면 저자에게 문의.
- **ComposioHQ/awesome-claude-skills** 832종 — 라이선스 없음 + 내용이 API 커넥터
  래퍼라 손자리엔 무의미(손자리는 자기 도구가 있다).
- **스크립트 실행을 요구하는 스킬** — 손자리 `shell_probe` 는 인터프리터를 영원히
  안 받는다(`test_no_interpreter_is_ever_allowed`). C단계 격리 상자가 열리기 전엔 못 돈다.

## ★ 스킬은 신뢰된 지시가 아니다

스킬 본문은 **밖에서 온 텍스트**이고, 그것이 모델에게는 지시로 보인다. 즉 주입 벡터다.
손자리는 브라우저 쓰기·구글·승인 게이트를 쥐고 있으므로 이 구분이 중요하다.

수확 시점 스캔 결과 — 원격 실행·자격증명 유출·지시 무력화 문구는 **없었다.** 다만 하나:

```
vendor/marketing/competitor-profiling/SKILL.md:24
  "If the user provides URLs and context is available, proceed without asking."
```

승인 게이트와 상충한다. **스킬 본문이 등급을 낮추지 못한다**는 것을 로더가 강제해야 한다.

## 실측 예산 (2026-08-21)

```
수확 전체 124종   본문 합계 ~385,000 토큰   ← 131K 창에 절대 안 들어간다
큐레이션 61종     description 합계 ~7,900 토큰 = 창의 6.0%
```

**본문을 다 올리는 설계는 불가능하다.** description 만으로도 6% 를 먹으므로,
상시 주입이 아니라 **코드가 골라 3~5개만** 넣는 두 단계여야 한다.


## 2026-08-29 수확 — 코딩

**왜 이 둘인가.** 저장소 실측(색인 2,416 파일)이 Python 66.1% · TypeScript 12.3% ·
PowerShell 7.0% 이고, C 는 3 개뿐이다. 그래서 **임베디드는 안 받았다** — 죽은 무게이고
검색만 오염시킨다.

### `vendor/engineering/` — obra/superpowers (MIT, 14 종)

라이선스 원문 확인: `Copyright (c) 2025 Jesse Vincent`.

언어 스킬보다 이쪽을 먼저 받은 이유가 있다. 같은 날 SWE 벤치에서 실패한 판의 모양이
**32 걸음 · 편집 5 회 · 검증 0 회** 였다. Qwen 이 못 한 것은 파이썬 문법이 아니라
*고치고 나서 확인하기* 였다. `verification-before-completion` 은 그 자리를 정확히 친다 —
"NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE".

### `vendor/devstack/` — Mindrally/skills (Apache 2.0, 12 종)

240 종 중 **우리 스택과 겹치는 것만** 골랐다. Django·Flask·Next.js·GraphQL·Prisma·
Drizzle·TypeORM 등 안 쓰는 스택은 검색 오염이라 뺐다.

**⚠ 품질이 고르지 않다.** Cursor 규칙을 옮긴 것이라 짧은 것들(46~65 줄)은 일반적인
문체 지침에 가깝고, **이 저장소의 관례와 부딪히는 문장도 있다.** 실제 예:
`fastapi-python` 이 "Favor functional, declarative programming over class-based
approaches" 라고 하는데 우리 코드는 `JarvisRuntime`·`BrowserAgent`·`LocalComputerTools`
처럼 클래스 중심이다. 같은 파일에 "Omit curly braces for single-line conditionals"
라는 **파이썬에 존재하지도 않는 규칙**도 있다(변환이 거칠다는 신호).

긴 것들(`ci-cd-best-practices` 515 줄, `git-workflow` 176, `performance-optimization` 134,
`playwright` 104, `security-best-practices` 104, `logging-best-practices` 101)은
의견이 아니라 참고 지식에 가까워 값어치가 있다.

**빼는 것을 검토할 후보**: `python`(62) · `fastapi-python`(61) · `python-testing`(60) ·
`typescript`(65) · `react`(46) · `testing`(48). 우리 관례는 이미 `CLAUDE.md` 와 코드
주석에 훨씬 촘촘히 적혀 있어서, 얇은 일반론이 그걸 흔들 수 있다.
