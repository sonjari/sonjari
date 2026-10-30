// @vitest-environment jsdom
// 윈도우 알림(2026-10-27) — 언제 띄우고 언제 안 띄우나. 띄우기(Rust)는 가짜로 갈아 끼우고 판단만 본다.
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  NOTIFY_ENABLED_KEY, createNotifier, factsOf, readNotifyEnabled, stuckReason, writeNotifyEnabled,
  type NotifyDeps, type ToastRequest,
} from "./notify";
import type { JarvisEvent, JobDetail } from "./types";

function job(extra: Partial<JobDetail> & { payload?: Record<string, unknown>; result?: Record<string, unknown> } = {}): JobDetail {
  return {
    id: "job-1", kind: "chat", title: "3ds Max 폴더에서 NPC 파일 찾아 엑셀로 정리해 줘", status: "completed", risk_level: "L0", error: "",
    created_at: 1, updated_at: 2, started_at: 1, finished_at: 2, attempts: 1, build: "t",
    payload: { origin: "workspace", session_id: "room-1" },
    result: { answer: "파일 12개를 찾아 표로 정리했습니다. 경로는 아래와 같습니다.", completion_state: "complete" },
    ...extra,
  } as unknown as JobDetail;
}

function setup(over: { front?: boolean; enabled?: boolean; loaded?: JobDetail | null; outputs?: boolean | Error } = {}) {
  const shown: ToastRequest[] = [];
  const deps: NotifyDeps = {
    enabled: () => over.enabled ?? true,
    inFront: async () => over.front ?? false,
    show: async (toast) => { shown.push(toast); },
    loadJob: vi.fn(async () => (over.loaded === undefined ? job() : over.loaded)),
    hasOutputs: vi.fn(async () => {
      if (over.outputs instanceof Error) throw over.outputs;
      return over.outputs ?? false;
    }),
  };
  return { shown, notifier: createNotifier(deps), deps };
}

const completed: JarvisEvent = { event: "job_completed", payload: { job_id: "job-1", result: {} } };
const failedTimeout: JarvisEvent = { event: "job_failed", payload: { job_id: "job-1", error: "timed out" } };
const approval: JarvisEvent = { event: "approval_requested", payload: { job_id: "job-1", nonce: "n1", tool_name: "local_write_file", target: { label: "바탕화면에 쓰기" } } };

const stuckJob = (wait: Record<string, unknown>) =>
  job({ status: "failed", error: "timed out", result: { failed: true, diagnosis: { model_wait: wait } } });

describe("창이 앞에 있으면 안 띄운다", () => {
  it.each([completed, failedTimeout, approval])("앞에 있으면 %# 번째 사건도 조용하다", async (event) => {
    const { shown, notifier } = setup({ front: true, loaded: stuckJob({ phase: "no_first_token", limit_sec: 300 }) });
    expect(await notifier.onEvent(event)).toBe("in_front");
    expect(shown).toEqual([]);
  });
});

