/**
 * 리허설 장면 `?fixture=claude-hands` — **Claude Agent 가 손자리에게 맡기는 흐름** (2026-10-26 · 개발 빌드 전용 · 데이터는 지어낸 것).
 *
 * 진짜 클로드를 부르지 않는다(개발 PC 의 구독 한도가 닳고 · 시험용 API 키가 없다). 대신:
 * - 클로드 쪽: Rust `claude_agent.rs` 가 보내는 사건(`AgentStreamEvent`)을 **손으로 만든 시간표**로 흘린다.
 *   같은 흐름의 원본 stream-json 표본은 `src-tauri/src/testdata/claude_agent_stream.jsonl` 이고 Rust 시험이 그것을 센다.
 * - 손자리 쪽: 맡긴 판(origin=mcp)이 서버 웹소켓으로 보내는 사건과 서버 걸음 기록을 흉내 낸다.
 *
 * `?claudeKey=none` 을 붙이면 키가 없는 상태(메뉴 안 「키 넣기」 줄)를 본다. `?claudeSpeed=0.25` 는 네 배 느리게(연출을 다듬을 때),
 * `?claudeStopAt=6000` 은 그 순간(배속 1 기준 밀리초)에서 멈춘다 — 중간 장면을 사진으로 남길 때.
 */
import type {
  AgentChatResult, AgentStreamEvent, ClaudeAgentStatus, JarvisEvent, JobOutput,
} from "../types";
import type { Observation, StepRow } from "../workspace/observation";
import { setBrain } from "../claudeAgent/brain";
import { ClaudeLane, type AgentRunRequest, type ClaudeRunner, type LocalSource } from "../claudeAgent/lane";

export const CLAUDE_HANDS_SESSION = "claude-room";
export const CLAUDE_HANDS_LOCAL_JOB = "fx-local-1";
export const CLAUDE_HANDS_PROMPT = "국내 AI 에이전트 소식 5개 찾아서 장표 6장으로 만들어 줘";

type Beat =
  | { at: number; claude: Partial<AgentStreamEvent> & { kind: AgentStreamEvent["kind"] } }
  | { at: number; local: JarvisEvent; row?: Observation };

const PAGES = [
  ["https://news.example.kr/ai-agent", "AI 에이전트 소식 — 검색 결과"],
  ["https://news.example.kr/1", "국내 스타트업, PC 에이전트 베타 공개"],
  ["https://news.example.kr/2", "대기업 그룹, 사내 문서 에이전트 4분기 시범 도입"],
  ["https://news.example.kr/3", "한글 문서 다루는 AI, 공공기관 실증 시작"],
  ["https://news.example.kr/4", "「로컬 모델로 개인정보 지킨다」 소비자 앱 잇따라"],
  ["https://news.example.kr/5", "에이전트 오작동 사례 모음 — 검사 장치가 관건"],
] as const;

function pageRow(step: number, url: string, title: string, at: number): Observation {
  return {
    job_id: CLAUDE_HANDS_LOCAL_JOB, step, tool: step === 1 ? "browser_search" : "browser_read_page", ok: true, status: "completed",
    error: "", kind: "page", title, at, took_ms: 640, truncated: false, arguments: { url },
    payload: { url, title, text: `${title}\n\n(리허설용 지어낸 본문입니다.)` }, truncation: {},
  };
}

