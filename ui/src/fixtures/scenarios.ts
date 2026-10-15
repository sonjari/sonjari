/**
 * 화면 리허설용 시나리오.
 *
 * 자비스 화면의 대부분은 백엔드가 살아 있어야만 나타난다 — 승인 카드, 스트리밍,
 * 도구 걸음, 주의 배너, 에러. 그래서 UI 를 고칠 때마다 **눈으로 확인할 방법이 없었다.**
 * 여기 있는 시나리오가 그 상태들을 가짜 백엔드로 재생한다.
 *
 * 정지 화면이 아니라 **시간표**인 것이 핵심이다. 연출(무엇이 언제 어디서 나타나
 * 어디로 들어가는가)은 느리게 돌려 보지 않으면 다듬을 수 없다. FixtureBar 의
 * 0.25배속이 그 용도다.
 *
 * 개발 빌드에서만 로드된다(`fixtures/index.ts` 의 DEV 가드).
 */
import type { Observation } from "../workspace/observation";
import type {
  BrowserStatus, ConversationHistory, ConversationSummary, GoogleStatus, JobOutput,
  JobSummary, PeopleStatus, ScheduleRow, SelfCheckStatus, UndoOffer, UpdateStatus,
} from "../types";

/** 재생 시간표의 한 걸음. `at` 은 재생 시작으로부터의 밀리초다. */
export interface ScriptStep {
  at: number;
  event: string;
  payload?: Record<string, unknown>;
}

export interface Scenario {
  id: string;
  label: string;
  /** 이 시나리오로 무엇을 확인하는지 — FixtureBar 에 그대로 뜬다. */
  hint: string;
  /** 재생 버튼이 작성창에 넣어 보낼 문장. 없으면 보내기 없이 ambient 만 돈다. */
  prompt?: string;
  sessions: ConversationSummary[];
  history: ConversationHistory;
  google?: Partial<GoogleStatus>;
  people?: Partial<PeopleStatus>;
  /** 연결 직후 재생 — 작업 없이도 뜨는 것(승인·주의·계속진행). */
  ambient?: ScriptStep[];
  /** 보내기 이후 재생 — job_id 는 재생기가 채운다. */
  onSend?: ScriptStep[];
  /** 작업이 끝난 뒤 대화에 안착할 답. 없으면 스트리밍한 원문이 그대로 남는다. */
  settledAnswer?: string;
  /** 사이드바 위층에 뜰 일감. 비우면 그 층이 통째로 안 그려진다(빈 상태 확인용). */
  jobs?: JobSummary[];
  /**
   * 걸음이 본 것 (P14). 안 주면 기본 일곱 걸음이 온다(`fixtures/observations.ts`) —
   * 뷰어를 확인하려면 볼 것이 있어야 하고, 시나리오마다 다시 적을 필요는 없다.
   * 빈 배열을 주면 **걸음이 없는 상태**를 본다(눈금자가 통째로 안 그려진다).
   */
  steps?: Observation[];
  /** 예약. 화면에 지금까지 전혀 없던 것이라 리허설 장면이 있어야 눈으로 본다. */
  schedules?: ScheduleRow[];
  /** 브라우저 상태 (R2). 막힌 화면을 눈으로 보려면 이 값이 갈려야 한다. */
  browser?: Partial<BrowserStatus>;
  /** 켤 때 점검 결과 (2026-09-18). 고장 줄은 진짜 PC 가 고장나야만 떠서 눈으로 볼 길이 없었다. */
  selfCheck?: SelfCheckStatus;
  /** 스토어판 업데이트 줄·덮개 (2026-09-18 밤). 없으면 「받을 것 없음」. */
  update?: UpdateStatus;
  /** 에이전트 화면에 그릴 가짜 페이지 제목. 없으면 프레임이 안 온다. */
  browserFrame?: { url: string; title: string };
  /** 그 작업이 만든 파일 (R4). 궤적을 펼쳐야 뜬다. */
  outputs?: JobOutput[];
  /** 되돌릴 수 있는 것 (R4). job_id 는 재생기가 방금 만든 잡으로 갈아 끼운다. */
  undo?: Omit<UndoOffer, "job_id">[];
}

const NOW = Math.floor(Date.now() / 1000);

function summary(id: string, title: string, preview: string, minutesAgo: number, count: number): ConversationSummary {
  return {
    session_id: id,
    title,
    preview,
    message_count: count,
    updated_at: NOW - minutesAgo * 60,
    has_summary: count > 20,
  };
}

let messageId = 1;
function said(session: string, role: "user" | "assistant", content: string, secondsAgo: number, metadata: Record<string, unknown> = {}) {
  return {
    id: messageId++,
    session_id: session,
    role,
    content,
    kind: "chat",
    metadata,
    created_at: NOW - secondsAgo,
  };
}

const SESSIONS: ConversationSummary[] = [
  summary("office-main", "여수 사무실 이전 네트워크 점검", "공유기를 안 가져가면 NAS 가 고립된다", 8, 34),
  summary("qb-night", "문제은행 야간 배치 결과 확인", "케이스 648개 중 612개가 풀에 없었다", 96, 12),
  summary("blog-draft", "네이버 블로그 초안 정리", "저장까지는 갔고 발행은 승인 대기", 190, 7),
];

function emptyHistory(session: string): ConversationHistory {
  return { session_id: session, summary: "", has_summary: false, messages: [], context_window: 131_072, retrieval_enabled: true, searchable_memory_count: 0 };
}

function historyOf(session: string, messages: ConversationHistory["messages"], extra: Partial<ConversationHistory> = {}): ConversationHistory {
  return { session_id: session, summary: "", has_summary: false, context_window: 131_072, retrieval_enabled: true, searchable_memory_count: 18, messages, ...extra };
}

const GOOGLE_CONNECTED: Partial<GoogleStatus> = {
  enabled: true, configured: true, connected: true, pending: false,
  email: "user@example.com", name: "홍길동", mode: "read_only", scopes: [], last_error: "",
};

const PEOPLE: Partial<PeopleStatus> = { enabled: true, ok: true, models_present: true, registered: ["사용자", "다른 사용자"] };