describe("창이 뒤에 있으면 세 때 모두 띄운다", () => {
  it("① 끝났을 때 — 제목은 요청 앞부분, 본문은 결과 한 줄", async () => {
    const { shown, notifier } = setup();
    expect(await notifier.onEvent(completed)).toBe("shown");
    expect(shown).toHaveLength(1);
    expect(shown[0].title).toBe("3ds Max 폴더에서 NPC 파일 찾아 엑셀로 정리해 줘".slice(0, 30) + "…");
    expect(shown[0].body).toBe("끝났습니다 — 파일 12개를 찾아 표로 정리했습니다.");
    expect(shown[0].sessionId).toBe("room-1");
    expect(shown[0].jobId).toBe("job-1");
  });

  it("① 일부만 끝났을 때 · 실패했을 때는 말이 다르다", async () => {
    const partial = setup({ loaded: job({ result: { answer: "5개 중 2개만 채웠습니다.", completion_state: "partial" } }) });
    await partial.notifier.onEvent(completed);
    expect(partial.shown[0].body).toBe("일부만 끝났습니다 — 5개 중 2개만 채웠습니다.");

    const failed = setup({ loaded: job({ status: "failed", error: "path_outside_allowed_roots: 허락한 폴더 밖입니다.", result: { failed: true } }) });
    await failed.notifier.onEvent({ event: "job_failed", payload: { job_id: "job-1", error: "x" } });
    expect(failed.shown[0].body).toBe("끝내지 못했습니다 — 허락한 폴더 밖입니다.");
  });

  it("② 승인 · 질문 · 사람이 해야 하는 화면 · 계속할지 묻기", async () => {
    const { shown, notifier } = setup();
    await notifier.onEvent(approval);
    await notifier.onEvent({ event: "approval_requested", payload: { job_id: "job-1", nonce: "n2", tool_name: "ask_user", target: { question: "어느 폴더부터 볼까요?" } } });
    await notifier.onEvent({ event: "attention_required", payload: { job_id: "job-1", title: "로그인이 필요해요", message: "크롬에서 로그인해 주세요." } });
    await notifier.onEvent({ event: "agent_continuation_requested", payload: { job_id: "job-1", reason: "time_budget" } });
    expect(shown.map((toast) => toast.body)).toEqual([
      "승인이 필요합니다 — 바탕화면에 쓰기",
      "질문이 있습니다 — 어느 폴더부터 볼까요?",
      "로그인이 필요해요 — 크롬에서 로그인해 주세요.",
      "시간이 다 되어 계속할지 묻고 있습니다",
    ]);
  });

  it("③ 막혔을 때 — 끝맺음 문장과 같은 까닭 한 줄", async () => {
    const { shown, notifier } = setup({ loaded: stuckJob({ phase: "no_first_token", limit_sec: 300, auto_resumed: true }) });
    await notifier.onEvent(failedTimeout);
    expect(shown[0].body).toContain("모델이 첫 글자를 300초 동안 내놓지 못했습니다");
    expect(shown[0].body).toContain("이어서 해줘");
  });

  it("③ 그래픽카드가 가득 차 다시 안 불렀으면 그 말을 한다", () => {
    const text = stuckReason({ diagnosis: { model_wait: { phase: "no_first_token", limit_sec: 300, resume_skipped: "card_full" } } });
    expect(text).toContain("그래픽카드가 가득 차 있어 다시 불러도 같은 자리에서 멈출 가능성이 큽니다");
    expect(text).toContain("다른 프로그램을 닫은 뒤");
  });

  it("같은 순간 두 카드(승인 안내와 사람 문)가 와도 한 번만 띄운다", async () => {
    const { shown, notifier } = setup();
    await notifier.onEvent({ event: "attention_required", payload: { job_id: "job-1", title: "로그인이 필요해요", message: "" } });
    expect(await notifier.onEvent({ event: "agent_waiting_for_human", payload: { job_id: "job-1", code: "login_required", message: "" } })).toBe("duplicate");
    expect(shown).toHaveLength(1);
  });
});

describe("끄기 설정", () => {
  it("꺼져 있으면 세 때 모두 안 띄우고, 일감을 읽으러 가지도 않는다", async () => {
    const { shown, notifier, deps } = setup({ enabled: false });
    for (const event of [completed, failedTimeout, approval]) expect(await notifier.onEvent(event)).toBe("disabled");
    expect(shown).toEqual([]);
    expect(deps.loadJob).not.toHaveBeenCalled();
  });

  beforeEach(() => window.localStorage.clear());

  it("설정은 기본 켬이고, 끄면 다음에도 꺼져 있다", () => {
    expect(readNotifyEnabled()).toBe(true);
    writeNotifyEnabled(false);
    expect(window.localStorage.getItem(NOTIFY_ENABLED_KEY)).toBe("off");
    expect(readNotifyEnabled()).toBe(false);
    writeNotifyEnabled(true);
    expect(readNotifyEnabled()).toBe(true);
  });
});