/** 시간표(배속 1 기준 밀리초). 클로드 걸음 3 · 손자리 걸음 7 — 클로드가 결과를 기다리는 사이 손자리 걸음이 끼어든다. */
export function claudeHandsBeats(start = Date.now() / 1000): Beat[] {
  const at = (ms: number) => start + ms / 1000;
  const progress = (step: number, tool: string, message: string): JarvisEvent => ({
    event: "agent_progress",
    payload: { job_id: CLAUDE_HANDS_LOCAL_JOB, step, phase: "research", tool, message, status: "completed" },
  });
  const beats: Beat[] = [
    { at: 200, claude: { kind: "thinking", delta: "사용자는 소식 다섯 개와 장표를 원한다. 페이지를 많이 읽는 일이라 손자리에게 맡긴다." } },
    { at: 500, claude: { kind: "text", delta: "소식 찾기와 장표 굽기는 손자리에게 맡기겠습니다. 페이지를 많이 읽는 일이라 이 PC에서 하는 게 빠르고 돈이 안 듭니다." } },
    { at: 900, claude: { kind: "tool", step: 1, tool: "mcp__sonjari__sonjari_guide", tool_use_id: "toolu_01", evidence: {} } },
    { at: 1300, claude: { kind: "tool_done", step: 1, tool: "mcp__sonjari__sonjari_guide", tool_use_id: "toolu_01", ok: true, message: "손자리 사용법: 과제 하나를 통째로 맡기세요." } },
    { at: 1700, claude: { kind: "tool", step: 2, tool: "mcp__sonjari__sonjari_task", tool_use_id: "toolu_02",
      evidence: { task: "국내 AI 에이전트 소식 5개 읽기 → 장표 6장", needs: ["제목", "출처"] } } },
    { at: 2300, claude: { kind: "tool_done", step: 2, tool: "mcp__sonjari__sonjari_task", tool_use_id: "toolu_02", ok: true,
      message: `{"job_id": "${CLAUDE_HANDS_LOCAL_JOB}", "status": "queued"}` } },
    { at: 2350, claude: { kind: "delegated", step: 2, tool: "mcp__sonjari__sonjari_task", tool_use_id: "toolu_02", local_job_id: CLAUDE_HANDS_LOCAL_JOB } },
    { at: 2600, claude: { kind: "tool", step: 3, tool: "mcp__sonjari__sonjari_task_status", tool_use_id: "toolu_03",
      evidence: { job_id: CLAUDE_HANDS_LOCAL_JOB, wait_sec: 240 } } },
    { at: 2900, local: { event: "agent_plan", payload: { job_id: CLAUDE_HANDS_LOCAL_JOB, items: [
      { kind: "need", label: "소식 5개 직접 읽기", met: false, saw: "0개 읽음" },
      { kind: "need", label: "장표 6장 굽기", met: false, saw: "아직" },
    ] } } },
  ];
  PAGES.forEach(([url, title], index) => {
    const ms = 3300 + index * 700;
    beats.push({ at: ms, local: progress(index + 1, index ? "browser_read_page" : "browser_search", index ? `「${title}」 본문을 읽는 중` : "소식을 찾는 중"),
      row: pageRow(index + 1, url, title, at(ms)) });
  });
  beats.push(
    { at: 7600, local: { event: "agent_plan", payload: { job_id: CLAUDE_HANDS_LOCAL_JOB, items: [
      { kind: "need", label: "소식 5개 직접 읽기", met: true, saw: "5개 읽음" },
      { kind: "need", label: "장표 6장 굽기", met: false, saw: "굽는 중" },
    ] } } },
    { at: 8100, local: { event: "agent_progress", payload: { job_id: CLAUDE_HANDS_LOCAL_JOB, step: 7, phase: "research", tool: "local_make_slide",
      message: "장표 6장을 굽는 중", status: "completed" } },
      row: {
        job_id: CLAUDE_HANDS_LOCAL_JOB, step: 7, tool: "local_make_slide", ok: true, status: "completed", error: "", kind: "artifact",
        title: "agent_news.pptx", at: at(8100), took_ms: 1800, truncated: false, arguments: { path: "Documents/Sonjari/agent_news.pptx" },
        payload: { text: "장표 6장: 표지 · 소식 1~4 · 정리(출처 5곳)" }, truncation: {},
      } },
    { at: 8700, local: { event: "agent_plan", payload: { job_id: CLAUDE_HANDS_LOCAL_JOB, items: [
      { kind: "need", label: "소식 5개 직접 읽기", met: true, saw: "5개 읽음" },
      { kind: "need", label: "장표 6장 굽기", met: true, saw: "6장" },
    ] } } },
    { at: 9000, local: { event: "job_completed", payload: { job_id: CLAUDE_HANDS_LOCAL_JOB, session_id: "mcp-fixture" } } },
    { at: 9300, claude: { kind: "tool_done", step: 3, tool: "mcp__sonjari__sonjari_task_status", tool_use_id: "toolu_03", ok: true,
      message: '{"job_id": "fx-local-1", "status": "done", "steps": 7}' } },
    { at: 9350, claude: { kind: "delegation_status", step: 3, tool: "mcp__sonjari__sonjari_task_status", tool_use_id: "toolu_03", local_job_id: CLAUDE_HANDS_LOCAL_JOB,
      summary: { status: "done", steps: 7, files: 1, sources: 5, unsupported_numbers: 0, needs_total: 2, needs_met: 2 } } },
    { at: 9800, claude: { kind: "thinking", delta: "검사에 걸린 것이 없다. 2번 기사의 「4분기」는 기사 날짜가 9월이라 확정 일정이 아니라고 덧붙인다." } },
  );
  return beats as Beat[];
}