/** 일감 한 줄. 실제 `/v1/jobs?view=summary` 응답 모양 그대로다(실측으로 맞췄다). */
function job(
  id: string,
  title: string,
  status: JobSummary["status"],
  extra: Partial<JobSummary> = {},
): JobSummary {
  const created = NOW - (extra.attempts ? 900 : 240);
  return {
    id, kind: "chat", title, status,
    risk_level: "L0", error: "", build: "ef5edaaeb923",
    created_at: created, updated_at: NOW, started_at: created + 1, finished_at: null,
    attempts: 1, session_id: "office-main", origin: "workspace",
    steps: 0, completion_state: "",
    ...extra,
  };
}

/** 붙어서 잘 도는 브라우저. 실제 `/v1/browser/status` 응답에서 쓰는 칸만 옮겼다. */
const BROWSER_OK: Partial<BrowserStatus> = {
  enabled: true, started: true, liveness: "probed", headless: false, read_only: false,
  connect_mode: "attached", automation_flag: false, attach_error: "", last_error: "",
  stuck: false, circuit_open: false, recoveries: 0,
};

function schedule(id: string, title: string, minutesAhead: number, prompt: string): ScheduleRow {
  return {
    id, title, prompt, session_id: "office-main",
    run_at: NOW + minutesAhead * 60, status: "pending",
    created_at: NOW - 3600, updated_at: NOW - 3600, last_job_id: "",
  };
}

/** 표·코드·목록·첨부가 한 화면에 다 있는 최악의 조판 조건. */
const HEAVY_ANSWER = `## 3090 컨텍스트 실측 (2026-08-10)

| num_ctx | 모델 VRAM | 3090 여유 | prefill (4,029토큰) |
|---:|---:|---:|---:|
| 24,576 | 14.03 GB | 7,372 MiB | 1.08초 |
| 65,536 | 14.27 GB | 6,742 MiB | 1.08초 |
| 131,072 | 14.41 GB | 5,920 MiB | 1.21초 |

결론부터: **64K 로 둔다.** 컨텍스트는 이 모델에서 거의 공짜다 — Gemma 4 가 슬라이딩
윈도우 어텐션이라 KV 캐시가 창 크기만큼 자라지 않는다. 24K → 128K 가 **0.38GB**다.

- 창을 크게 잡는 것 자체는 값이 없다. **실제로 채웠을 때만** 비용이 붙는다
- 128K 가 아닌 이유: 진짜 상한은 여기가 아니라 전사 예산이고, 길수록 정확도가 떨어진다
- 이미 더 큰 러너가 떠 있으면 그대로 쓴다 — 14GB 재적재를 피하려는 장치다

\`\`\`python
GEMMA_NUM_CTX      = 131072  # Cowork 기본 128K — 모델 자체 한계는 262,144
GEMMA_MIN_NUM_CTX  = 16384
ADOPT_RESIDENT_CTX = True
\`\`\`

근거: 2026-08-10 실측(같은 입력 4,029토큰 3회).`;

/**
 * 통이미지 상세의 조각 하나를 흉내 낸 그림(지어낸 상품). 실제로는 백엔드가 읽기 직전의 조각을 줄여 보낸다.
 * 세 조각이 서로 달라야 조각이 넘어가는 것이 보인다 — 머리 · 사양 표 · 안내 글.
 */