describe("바깥 AI 가 맡긴 판은 ②(기다림) · ③(막힘)만", () => {
  const external = { origin: "mcp", session_id: "mcp-abc" };
  const loginGate: JarvisEvent = { event: "agent_waiting_for_human", payload: { job_id: "job-1", code: "login_required", message: "크롬에서 로그인해 주세요." } };

  it("MCP 로 맡긴 판의 완료 알림은 안 띄운다(그쪽이 결과를 받는다)", async () => {
    const { shown, notifier } = setup({ loaded: job({ payload: external }) });
    expect(await notifier.onEvent(completed)).toBe("external");
    expect(shown).toEqual([]);
  });

  it("MCP 로 맡긴 판이 로그인을 기다리면 띄운다 — 바깥 AI 는 그 단계를 못 한다", async () => {
    const { shown, notifier } = setup({ loaded: job({ payload: external }) });
    expect(await notifier.onEvent(loginGate)).toBe("shown");
    expect(shown).toHaveLength(1);
    expect(shown[0].tone).toBe("waiting");
    expect(shown[0].body).toContain("크롬에서 로그인해 주세요.");
  });

  it("승인 카드 · 질문도 바깥 AI 판이면 띄운다", async () => {
    const { shown, notifier } = setup({ loaded: job({ payload: external }) });
    expect(await notifier.onEvent(approval)).toBe("shown");
    expect(await notifier.onEvent({ event: "approval_requested", payload: { job_id: "job-1", nonce: "n2", tool_name: "ask_user", target: { question: "어느 폴더부터 볼까요?" } } })).toBe("shown");
    expect(shown.map((toast) => toast.tone)).toEqual(["waiting", "waiting"]);
  });

  it("바깥 AI 판의 기다림 알림도 같은 일은 한 번만 띄우고, 창이 앞이면 안 띄운다", async () => {
    const dup = setup({ loaded: job({ payload: external }) });
    await dup.notifier.onEvent({ event: "attention_required", payload: { job_id: "job-1", title: "로그인이 필요해요", message: "" } });
    expect(await dup.notifier.onEvent(loginGate)).toBe("duplicate");
    expect(dup.shown).toHaveLength(1);

    const front = setup({ front: true, loaded: job({ payload: external }) });
    expect(await front.notifier.onEvent(loginGate)).toBe("in_front");
    expect(front.shown).toEqual([]);
  });

  it("앱 안 Claude(via=app) · 원격(via=remote) 판도 완료는 조용하고 기다림은 띄운다", async () => {
    for (const via of ["app", "remote"]) {
      const { shown, notifier } = setup({ loaded: job({ payload: { origin: "workspace", via } }) });
      expect(await notifier.onEvent(completed)).toBe("external");
      expect(shown).toEqual([]);
      expect(await notifier.onEvent(loginGate)).toBe("shown");
      expect(shown).toHaveLength(1);
    }
  });

  it("그래도 막혔을 때는 띄운다", async () => {
    const { shown, notifier } = setup({ loaded: { ...stuckJob({ phase: "no_first_token", limit_sec: 300 }), payload: external } as JobDetail });
    expect(await notifier.onEvent(failedTimeout)).toBe("shown");
    expect(shown[0].body).toContain("첫 글자를 300초");
  });

  it("바깥 AI 판이라도 창이 앞에 있으면 막힘 알림도 안 띄운다", async () => {
    const { shown, notifier } = setup({ front: true, loaded: { ...stuckJob({ phase: "no_first_token", limit_sec: 300 }), payload: external } as JobDetail });
    expect(await notifier.onEvent(failedTimeout)).toBe("in_front");
    expect(shown).toEqual([]);
  });
});