/**
 * 코드 모드 장면(`&claudeScene=code`) — 대표 PC 10-26 13:52 · 13:59 판(클로드 코드 기록 `cc8852ce…` · `31deb38a…`)의 걸음 모양 그대로.
 * 명령 걸음의 본문은 Rust `command_payload` 가 만드는 꼴(`$ 명령` + 출력)이다. 생각 글은 `--thinking-display summarized` 로 오는 모양.
 */
const CODE_FILE = "D:\\bench_tmp\\claude_code_test\\price.py";
const PYTEST = "python -m pytest -q test_price.py";
const PASSED = "..                                                                       [100%]\n2 passed in 0.01s";
export const CLAUDE_CODE_ANSWER = "`price.py`의 버그 두 개를 고쳤고, `test_price.py` 시험 2개가 모두 통과합니다(pytest로 직접 돌려 확인).\n\n"
  + "- **개수 누락:** `price.py:6`에서 합계를 낼 때 개수를 곱하지 않았습니다. `price * qty`로 고쳤습니다.\n"
  + "- **기준 금액 경계:** `price.py:7`의 `>`를 `>=`로 바꿨습니다.";

function codeBeats(): Beat[] {
  const edit = { file_path: CODE_FILE, old_string: "    subtotal = sum(price for _name, price, _qty in items)\n    if subtotal > free_over:", new_string: "    subtotal = sum(price * qty for _name, price, qty in items)\n    if subtotal >= free_over:" };
  return [
    { at: 200, claude: { kind: "thinking", delta: "The test expects quantity to be multiplied and the free-shipping threshold to be inclusive." } },
    { at: 500, claude: { kind: "text", delta: "먼저 두 파일을 찾아서 읽겠습니다." } },
    { at: 700, claude: { kind: "tool", step: 1, tool: "Glob", tool_use_id: "toolu_g1", evidence: { pattern: "**/*price*.py" } } },
    { at: 900, claude: { kind: "tool_done", step: 1, tool: "Glob", tool_use_id: "toolu_g1", ok: true, message: "test_price.py\nprice.py", evidence: { text: "test_price.py\nprice.py" } } },
    { at: 1100, claude: { kind: "tool", step: 2, tool: "Read", tool_use_id: "toolu_r1", evidence: { file_path: CODE_FILE } } },
    { at: 1300, claude: { kind: "tool_done", step: 2, tool: "Read", tool_use_id: "toolu_r1", ok: true, evidence: { text: '1\t"""장바구니 합계 계산."""\n2\t\n3\t\n4\tdef total(items, shipping=3000, free_over=50000):\n5\t    """items: [(이름, 값, 개수)]"""\n6\t    subtotal = sum(price for _name, price, _qty in items)\n7\t    if subtotal > free_over:\n8\t        return subtotal\n9\t    return subtotal + shipping' } } },
    { at: 1600, claude: { kind: "thinking", delta: " Fix both lines in price.py, then run pytest to prove it." } },
    { at: 1900, claude: { kind: "tool", step: 3, tool: "Edit", tool_use_id: "toolu_e1", evidence: edit } },
    { at: 2200, claude: { kind: "tool_done", step: 3, tool: "Edit", tool_use_id: "toolu_e1", ok: true,
      evidence: { path: CODE_FILE, text: "The file has been updated successfully.", edit_preview: { start_line: 6, removed: edit.old_string.split("\n"), added: edit.new_string.split("\n"), truncated: false, added_count: 2 } } } },
    { at: 2500, claude: { kind: "tool", step: 4, tool: "Bash", tool_use_id: "toolu_b1", evidence: { command: `${PYTEST} 2>&1 | tail -15`, description: "price 시험 실행" } } },
    { at: 2700, claude: { kind: "tool_done", step: 4, tool: "Bash", tool_use_id: "toolu_b1", ok: false,
      message: "This Bash command contains multiple operations. The following part requires approval: python -m pytest -q test_price.py 2>&1",
      evidence: { command: `${PYTEST} 2>&1 | tail -15`, language: "bash", text: `$ ${PYTEST} 2>&1 | tail -15\nThis Bash command contains multiple operations. The following part requires approval: python -m pytest -q test_price.py 2>&1` } } },
    { at: 3000, claude: { kind: "tool", step: 5, tool: "Bash", tool_use_id: "toolu_b2", evidence: { command: PYTEST, description: "price 시험 실행" } } },
    { at: 4200, claude: { kind: "tool_done", step: 5, tool: "Bash", tool_use_id: "toolu_b2", ok: true, message: PASSED,
      evidence: { command: PYTEST, language: "bash", text: `$ ${PYTEST}\n${PASSED}`, output_lines: 2, clipped: false } } },
  ] as Beat[];
}