function fakePiece(part: 1 | 2 | 3): string {
  const line = (y: number, w: number, tone = "#b9b4ab") => `<rect x='18' y='${y}' width='${w}' height='6' rx='2' fill='${tone}'/>`;
  const row = (y: number, label: string, value: string) =>
    `<rect x='18' y='${y}' width='204' height='24' fill='#f1eee8'/><rect x='18' y='${y}' width='70' height='24' fill='#e2ded6'/>`
    + `<text x='26' y='${y + 16}' font-size='10' fill='#55504a'>${label}</text><text x='98' y='${y + 16}' font-size='10' fill='#2b2824'>${value}</text>`;
  const body = part === 1
    ? `<text x='18' y='40' font-size='17' font-weight='700' fill='#22201d'>가온 K87 무선</text>`
      + `<text x='18' y='60' font-size='11' fill='#6b665f'>기계식 키보드 · 87키</text>`
      + `<rect x='18' y='78' width='204' height='150' rx='8' fill='#d9d5cc'/><rect x='38' y='128' width='164' height='56' rx='6' fill='#8f8a80'/>`
      + line(250, 180) + line(266, 150) + line(282, 196) + line(298, 120)
    : part === 2
      ? `<text x='18' y='34' font-size='13' font-weight='700' fill='#22201d'>상세 사양</text>`
        + row(48, "연결", "블루투스 5.1 · 2.4GHz") + row(76, "스위치", "저소음 적축") + row(104, "배터리", "4,000mAh")
        + row(132, "무게", "812g") + row(160, "키캡", "PBT 이중사출") + row(188, "보증", "구매일부터 1년")
        + line(236, 190) + line(252, 160) + line(268, 176) + line(300, 140) + line(316, 188)
      : `<text x='18' y='34' font-size='13' font-weight='700' fill='#22201d'>배송 · 교환 안내</text>`
        + line(54, 196) + line(70, 170) + line(86, 188) + line(102, 110)
        + `<rect x='18' y='128' width='204' height='64' rx='6' fill='#ece8e0'/><text x='28' y='152' font-size='10' fill='#55504a'>평일 14시 이전 주문은 당일 출고</text>`
        + `<text x='28' y='172' font-size='10' fill='#55504a'>수령 후 7일 안에 교환 신청</text>`
        + line(214, 180) + line(230, 150) + line(246, 196) + line(278, 130) + line(294, 170);
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='240' height='349' viewBox='0 0 240 349' font-family='Malgun Gothic, sans-serif'>`
    + `<rect width='240' height='349' fill='#faf8f4'/>${body}</svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export const SCENARIOS: Scenario[] = [
  {
    id: "welcome",
    label: "첫 화면",
    hint: "대화가 하나도 없을 때. 빈 상태가 무엇을 하라고 말하는지 본다.",
    sessions: [],
    history: emptyHistory("fixture-new"),
    google: { enabled: true, configured: true, connected: false, pending: false, mode: "read_only", scopes: [], last_error: "" },
    people: PEOPLE,
  },
  {
    id: "health-slow",
    label: "점검 줄 — 평소보다 느림",
    hint: "켤 때 점검이 고장을 찾았을 때. 고장 설명과 고치기 결과·진단 파일 안내가 서로 다른 줄에 뜨는지 본다.",
    sessions: [],
    history: emptyHistory("fixture-health"),
    people: PEOPLE,
    selfCheck: {
      pending: false,
      organs: [{
        organ: "model", state: "down", healer: "reload_model",
        detail: "평소(적용할 때 128 tok/s)보다 크게 느립니다 — 지금 2.3 tok/s.",
      }],
    },
  },
  {
    id: "update-store",
    label: "스토어판 — 새 버전 있음",
    hint: "「지금 업데이트」를 누르면 화면이 흐려지며 무슨 일인지 말하는지 본다. 리허설은 앱이 안 꺼지므로 덮개가 남는다.",
    sessions: [],
    history: emptyHistory("fixture-update"),
    people: PEOPLE,
    update: { ok: true, kind: "store", mine: "0.4.26261.2203", theirs: "0.4.26261.2330", available: true, how: "restart" },
  },
  {
    id: "update-store-done",
    label: "스토어판 — 업데이트 끝나고 다시 열림",
    hint: "새 버전으로 다시 열린 직후 한 번 뜨는 줄.",
    sessions: [],
    history: emptyHistory("fixture-update-done"),
    people: PEOPLE,
    update: { ok: true, kind: "store", mine: "0.4.26261.2330", theirs: "0.4.26261.2330", available: false,
              just_updated: { ok: true, from: "0.4.26261.2203", to: "0.4.26261.2330", installed: "0.4.26261.2330" } },
  },
  {
    id: "takeover-relay",
    label: "사용량 한도 이어오기",
    hint: "외부 도구의 출처 선이 Sonjari로 넘어오고, 기존 대화는 그대로 남는지 확인한다.",
    prompt: "클로드 사용량이 끝났어. 여기서 이어서 해줘",
    // 캡슐은 사용자가 말을 건 그 대화 위에 떠야 한다. 다른 주제 대화 위에 띄우면
    // 캡처가 「엉뚱한 대화에서 인계가 뜬다」를 보여 준다. 걸음도 비워 둔다 —
    // 기본 일곱 걸음(메일 승인)이 새 인계 대화 오른쪽 칸에 섞여 찍혔었다.
    sessions: [summary("handoff-chat", "클로드 한도 이어오기", "클로드 사용량이 끝났어. 여기서 이어서 해줘", 1, 1), ...SESSIONS],
    history: historyOf("handoff-chat", [
      said("handoff-chat", "user", "클로드 사용량이 끝났어. 여기서 이어서 해줘", 20),
    ]),
    steps: [],
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    ambient: [
      {
        at: 450,
        event: "takeover_offered",
        payload: {
          takeover_id: 17,
          other_count: 0,
          card: {
            tool: "claude_code", tool_name: "Claude Code",
            session_path: "C:/Users/example/.claude/projects/payments/session.jsonl",
            title: "결제 모듈 리팩터링", cwd: "C:/work/payments",
            stop_kind: "rate_limit", stopped_minutes_ago: 2, resets_at: null,
            last_request: "결제 실패 회귀 테스트도 붙여 줘",
            files: ["src/payments/service.py", "tests/test_payments.py"],
            open_tasks: ["실패 회귀 테스트 추가", "전체 테스트 확인"], request_count: 38,
            git: { repo: true, root: "C:/work/payments", branch: "feature/payment", changed_count: 2, untracked_count: 1 },
          },
        },
      },
    ],
    onSend: [
      { at: 80, event: "agent_thinking" },
      { at: 850, event: "agent_answer_delta", payload: { delta: "Claude Code에서 멈춘 지점과 남은 검증 항목을 확인했습니다." } },
      { at: 1300, event: "job_completed" },
    ],
    settledAnswer: "Claude Code에서 멈춘 지점과 남은 검증 항목을 확인했습니다.",
  },
  {
    id: "streaming",
    label: "답이 흘러나옴",
    hint: "생각하는 점 → 토큰이 흐름 → 안착. 3초 안에 답하면 설명 문구가 안 떠야 한다.",
    prompt: "오늘 우선순위를 정리해줘",
    sessions: SESSIONS,
    history: historyOf("office-main", [
      said("office-main", "user", "사무실 이전 전에 확인할 게 뭐가 있지?", 620),
      said("office-main", "assistant", "공유기를 안 가져가면 NAS 가 고립됩니다. NAS 는 자체 고정 IP 라 대역이 바뀌면 아무도 못 찾습니다.", 610, { grounding: { basis: "memory", observed_steps: 0 } }),
    ]),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    onSend: [
      { at: 60, event: "agent_thinking" },
      { at: 900, event: "agent_answer_delta", payload: { delta: "오늘은 세 가지입니다.\n\n" } },
      { at: 1150, event: "agent_answer_delta", payload: { delta: "**하나.** 이전 전에 공유기 대역을 확정해야 합니다" } },
      { at: 1400, event: "agent_answer_delta", payload: { delta: " — NAS 가 자체 고정 IP 라 대역이 바뀌면 고립됩니다.\n\n" } },
      { at: 1700, event: "agent_answer_delta", payload: { delta: "**둘.** 젯슨은 Wi-Fi 에 물려 있어서 같은 문제를 한 번 더 겪습니다.\n\n" } },
      { at: 2050, event: "agent_answer_delta", payload: { delta: "**셋.** 크몽 공고 반려 사유를 오늘 안에 정리해야 재제출이 가능합니다." } },
      { at: 2600, event: "job_completed" },
    ],
    settledAnswer: "오늘은 세 가지입니다.\n\n**하나.** 이전 전에 공유기 대역을 확정해야 합니다 — NAS 가 자체 고정 IP 라 대역이 바뀌면 고립됩니다.\n\n**둘.** 젯슨은 Wi-Fi 에 물려 있어서 같은 문제를 한 번 더 겪습니다.\n\n**셋.** 크몽 공고 반려 사유를 오늘 안에 정리해야 재제출이 가능합니다.",
  },
  {
    // 2026-10-07: 본 창이 시킨 판의 답은 판 밖에서 칠해진다(`workspace/settling.ts`). 판이 끝났다는 사건이 답 중간에 온다.
    id: "painting-apart",
    label: "판이 끝난 뒤에도 답이 칠해짐",
    hint: "「끝났다」가 답 중간에 온다. 풍선이 끊기지 않고 끝까지 흘러야 하고, 다 칠해진 뒤에 완성된 답으로 바뀐다.",
    prompt: "이번 주에 할 일을 정리해줘",
    sessions: SESSIONS,
    history: historyOf("office-main", []),
    onSend: [
      { at: 60, event: "agent_thinking" },
      { at: 500, event: "agent_answer_reset", payload: { apart: true } },
      { at: 600, event: "agent_answer_delta", payload: { delta: "이번 주는 네 가지입니다.\n\n" } },
      { at: 1000, event: "agent_answer_delta", payload: { delta: "**하나.** 견적서 초안을 수요일까지 보냅니다.\n\n" } },
      { at: 1300, event: "job_completed" },
      { at: 1900, event: "agent_answer_delta", payload: { delta: "**둘.** 회의실 예약을 다음 주로 옮깁니다.\n\n" } },
      { at: 2800, event: "agent_answer_delta", payload: { delta: "**셋.** 교육 자료의 표를 새 숫자로 바꿉니다.\n\n" } },
      { at: 3700, event: "agent_answer_delta", payload: { delta: "**넷.** 금요일 보고 전에 한 번 더 읽습니다." } },
      { at: 4300, event: "agent_answer_painted" },
    ],
    settledAnswer: "이번 주는 네 가지입니다.\n\n**하나.** 견적서 초안을 수요일까지 보냅니다.\n\n**둘.** 회의실 예약을 다음 주로 옮깁니다.\n\n**셋.** 교육 자료의 표를 새 숫자로 바꿉니다.\n\n**넷.** 금요일 보고 전에 한 번 더 읽습니다.",
  },
  {
    id: "agent-running",
    label: "도구를 쓰는 중",
    hint: "걸음이 붙는 리듬. 답이 도착한 뒤에도 궤적이 남는지가 핵심이다.",
    prompt: "최신 AI 에이전트 동향을 브라우저로 조사해줘",
    sessions: SESSIONS,
    // 사이드바 위층과 가운데 궤적이 **같은 일**을 말하는지 보려고 둔다.
    jobs: [job("fx-job-running", "최신 AI 에이전트 동향 조사", "running", { steps: 7, started_at: NOW - 46 })],
    browser: BROWSER_OK,
    browserFrame: { url: "https://www.kmong.com/search?type=gigs&keyword=RAG", title: "RAG 검색 결과 — 크몽" },
    outputs: [
      { step: 3, tool: "browser_screenshot", name: "20260819_161200_결과목록.png",
        path: "C:/Users/example/AppData/Local/AltureJarvis/outputs/browser-evidence/20260819_161200_결과목록.png",
        bytes: 486_112, kind: "image", exists: true, viewable: true },
      // 장부에는 있는데 사라진 파일. 조용히 빼면 "안 만들었다"와 구별이 안 된다.
      { step: 6, tool: "browser_screenshot", name: "20260819_161240_상세.png",
        path: "C:/Users/example/AppData/Local/AltureJarvis/outputs/browser-evidence/20260819_161240_상세.png",
        bytes: 0, kind: "image", exists: false, viewable: false },
    ],
    undo: [
      { undo_id: "fx-undo-1", tool: "naver_blog_save_draft", label: "블로그 임시저장을 지웁니다",
        automatic: true, manual_hint: "", what: { title: "AI 에이전트 동향 정리" },
        created_at: NOW - 20, expires_at: NOW + 1800 },
      { undo_id: "fx-undo-2", tool: "google_gmail_send", label: "보낸 메일은 Sonjari가 못 지웁니다",
        automatic: false, manual_hint: "Gmail 보낸편지함에서 직접 삭제해 주세요",
        what: { subject: "동향 정리" }, created_at: NOW - 18, expires_at: NOW + 1800 },
    ],
    history: historyOf("office-main", [
      said("office-main", "user", "지난번 조사 결과 어디에 저장했지?", 1200),
      said("office-main", "assistant", "`outputs/research/` 아래에 날짜별로 남겼습니다.", 1190),
    ]),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    onSend: [
      { at: 50, event: "agent_started" },
      // 시킨 것 대조 (R3). 처음에는 하나도 안 채워진 채로 뜨고, 걸음이 붙을 때마다
      // 채워진다 — 이게 143초를 견디게 하는 유일한 표시다.
      {
        at: 120,
        event: "agent_plan",
        payload: {
          met: 0, total: 3,
          items: [
            { kind: "count", label: "4개 이상 직접 열어 읽기", met: false, saw: "0개 읽음" },
            { kind: "site", label: "크몽에서 읽기", met: false, saw: "한 건도 못 읽음" },
            { kind: "site", label: "위시켓에서 읽기", met: false, saw: "한 건도 못 읽음" },
          ],
        },
      },
      { at: 400, event: "agent_progress", payload: { step: 1, phase: "plan", tool: "browser_open", message: "조사 계획을 세웠습니다", status: "completed" } },
      { at: 900, event: "agent_progress", payload: { step: 2, phase: "act", tool: "browser_site_search", message: "사이트에서 직접 검색", status: "completed" } },
      { at: 1500, event: "agent_progress", payload: { step: 3, phase: "act", tool: "browser_result_list", message: "결과 목록 24개를 읽었습니다", status: "completed" } },
      { at: 2100, event: "agent_progress", payload: { step: 4, phase: "act", tool: "browser_extract", message: "본문 3건을 끝까지 읽는 중", status: "running" } },
      {
        at: 3400,
        event: "agent_progress",
        payload: {
          step: 4, phase: "act", tool: "browser_extract", message: "본문 3건을 읽었습니다", status: "completed",
          // 근거 (R4). 이게 없으면 걸음은 도구 이름일 뿐이라 "봤다"를 대조할 수 없다.
          evidence: { url: "https://www.kmong.com/gig/612345", char_count: 4820, truncated: false },
        },
      },
      { at: 3900, event: "agent_progress", payload: { step: 5, phase: "act", tool: "browser_scroll", message: "표가 잘려 있어 끝까지 내렸습니다", status: "completed" } },
      { at: 4400, event: "agent_progress", payload: { step: 6, phase: "act", tool: "inhouse_lookup", message: "우리 데이터와 대조", status: "partial" } },
      {
        at: 4600,
        event: "agent_plan",
        payload: {
          met: 1, total: 3,
          items: [
            { kind: "count", label: "4개 이상 직접 열어 읽기", met: false, saw: "3개 읽음" },
            { kind: "site", label: "크몽에서 읽기", met: true, saw: "2건" },
            { kind: "site", label: "위시켓에서 읽기", met: false, saw: "한 건도 못 읽음" },
          ],
        },
      },
      { at: 5000, event: "agent_progress", payload: { step: 7, phase: "verify", tool: "evidence_check", message: "출처 3곳을 확인했습니다", status: "completed" } },
      {
        at: 5100,
        event: "agent_plan",
        payload: {
          met: 3, total: 3,
          items: [
            { kind: "count", label: "4개 이상 직접 열어 읽기", met: true, saw: "5개 읽음" },
            { kind: "site", label: "크몽에서 읽기", met: true, saw: "3건" },
            { kind: "site", label: "위시켓에서 읽기", met: true, saw: "2건" },
          ],
        },
      },
      { at: 5400, event: "agent_answer_delta", payload: { delta: HEAVY_ANSWER.slice(0, 420) } },
      { at: 5900, event: "agent_answer_delta", payload: { delta: HEAVY_ANSWER.slice(420) } },
      { at: 6600, event: "job_completed" },
    ],
    settledAnswer: HEAVY_ANSWER,
  },
  {
    // 2026-10-13 대표: 맞는 답 아래에 ⚠ 문단이 둘씩 매달리는 것이 불편하다. 본문에서 떼어 답 아래 접힌 한 줄과
    // 오른쪽 판의 노란 줄로 옮겼다(`workspace/answerChecks.ts`). 이름 · 값은 지어낸 것이다.
    id: "answer-checks",
    label: "확인할 것이 붙은 답",
    hint: "답 본문에 ⚠ 문단이 안 보이는지. 답 아래 「확인할 것 2」가 접혀 있고, 오른쪽 판의 초록 줄 아래에 노란 줄 둘이 뜨는지.",
    prompt: "가상 모델 A 와 B 중 어느 쪽이 맞는지 조사해줘",
    sessions: SESSIONS,
    jobs: [],
    browser: BROWSER_OK,
    browserFrame: { url: "https://docs.example/models/benchmarks", title: "가상 모델 벤치마크" },
    history: historyOf("office-main", []),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    onSend: [
      { at: 50, event: "agent_started" },
      { at: 120, event: "agent_plan", payload: { met: 0, total: 1, items: [{ kind: "count", label: "근거가 되는 대상 실제로 읽기", met: false, saw: "0개 읽음" }] } },
      { at: 500, event: "agent_progress", payload: { step: 1, phase: "act", tool: "browser_search", message: "검색했습니다", status: "completed" } },
      { at: 1100, event: "agent_progress", payload: { step: 2, phase: "act", tool: "browser_open_result", message: "문서를 열었습니다", status: "completed" } },
      {
        at: 1700,
        event: "agent_progress",
        payload: {
          step: 3, phase: "act", tool: "browser_extract", message: "본문을 읽었습니다", status: "completed",
          evidence: { url: "https://docs.example/models/benchmarks", char_count: 6120, truncated: false },
        },
      },
      { at: 1800, event: "agent_plan", payload: { met: 1, total: 1, items: [{ kind: "count", label: "근거가 되는 대상 실제로 읽기", met: true, saw: "1개 실제로 읽음" }] } },
      { at: 2200, event: "agent_answer_delta", payload: { delta: "**가상 모델 A 가 답입니다.** 3비트로 줄인 판 가운데 가장 안정적입니다." } },
      { at: 2800, event: "job_completed" },
    ],
    settledAnswer: [
      "**가상 모델 A 가 답입니다.** 3비트로 줄인 판 가운데 가장 안정적입니다.",
      "| 선택지 | 판단 |\n|---|---|\n| 가상 A | 가장 정합 |\n| 가상 B | A 보다 약간 나쁨, 5~10% 느림 |",
      "한 가지 주의: 숫자만 보고 단정할 수 없습니다. 실제로 돌려 본 체감이 기준입니다.",
      "⚠ **읽은 자료에 없는 비율이 있습니다: 17%** — 원문으로 확인하기 전에는 사실로 쓰지 마세요.",
      "⚠ **읽지 않고 적은 것이 있습니다: 가상 A, 가상 B.** 이 이름들은 이번에 읽은 자료(페이지·파일) 어디에도 없습니다 — 목록 줄에서 옮겨 적었을 수 있습니다. 필요하면 그 항목들을 직접 열어 확인해 달라고 시켜 주세요.",
    ].join("\n\n"),
  },
  {
    id: "image-reading",
    label: "그림으로 된 상세를 읽는 중",
    hint: "상세가 통이미지인 페이지. 일하면서 하는 말 줄 아래에 지금 읽는 조각과 조각 눈금이 뜨고, 다 읽으면 그림이 남지 않는지.",
    prompt: "이 키보드 상세 페이지에서 배터리와 보증 기간 알려줘",
    sessions: SESSIONS,
    jobs: [job("fx-job-running", "키보드 상세 사양 확인", "running", { steps: 2, started_at: NOW - 12 })],
    browser: BROWSER_OK,
    browserFrame: { url: "https://shop.example/item/k87", title: "가온 K87 무선 — 상세" },
    history: historyOf("office-main", []),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    onSend: [
      { at: 50, event: "agent_started" },
      { at: 400, event: "agent_progress", payload: { step: 1, phase: "act", tool: "browser_open", message: "상세 페이지를 열었습니다", status: "completed" } },
      { at: 500, event: "agent_says", payload: { step: 1, text: "상세 페이지를 열었습니다. 배터리와 보증 기간이 적힌 곳을 찾겠습니다." } },
      { at: 900, event: "agent_progress", payload: { step: 2, phase: "act", tool: "browser_extract", message: "본문 읽는 중", status: "running" } },
      { at: 1000, event: "agent_says", payload: { step: 2, text: "본문 글에는 사양이 없고 상세가 그림 한 장으로 되어 있습니다. 그림을 읽겠습니다." } },
      // 그림 조각은 걸음이 아니다 — 걸음 2가 도는 동안 말 줄 아래에 비췄다가, 걸음이 끝나면 거둔다.
      { at: 1300, event: "agent_looking", payload: { image: 1, images: 1, tile: 1, tiles: 3, width: 240, height: 349, picture: fakePiece(1) } },
      { at: 5300, event: "agent_looking", payload: { image: 1, images: 1, tile: 2, tiles: 3, width: 240, height: 349, picture: fakePiece(2) } },
      { at: 9300, event: "agent_looking", payload: { image: 1, images: 1, tile: 3, tiles: 3, width: 240, height: 349, picture: fakePiece(3) } },
      { at: 13300, event: "agent_looking", payload: { done: true } },
      {
        at: 13500,
        event: "agent_progress",
        payload: {
          step: 2, phase: "act", tool: "browser_extract", message: "본문과 상세 그림 1장을 읽었습니다", status: "completed",
          evidence: { url: "https://shop.example/item/k87", char_count: 1840, truncated: false },
        },
      },
      { at: 14200, event: "agent_answer_delta", payload: { delta: "배터리는 **4,000mAh**, 보증은 **구매일부터 1년**입니다. 두 값 모두 상세 그림에서 읽은 것이라 틀릴 수 있습니다 — 원문 그림과 대조해 주세요." } },
      { at: 15000, event: "job_completed" },
    ],
    settledAnswer: "배터리는 **4,000mAh**, 보증은 **구매일부터 1년**입니다. 두 값 모두 상세 그림에서 읽은 것이라 틀릴 수 있습니다 — 원문 그림과 대조해 주세요.",
  },
  {
    id: "viewer-approval",
    label: "걸음 되감기 · 승인",
    hint: "걸음을 눌러 그때 본 것을 편다. 초안 걸음(7)에서만 승인 버튼이 뜨는지 — 다른 걸음에서 뜨면 무엇에 동의하는지 모르는 채 누르게 된다.",
    prompt: "크몽 공고 단가가 시세에 맞는지 보고 파트너 담당자에게 메일 초안 잡아줘",
    sessions: SESSIONS,
    jobs: [job("fx-job-viewer", "크몽 단가 조사", "running", { steps: 7, started_at: NOW - 24 })],
    browser: BROWSER_OK,
    browserFrame: { url: "https://kmong.com/gig/641203", title: "메일 · 일정 자동 연동 구축 — 크몽" },
    history: historyOf("office-main", [
      said("office-main", "user", "우리 단가표 어디 있더라?", 900),
      said("office-main", "assistant", "`docs/단가표_2026.xlsx` 입니다.", 890),
    ]),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    onSend: [
      { at: 50, event: "agent_started" },
      { at: 300, event: "agent_progress", payload: { phase: "tool", step: 1, tool: "local_search_files", message: "문서 폴더에서 「단가」 찾는 중", status: "completed" } },
      { at: 900, event: "agent_progress", payload: { phase: "tool", step: 2, tool: "local_read_document", message: "단가표_2026.xlsx 읽는 중", status: "completed" } },
      { at: 1500, event: "agent_progress", payload: { phase: "tool", step: 3, tool: "local_read_text_file", message: "ComputerPane.tsx 읽는 중", status: "completed" } },
      { at: 2100, event: "agent_progress", payload: { phase: "tool", step: 4, tool: "browser_site_search", message: "크몽에서 「업무 자동화」 찾는 중", status: "completed" } },
      { at: 2800, event: "agent_progress", payload: { phase: "tool", step: 5, tool: "browser_extract", message: "공고 5개 본문 읽는 중", status: "completed" } },
      { at: 3300, event: "agent_progress", payload: { phase: "tool", step: 6, tool: "browser_click", message: "가격표 더 보기를 누르는 중", status: "failed" } },
      { at: 3800, event: "agent_progress", payload: { phase: "tool", step: 7, tool: "google_gmail_prepare_send", message: "메일 초안 만드는 중", status: "completed" } },
      {
        at: 4200,
        event: "agent_plan",
        payload: {
          job_id: "",
          met: 2,
          total: 3,
          items: [
            { kind: "action", label: "우리 단가표를 근거로 쓸 것", met: true, saw: "6행 읽음" },
            { kind: "count", label: "공고 5개는 직접 열어 읽을 것", met: true, saw: "5개 읽음" },
            { kind: "action", label: "메일은 승인 뒤에 보낼 것", met: false, saw: "아직" },
          ],
        },
      },
      { at: 4400, event: "state_changed", payload: { to: "waiting_approval" } },
      {
        at: 4600,
        event: "approval_requested",
        payload: {
          nonce: "fixture-approval-viewer",
          tool_name: "google_gmail_send",
          expires_at: NOW + 1800,
          // ★ `fixtures/observations.ts` 7걸음의 action_id 와 **같아야** 게이트가 뜬다.
          //   다르면 화면에 뜬 초안과 기다리는 건이 다른 것이고, 그때는 안 뜨는 게 맞다.
          arguments: { action_id: "fixture-action-1" },
        },
      },
    ],
  },
  {
    id: "approval",
    label: "승인 대기",
    hint: "카드가 화면을 덮지 않고 그 자리에서 자란다. 뒤의 대화가 계속 보이는지 확인한다.",
    sessions: SESSIONS,
    history: historyOf("blog-draft", [
      said("blog-draft", "user", "정리한 내용 파트너 담당자에게 메일로 보내줘", 90),
      said("blog-draft", "assistant", "초안을 만들었습니다. 보내기 전에 확인해 주세요.", 60),
    ]),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    ambient: [
      { at: 300, event: "state_changed", payload: { to: "waiting_approval" } },
      {
        at: 400,
        event: "approval_requested",
        payload: {
          nonce: "fixture-approval-1",
          tool_name: "google_gmail_send",
          expires_at: NOW + 1800,
          arguments: { action_id: "fixture-action-1" },
        },
      },
    ],
  },
  {
    id: "question",
    label: "선택지 질문",
    hint: "모델이 선택지로 묻는 카드(ask_user). 추천 표시가 한눈에 보이는지, 누르면 바로 보내지는지, 좁은 창에서도 안 깨지는지.",
    sessions: SESSIONS,
    history: historyOf("office-main", [
      said("office-main", "user", "여행 경비 정산 웹앱 만들어 줘", 60),
    ]),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    ambient: [
      { at: 300, event: "state_changed", payload: { to: "waiting_approval" } },
      {
        at: 400,
        event: "approval_requested",
        payload: {
          nonce: "fixture-question-1",
          tool_name: "ask_user",
          expires_at: NOW + 1800,
          arguments: {
            question: "정산 결과를 어떻게 보여 드릴까요?",
            options: [
              { label: "누가 누구에게 얼마", description: "송금 횟수가 가장 적게 되도록 짝지어 보여 줍니다" },
              { label: "사람별 합계만", description: "각자 낸 돈과 내야 할 돈의 차이만 보여 줍니다" },
              { label: "둘 다", description: "위에 합계, 아래에 송금 목록" },
            ],
            recommended: 0,
          },
          target: {
            question: "정산 결과를 어떻게 보여 드릴까요?",
            options: [
              { label: "누가 누구에게 얼마", description: "송금 횟수가 가장 적게 되도록 짝지어 보여 줍니다" },
              { label: "사람별 합계만", description: "각자 낸 돈과 내야 할 돈의 차이만 보여 줍니다" },
              { label: "둘 다", description: "위에 합계, 아래에 송금 목록" },
            ],
            recommended: 0,
          },
        },
      },
    ],
  },
  {
    id: "continuation",
    label: "계속 진행 묻기",
    hint: "예산이 다 됐을 때. 숫자 셋(걸음·초·출처)이 읽히는 크기인지.",
    sessions: SESSIONS,
    history: historyOf("office-main", [
      said("office-main", "user", "경쟁사 다섯 곳 가격을 전부 훑어줘", 300),
    ]),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    ambient: [
      { at: 300, event: "state_changed", payload: { to: "waiting_continuation" } },
      {
        at: 400,
        event: "agent_continuation_requested",
        payload: {
          job_id: "fixture-job-continuation",
          goal: "경쟁사 다섯 곳의 요금제를 표로 정리하고, 우리 가격과 나란히 놓는다",
          reason: "time_budget",
          elapsed_sec: 182,
          steps: 14,
          successful_steps: 12,
          failed_steps: 2,
          sources: 6,
          expires_at: NOW + 1800,
        },
      },
    ],
  },
  {
    id: "attention",
    label: "사람이 나서야 함",
    hint: "로그인·캡차처럼 Sonjari가 못 지나가는 문. 배너가 작성창을 가리지 않는지.",
    sessions: SESSIONS,
    history: historyOf("blog-draft", [
      said("blog-draft", "user", "블로그에 초안 저장해줘", 120),
    ]),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    ambient: [
      {
        at: 300,
        event: "attention_required",
        payload: {
          job_id: "fixture-job-attention",
          code: "login_required",
          tool: "browser_open",
          title: "네이버 로그인이 필요합니다",
          message: "열어 둔 창에서 로그인해 주시면 이어서 진행합니다. '로그인 상태 유지'를 켜면 다음부터는 묻지 않습니다.",
          url: "https://nid.naver.com/nidlogin.login",
        },
      },
    ],
  },
  {
    id: "stage-gate",
    label: "무대 · 사람 차례",
    history: historyOf("office-main", []),
    hint: "브라우저 무대가 열린 채 로그인 문이 뜬다. 주 버튼이 「여기서 직접 하기」인지, 누르면 무대가 넘겨받는지.",
    sessions: SESSIONS,
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    prompt: "위시켓에서 AI 에이전트 프로젝트 3개 알려줘",
    jobs: [job("fx-job-gate", "위시켓 AI 에이전트 프로젝트", "running", { steps: 2, started_at: NOW - 20 })],
    browser: BROWSER_OK,
    browserFrame: { url: "https://auth.wishket.com/login/", title: "로그인 — 위시켓" },
    onSend: [
      { at: 50, event: "agent_started" },
      { at: 400, event: "agent_progress", payload: { step: 1, phase: "act", tool: "browser_open", message: "위시켓을 여는 중", status: "running" } },
      { at: 1200, event: "agent_progress", payload: { step: 1, phase: "act", tool: "browser_open", message: "위시켓을 열었습니다", status: "ok" } },
      // 실제 백엔드 순서: 사람 문 → `agent_waiting_for_human` → 체크포인트 `agent_continuation_requested`.
      {
        at: 1800,
        event: "agent_waiting_for_human",
        payload: {
          code: "login_required",
          url: "https://auth.wishket.com/login/",
          steps: 1,
          message: "**로그인이 필요해요.** Sonjari 창의 브라우저 화면을 눌러 직접 평소처럼 로그인해 주세요.\n\n다 하시면 제가 알아서 이어서 할게요.",
        },
      },
      { at: 1900, event: "agent_continuation_requested", payload: { reason: "human_gate:login_required", steps: 1 } },
    ],
  },
  {
    id: "error",
    label: "실패",
    hint: "에러가 무엇이 잘못됐고 어떻게 고치는지 말하는지. 지금은 안 말한다.",
    prompt: "첨부한 문서를 읽고 핵심만 정리해줘",
    sessions: SESSIONS,
    history: historyOf("office-main", [
      said("office-main", "user", "이 PDF 요약해줘", 400, { attachments: [{ name: "이전_견적서.pdf", mime_type: "application/pdf" }] }),
      said("office-main", "assistant", "22쪽 중 핵심은 임대차 기간과 원상복구 조항입니다.", 380),
    ]),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    onSend: [
      { at: 60, event: "agent_thinking" },
      { at: 800, event: "agent_progress", payload: { step: 1, phase: "act", tool: "file_read", message: "파일을 여는 중", status: "running" } },
      { at: 1800, event: "agent_progress", payload: { step: 1, phase: "act", tool: "file_read", message: "파일을 열지 못했습니다", status: "failed" } },
      { at: 2100, event: "job_failed", payload: { error: "문서를 읽지 못했습니다." } },
    ],
  },
  {
    id: "long-table",
    label: "긴 답 · 표 · 첨부",
    hint: "조판이 무너지는 조건. 표가 가로로 새는지, 첨부 칩이 읽히는지.",
    sessions: SESSIONS,
    history: historyOf("qb-night", [
      said("qb-night", "user", "3090 컨텍스트 실측 결과 정리해줘", 900, {
        attachments: [
          { name: "ollama_ps_2026-08-03.log", mime_type: "text/plain" },
          { name: "nvidia-smi_샘플45.csv", mime_type: "text/csv" },
        ],
      }),
      said("qb-night", "assistant", HEAVY_ANSWER, 880),
      said("qb-night", "user", "그럼 32K 는 아예 못 쓰는 거야?", 300),
      said("qb-night", "assistant", "계산은 됩니다. 상주가 안 될 뿐입니다 — 그래서 기본값으로 안 씁니다.", 290),
    ], { has_summary: true, summary: "3090 컨텍스트 실측과 64K 결정" }),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    // 도는 작업이 **없는** 채로 마지막 화면이 남아 있는 경우. 여기서 폴링이
    // 멈추는지를 본다 — 가만히 있는 화면이 1.5초마다 네트워크를 쓰면 안 된다.
    browser: BROWSER_OK,
    browserFrame: { url: "https://ollama.com/library/gemma3", title: "gemma3 — Ollama" },
  },
  {
    id: "jobs",
    label: "일감이 여러 개",
    hint: "사이드바 위층. 승인 대기가 도는 것보다 위에 오는지, 소요·걸음수가 매초 흔들리지 않는지.",
    sessions: SESSIONS,
    history: historyOf("office-main", [
      said("office-main", "user", "크몽하고 위시켓 두 군데 같이 훑어줘", 640),
      said("office-main", "assistant", "두 곳을 나눠서 돌리고 있습니다. 왼쪽에서 진행을 보실 수 있습니다.", 630),
    ]),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    jobs: [
      job("fx-job-approval", "다른 사용자께 이전 체크리스트 메일 보내기", "waiting_approval", {
        risk_level: "L2", steps: 9, started_at: NOW - 212,
      }),
      job("fx-job-running", "크몽에서 AI 챗봇 서비스 시세 조사", "running", {
        steps: 14, started_at: NOW - 143,
      }),
      job("fx-job-queued", "위시켓 공고 8건 읽고 표로 정리", "queued", {
        started_at: null, steps: 0,
      }),
      job("fx-job-partial", "경쟁사 다섯 곳 요금제 비교", "completed", {
        steps: 26, started_at: NOW - 1_100, finished_at: NOW - 786,
        completion_state: "partial", session_id: "qb-night",
      }),
      job("fx-job-done", "3090 컨텍스트 실측 정리", "completed", {
        steps: 4, started_at: NOW - 3_000, finished_at: NOW - 2_957,
        completion_state: "complete", session_id: "qb-night",
      }),
      job("fx-job-failed", "네이버 블로그 초안 저장", "failed", {
        risk_level: "L1", steps: 6, attempts: 2, started_at: NOW - 5_000, finished_at: NOW - 4_890,
        error: "로그인이 필요합니다", session_id: "blog-draft",
      }),
      job("fx-job-cancelled", "교보문고에서 책 3권 찾기", "cancelled", {
        steps: 2, started_at: NOW - 9_000, finished_at: NOW - 8_700, session_id: "blog-draft",
      }),
    ],
    schedules: [
      schedule("fx-sch-1", "아침 브리핑", 47, "오늘 일정과 남은 일감을 정리해줘"),
      schedule("fx-sch-2", "주간 QB 풀 점검", 1_580, "문제은행 야간 배치 결과를 확인해줘"),
    ],
  },
  {
    id: "browser-blocked",
    label: "브라우저가 막힘",
    hint: "화면을 못 가져올 때. 빈 상태가 **왜 없는지**와 사람이 할 일을 말하는지.",
    sessions: SESSIONS,
    history: historyOf("blog-draft", [
      said("blog-draft", "user", "사람인에서 정규직 공고 3개만 골라줘", 200),
    ]),
    google: GOOGLE_CONNECTED,
    people: PEOPLE,
    prompt: "사람인에서 정규직 공고 3개만 골라줘",
    jobs: [job("fx-job-blocked", "사람인에서 정규직 공고 3개 고르기", "running", { steps: 3, started_at: NOW - 71 })],
    // 컴퓨터 칸은 **이 창이 보낸 일**이 돌 때 열린다. 그래야 빈 상태를 눈으로 본다.
    onSend: [
      { at: 50, event: "agent_started" },
      { at: 500, event: "agent_progress", payload: { step: 1, phase: "act", tool: "browser_open", message: "사람인을 여는 중", status: "running" } },
      { at: 2600, event: "agent_progress", payload: { step: 1, phase: "act", tool: "browser_open", message: "브라우저를 열지 못했습니다", status: "failed" } },
      { at: 3000, event: "job_failed", payload: { error: "브라우저에 붙지 못했습니다." } },
    ],
    // 붙기에 실패한 상태. 화면에는 아무것도 없고, 사람이 크롬을 껐다 켜야 한다.
    browser: {
      ...BROWSER_OK,
      started: false,
      connect_mode: "",
      automation_flag: null,
      attach_error: "9222 포트에 붙지 못했습니다(연결 거부)",
      recoveries: 4,
    },
  },
];

export const DEFAULT_SCENARIO = SCENARIOS[0].id;

export function findScenario(id: string | null): Scenario | null {
  if (!id) return null;
  return SCENARIOS.find((row) => row.id === id) ?? null;
}