describe("그 밖", () => {
  it("대화 · 조사가 아닌 판(음성 · 받아쓰기)은 끝나도 안 띄운다", async () => {
    const { shown, notifier } = setup({ loaded: job({ kind: "tts" }) });
    expect(await notifier.onEvent(completed)).toBe("ignored");
    expect(shown).toEqual([]);
  });

  it("일감을 못 읽어도(null) 막힘이 아니면 띄우고, 모르는 판은 사람의 판으로 본다", async () => {
    const { shown, notifier } = setup({ loaded: null });
    expect(await notifier.onEvent(approval)).toBe("shown");
    expect(shown[0].title).toBe("손자리");
  });

  it("알림 대상이 아닌 사건은 건드리지 않는다", async () => {
    const { notifier, deps } = setup();
    expect(await notifier.onEvent({ event: "agent_progress", payload: { job_id: "job-1" } })).toBe("ignored");
    expect(deps.loadJob).not.toHaveBeenCalled();
  });

  it("창이 앞인지 못 알아내도 알림은 놓치지 않는다", async () => {
    const shown: ToastRequest[] = [];
    const notifier = createNotifier({
      enabled: () => true, inFront: async () => { throw new Error("boom"); }, show: async (toast) => { shown.push(toast); },
      loadJob: async () => job(),
    });
    expect(await notifier.onEvent(completed)).toBe("shown");
    expect(shown).toHaveLength(1);
  });

  it("factsOf 는 payload 의 어디서 왔는지를 읽는다", () => {
    expect(factsOf(job({ payload: { origin: "mcp", via: "app", session_id: "s" } })).origin).toBe("mcp");
  });
});

describe("모양 — 큰 그림 · 출처 줄 · 단추", () => {
  it("끝났어요: 그림 done · 출처 줄 · 「열기」 · 산출물이 있으면 「결과 폴더」", async () => {
    const { shown, notifier } = setup({ outputs: true });
    await notifier.onEvent(completed);
    expect(shown[0]).toMatchObject({ tone: "done", attribution: "대화", openLabel: "열기", folderLabel: "결과 폴더", lang: "ko" });
  });

  it("산출물이 없거나 못 읽으면 「결과 폴더」 없이 「열기」만", async () => {
    for (const outputs of [false, new Error("down")]) {
      const { shown, notifier } = setup({ outputs });
      await notifier.onEvent(completed);
      expect(shown[0].folderLabel).toBeNull();
      expect(shown[0].openLabel).toBe("열기");
    }
  });

  it("기다려요: 그림 waiting · 「열기」만(산출물이 있어도 폴더 단추 없음) · 산출물을 묻지도 않는다", async () => {
    const { shown, notifier, deps } = setup({ outputs: true });
    await notifier.onEvent(approval);
    expect(shown[0]).toMatchObject({ tone: "waiting", folderLabel: null, openLabel: "열기" });
    expect(deps.hasOutputs).not.toHaveBeenCalled();
  });

  it("막혔어요 · 끝내지 못했어요: 그림 stuck · 폴더 단추 없음", async () => {
    const stuck = setup({ outputs: true, loaded: stuckJob({ phase: "no_first_token", limit_sec: 300 }) });
    await stuck.notifier.onEvent(failedTimeout);
    expect(stuck.shown[0]).toMatchObject({ tone: "stuck", folderLabel: null });
    const failed = setup({ outputs: true, loaded: job({ status: "failed", error: "path_outside_allowed_roots: 허락한 폴더 밖입니다.", result: { failed: true } }) });
    await failed.notifier.onEvent({ event: "job_failed", payload: { job_id: "job-1", error: "x" } });
    expect(failed.shown[0]).toMatchObject({ tone: "stuck", folderLabel: null });
  });

  it("출처 줄은 판 종류를 따른다(코드 · 조사)", async () => {
    const code = setup({ loaded: job({ payload: { origin: "workspace", session_id: "r", workspace_mode: "code" } }) });
    await code.notifier.onEvent(completed);
    expect(code.shown[0].attribution).toBe("코드");
    const research = setup({ loaded: job({ kind: "research" }) });
    await research.notifier.onEvent(completed);
    expect(research.shown[0].attribution).toBe("조사");
  });
});