export const CLAUDE_HANDS_ANSWER ="**장표 6장을 만들었습니다.** 손자리가 소식 5곳을 직접 읽고 장표를 구웠고, 검사에서 걸린 것은 없었습니다. "
  + "2번 장의 「4분기 시범 도입」은 기사 날짜가 9월이라 확정 일정은 아닙니다.";

const FINISH_MS = 10_600;

class FixtureLocal implements LocalSource {
  rows: Observation[] = [];
  async listSteps(jobId: string): Promise<{ items: StepRow[] }> {
    if (jobId !== CLAUDE_HANDS_LOCAL_JOB) return { items: [] };
    return { items: this.rows.map(({ job_id: _j, arguments: _a, payload: _p, truncation: _t, ...row }) => row) };
  }
  async getStep(jobId: string, step: number) {
    return structuredClone(this.rows.find((row) => row.job_id === jobId && row.step === step) ?? null);
  }
  async listOutputs(jobId: string): Promise<{ items: JobOutput[] }> {
    if (jobId !== CLAUDE_HANDS_LOCAL_JOB || !this.rows.some((row) => row.step === 7)) return { items: [] };
    return { items: [{ step: 7, tool: "local_make_slide", name: "agent_news.pptx", path: "Documents/Sonjari/agent_news.pptx", bytes: 184_320, kind: "file", exists: true, viewable: true }] };
  }
  async cancelJob() {
    return { ok: true };
  }
}

