# 클로드 코드 · 코덱스 · 커서에서 손자리 쓰기 (MCP)

[English](mcp.md) · **한국어**

손자리는 내 PC 에서 로컬 모델로 돕니다. 다른 AI(클로드 코드 · 클로드 데스크톱 · 코덱스 · 커서)가 [MCP](https://modelcontextprotocol.io)
로 손자리에게 일을 통째로 맡길 수 있습니다 — 「웹에서 찾아서 엑셀로」, 「내 저장소의 이 시험 고쳐 줘」. 손자리는 페이지와 파일을
**이 PC 에서** 읽으므로 그 본문은 맡긴 AI 의 대화 창에 들어가지 않습니다. 맡긴 AI 는 답 · 만든 파일 · 읽은 출처 · 확인 못 한 것을
돌려받습니다.

- [연결하기](#연결하기)
- [도구](#도구)
- [돌아오는 것](#돌아오는-것)
- [상태 흐름](#상태-흐름)
- [쓰는 예](#쓰는-예)
- [한계와 안전](#한계와-안전)
- [안 될 때](#안-될-때)

---

## 연결하기

### 쉬운 길 — 「연결」 단추

손자리 → **설정 › 연결** → 쓰는 앱 옆의 **연결**을 누릅니다. 손자리가 원래 설정 파일을 먼저 백업하고 `sonjari` 라는 항목 하나를 더합니다.

| 앱 | 항목이 들어가는 곳 | 방법 |
|---|---|---|
| 클로드 코드 | 사용자 범위(`claude mcp add-json … --scope user`) | `claude` 명령으로 — `.claude.json` 을 손으로 고치지 않음 |
| 클로드 데스크톱 | `%APPDATA%\Claude\claude_desktop_config.json` 의 `mcpServers`(스토어판 클로드는 패키지 폴더의 같은 파일도) | 파일 수정 · 원본 백업 |
| 커서 | `~/.cursor/mcp.json` 의 `mcpServers` | 파일 수정 · 원본 백업 |
| 코덱스 | `codex mcp add` 가 있으면 그것, 없으면 `~/.codex/config.toml` 의 `[mcp_servers.sonjari]` | 명령 또는 파일 수정 |

연결한 뒤 그 앱을 다시 켭니다(클로드 데스크톱은 완전히 꺼야 합니다 — 손자리가 꺼질 때까지 기다려 줍니다).

연결하면 맡긴 AI 가 읽을 짧은 사용법도 같이 깔립니다.

| 앱 | 사용법 파일 | 가리키는 줄을 더하는 곳 |
|---|---|---|
| 클로드 코드 | `~/.claude/skills/sonjari-guide/SKILL.md` | `~/.claude/CLAUDE.md` |
| 코덱스 | `~/.codex/sonjari-guide.md` | `~/.codex/AGENTS.md` |
| 커서 | — (사용자 규칙이 앱 안에 있어 붙여 넣을 글을 보여 줌) | — |
| 클로드 데스크톱 | — (앱이 스킬을 넣을 수 없음) — 대신 `sonjari_guide` 도구를 한 번 부름 | — |

### 손으로

항목에는 비밀이 없습니다. 스토어판이면 이런 모양입니다(「연결」을 누르면 손자리가 실제 경로를 채워 줍니다 — 되도록 거기서 복사하세요).

```json
{
  "mcpServers": {
    "sonjari": {
      "command": "%LOCALAPPDATA%\\Microsoft\\WindowsApps\\sonjari-mcp.exe",
      "args": ["-m", "alture_jarvis.mcp_server"],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "JARVIS_BASE_URL": "http://127.0.0.1:8091",
        "JARVIS_TOKEN_FILE": "<손자리 control.token 파일 경로>",
        "JARVIS_MCP_MAX_RISK": "L1"
      }
    }
  }
}
```

소스로 빌드했으면 `command` 는 `.venv\Scripts\python.exe` 이고, `env` 에 `src` 를 가리키는 `PYTHONPATH` 가 더 있습니다.

코덱스(`~/.codex/config.toml`):

```toml
[mcp_servers.sonjari]
command = "<같은 명령>"
args = ["-m", "alture_jarvis.mcp_server"]
env = { PYTHONIOENCODING = "utf-8", JARVIS_BASE_URL = "http://127.0.0.1:8091", JARVIS_TOKEN_FILE = "<경로>", JARVIS_MCP_MAX_RISK = "L1" }
```

| 변수 | 뜻 |
|---|---|
| `JARVIS_BASE_URL` | 손자리 로컬 백엔드. `127.0.0.1` 만 — 네트워크에 열려 있지 않음 |
| `JARVIS_TOKEN_FILE` | 로컬 토큰이 든 파일. 토큰 자체는 설정에 적지 않음 |
| `JARVIS_MCP_MAX_RISK` | 내보내는 가장 높은 위험 단계. 기본 `L1` 은 되돌릴 수 없는 동작을 아예 안 내보냄 |
| `JARVIS_MCP_INCLUDE` / `JARVIS_MCP_EXCLUDE` | 쉼표로 이은 도구 이름 — 억지로 넣기 / 빼기(넣기가 이김) |
| `JARVIS_MCP_EXCLUDE_PREFIXES` | 기본으로 숨기는 이름 머리: `camera_`, `ui_` |

---

## 도구

늘 있는 도구는 셋입니다. 분야 팩을 켜면 그 팩의 도구가 더해집니다(예: 게임 팩의 `unity_*`).

### `sonjari_task` — 일 하나를 통째로 맡기기

`job_id` 를 바로 돌려줍니다. **무엇을 · 어디서 · 어떤 파일로** 받을지를 한 문장에 담으세요. 낮은 단위 브라우저 도구를 여러 번
부르는 것보다 이 도구 한 번이 빠르고 쌉니다.

| 칸 | 종류 | 필수 | 하는 일 |
|---|---|---|---|
| `task` | 글 | 예 | 과제 한 문장 · 사용자가 쓰는 언어로(최대 4,000자) |
| `needs` | 글 목록 | 아니오 | 꼭 돌려받아야 할 항목 이름 12개까지. 예: `["상품 이름", "가격", "주소"]`. 결과에 항목마다 채웠는지(`met: true / false / null`)가 옴. 전화번호 · 메일 주소는 여기 밝혔을 때만 나가고, 주민번호 · 카드 번호 · 비밀 키는 늘 가림 |
| `repo` | 글 | 아니오 | **코드 일:** 이 PC 의 git 저장소(또는 그 안의 폴더) 절대 경로. 손자리가 **따로 꺼낸 새 가지**에서만 고치고 내 폴더는 건드리지 않음. 커밋 안 한 변경(추적 중인 파일)은 같이 가져감 |
| `check` | 글 | 아니오 | `repo` 와 같이: 「끝났나」를 가르는 명령 한 줄(그 폴더에서 실행 · 종료 코드 0 이면 통과). 예: `python -m pytest -q tests/test_x.py`. 통과할 때까지 고치거나, 못 하면 못 했다고 돌려줌 |
| `skill` | 글 | 아니오 | 쓸 스킬 이름. 모르면 비워 둠 |

저장 폴더는 적지 않는 것이 기본입니다 — 결과는 `문서\Sonjari` 에 저장되고 경로가 `files` 로 옵니다. 다른 폴더를 적으면 손자리 창에서
사람이 승인해야 하고, 승인할 때까지 일이 기다립니다.

### `sonjari_task_status` — 진행과 결과

| 칸 | 종류 | 필수 | 하는 일 |
|---|---|---|---|
| `job_id` | 글 | 예 | `sonjari_task` 가 준 번호 |
| `wait_sec` | 정수 | 아니오 | 답하기 전에 최대 이만큼 기다림. 기본값이자 상한: 클로드 코드 240초, 다른 앱 50초. 비워 두세요 — 물을 때마다 맡긴 AI 가 대화 전체를 다시 읽습니다 |

### `sonjari_guide` — 첫 일 전에 한 번 읽기

「연결」이 스킬로 까는 것과 같은 사용법(과제를 적는 법 · 결과를 전하는 법 · 막혔을 때 할 일)을 돌려줍니다. 읽기만 합니다.

---

## 돌아오는 것

일이 끝났을 때 `sonjari_task_status` 의 칸:

| 칸 | 무엇 |
|---|---|
| `status` | [상태 흐름](#상태-흐름) 참고 |
| `answer` | 손자리의 답 |
| `files` | 만든 파일의 경로 |
| `sources` | 실제로 읽은 주소 · 파일 |
| `unsupported_numbers` | 답이나 파일에 있는데 **어떤 도구도 준 적 없는 숫자** — 사실로 전하지 말 것 |
| `needs` | 밝힌 항목마다 `met` = `true`(값이 있음) · `false`(자리가 비어 있음) · `null`(자리를 못 찾음 — 답을 직접 볼 것) |
| `completion_state` | `complete` 또는 `partial` |
| `review_notes` | 답을 전하기 전에 읽을 짧은 메모 |
| `resume` | 덜 끝났을 때: `evidence`(이미 읽음 — 다시 열지 말 것) · `next`(남은 것) |
| `branch` | 코드 일: `name` · `changed` · `changed_count` · `stat` · `check`(통과 여부) · `wording_only`(설명 글 · 주석만 바뀐 파일) · `take_home`(`review` / `take` / `discard` 명령) |
| `cost` | 걸린 초 · 이 PC 에서 읽은 페이지 수 · `host_context_kept_out.tokens_at_least` — **하한**이고 `basis` 가 같이 옴 |
| `receipt` | 사용자에게 보여 줄 한 줄 |

도는 동안에는 `progress.doing`(지금 하는 일) · `progress.requested`(시킨 것 n/m) · `steps`, 줄 서 있을 때는 `jobs_ahead` 가 옵니다.
손자리는 한 번에 한 일만 합니다.

---

## 상태 흐름

| `status` | 뜻 | 맡긴 AI 가 할 일 |
|---|---|---|
| `queued` | 다른 일 뒤에 줄 서 있음 | 다시 묻기 |
| `running` | 일하는 중 | `progress.doing` 을 한 줄로 전하고 다시 묻기 |
| `needs_approval` | 되돌릴 수 없는 걸음이나 질문이 손자리 창에서 사람을 기다림 | 손자리 창을 봐 달라고 사용자에게 알리기. 대신 답하지 않기 |
| `needs_decision` | 같은 자리에서 막힘, 또는 로그인 · 보안 문자 · 결제 화면 | `message` 를 그대로 전하기. 로그인 · 보안 문자는 사람이 끝내면 손자리가 알아서 이어 감 — 계속 묻기 |
| `done` | 끝남 | `answer` · `files` · `sources` 전하기 |
| `needs_review` | 끝났지만 도구가 준 적 없는 숫자가 답에 있음 | 확인이 필요하다고 말하기 |
| `failed` / `cancelled` | 멈춤 | 그래도 `files` · `sources` · `resume` 은 쓰기 — 멈추기 전까지 한 일 |

---

## 쓰는 예

**조사해서 파일로**

```text
sonjari_task(task="사람인에서 서울 마케팅 공고 3개 찾아서 회사 · 마감일 · 링크를 엑셀로 정리해줘",
             needs=["회사", "마감일", "링크"])
sonjari_task_status(job_id=...)   # wait_sec 은 비워 두기
```

**명령으로 확인하는 좁은 코드 일**

```text
sonjari_task(task="시험은 고치지 말고 test_parse_dates 가 통과하게 해줘",
             repo="C:/work/myapp",
             check="python -m pytest -q tests/test_dates.py")
```

끝나면 보고 나서 가져갑니다.

```powershell
git -C C:/work/myapp diff <base>..sonjari/task-<n>            # branch.take_home.review
git -C C:/work/myapp cherry-pick -n <base>..sonjari/task-<n>  # branch.take_home.take
```

손자리에게는 확인 명령이 분명한 좁은 일(파일 한두 개)을 맡기세요. 큰 설계 · 처음 보는 API 는 맡긴 AI 가 짜서 손자리에게 적용 ·
시험만 시키는 편이 낫습니다.

---

## 한계와 안전

- 손자리는 `127.0.0.1` 에서만 듣습니다. MCP 항목에는 토큰이 아니라 토큰 **파일 경로**가 들어갑니다.
- 되돌릴 수 없는 동작(메일 보내기 · 게시 · 결제 · 삭제)은 기본 `L1` 에서 **내보내지 않습니다.** 사람이 손자리 창에서 합니다.
- 로그인 · 보안 문자 · 결제 화면은 사람에게 넘깁니다. 손자리는 보안 문자를 풀지 않습니다.
- 코드 일은 내 작업 폴더를 바꾸지 않습니다 — 보고 가져가거나 버릴 수 있는 따로 된 가지만.
- 로컬 모델은 클라우드 모델보다 느립니다. 손자리가 아껴 주는 것은 맡긴 AI 의 대화 창과 사용 한도이지, 더 빠르다고 약속하지 않습니다.
- 무엇이 밖으로 나가는지는 [내 PC 밖으로 나가는 것](privacy.ko.md)에 그림으로 있습니다.

---

## 안 될 때

| 증상 | 볼 것 |
|---|---|
| 앱 목록에 `sonjari` 가 없음 | 연결한 뒤 그 앱을 다시 켰는지. 클로드 데스크톱은 완전히 끈 뒤 |
| 도구는 보이는데 부르면 연결 오류 | 손자리가 꺼져 있음 — 손자리를 켜기(백엔드가 같이 켜짐) |
| 부를 때마다 `queued` 에서 기다림 | 다른 일이 도는 중 — 손자리는 한 번에 하나 |
| `needs_approval` 에서 계속 기다림 | 누군가 손자리 창의 카드에 답해야 함 |
| 코드 일이 거절됨 | `repo` 가 이 PC 의 git 저장소이고, 손자리가 쓸 수 있게 허락한 폴더 안인지 |