/** 리허설 갈래 — `deliver` 는 원래 클라이언트의 사건이 흐르는 길(화면 + 갈래의 observe). */
export function createFixtureLane(name: string, emit: (event: JarvisEvent) => void): ClaudeLane | null {
  if (name !== "claude-hands") return null;
  const params = new URLSearchParams(window.location.search);
  const local = new FixtureLocal();
  let keyed = params.get("claudeKey") !== "none";
  const speed = Math.min(4, Math.max(0.1, Number(params.get("claudeSpeed") ?? 1) || 1));
  const stopAt = Number(params.get("claudeStopAt") ?? 0) || Infinity;
  const codeScene = params.get("claudeScene") === "code";
  const timers: number[] = [];
  let lane: ClaudeLane | null = null;
  const deliver = (event: JarvisEvent) => {
    emit(event);
    lane?.observe(event);
  };
  const runner: ClaudeRunner = {
    async status(): Promise<ClaudeAgentStatus> {
      return keyed
        ? { ready: true, claude_found: true, has_key: true, key_state: "ok", message: "API 키가 연결되어 있습니다." }
        : { ready: false, claude_found: true, has_key: false, key_state: "none", message: "API 키를 넣어 주세요." };
    },
    async prepare() { /* 리허설: 쓸 파일이 없다 */ },
    async keyFromClipboard() {
      keyed = true;
      return { ok: true };
    },
    async cancel() {
      for (const timer of timers.splice(0)) window.clearTimeout(timer);
    },
    run(request: AgentRunRequest, onStream: (event: AgentStreamEvent) => void): Promise<AgentChatResult> {
      local.rows = [];
      const base: AgentStreamEvent = {
        job_id: request.job_id, kind: "thinking", delta: "", step: 0, tool: "", tool_use_id: "", message: "", ok: true,
        evidence: {}, local_job_id: "", summary: null,
      };
      if (!codeScene) {
        // 앱 안 Claude 가 맡긴 판은 서버에서 via=app 으로 줄을 선다 — 화면이 그 방을 따로 세우거나 열지 않는지 보는 자리.
        deliver({ event: "job_queued", payload: { job_id: CLAUDE_HANDS_LOCAL_JOB, kind: "chat", origin: "mcp", via: "app", caller: "claude-code",
          session_id: "mcp-fixture", prompt: "바깥 AI 가 맡긴 일 · 국내 AI 에이전트 소식 5개 읽기 → 장표 6장" } });
        deliver({ event: "agent_started", payload: { job_id: CLAUDE_HANDS_LOCAL_JOB, origin: "mcp", session_id: "mcp-fixture" } });
      }
      for (const beat of (codeScene ? codeBeats() : claudeHandsBeats()).filter((row) => row.at <= stopAt)) {
        timers.push(window.setTimeout(() => {
          if ("claude" in beat) onStream({ ...base, ...beat.claude });
          else {
            if (beat.row) local.rows = [...local.rows.filter((row) => row.step !== beat.row!.step), beat.row];
            deliver(beat.local);
          }
        }, beat.at / speed));
      }
      return new Promise((resolve) => {
        if (FINISH_MS > stopAt) return;
        if (codeScene) {
          timers.push(window.setTimeout(() => resolve({
            answer: CLAUDE_CODE_ANSWER, cost_usd: 0.19, duration_ms: 5200, session_id: "31deb38a-0000-4000-8000-000000000001",
            model: request.model, input_tokens: 12, output_tokens: 800, cache_read_tokens: 40_000, cache_creation_tokens: 9_000,
            num_turns: 6, delegations: [], trace: [],
          }), 5200 / speed));
          return;
        }
        timers.push(window.setTimeout(() => resolve({
          answer: CLAUDE_HANDS_ANSWER, cost_usd: 0.0412, duration_ms: FINISH_MS, session_id: "5f0c2a9e-1111-4222-8333-444455556666",
          model: request.model, input_tokens: 6100, output_tokens: 900, cache_read_tokens: 2048, cache_creation_tokens: 512,
          num_turns: 5, delegations: [{ tool_use_id: "toolu_02", local_job_id: CLAUDE_HANDS_LOCAL_JOB }],
          trace: [
            { step: 1, tool: "mcp__sonjari__sonjari_guide", ok: true, status: "completed", error: "", kind: "note", title: "", at: 0, took_ms: 400, truncated: false, arguments: {}, payload: { text: "손자리 사용법: 과제 하나를 통째로 맡기세요." } },
            { step: 2, tool: "mcp__sonjari__sonjari_task", ok: true, status: "completed", error: "", kind: "note", title: "", at: 0, took_ms: 600, truncated: false, arguments: { task: "국내 AI 에이전트 소식 5개 읽기 → 장표 6장" }, payload: { text: `{"job_id": "${CLAUDE_HANDS_LOCAL_JOB}", "status": "queued"}` } },
            { step: 3, tool: "mcp__sonjari__sonjari_task_status", ok: true, status: "completed", error: "", kind: "note", title: "", at: 0, took_ms: 6700, truncated: false, arguments: { job_id: CLAUDE_HANDS_LOCAL_JOB }, payload: { text: '{"status": "done", "steps": 7}' } },
          ],
        }), FINISH_MS / speed));
      });
    },
  };
  lane = new ClaudeLane({ emit, runner, local, lang: () => "ko" });
  // 장면의 대화는 처음부터 Claude Agent · Sonnet 5.5 로 — 모델 칸에서 내 PC 모델로 바꿔 「지금 그대로」도 볼 수 있다.
  setBrain(CLAUDE_HANDS_SESSION, "claude-sonnet-5-5");
  return lane;
}
