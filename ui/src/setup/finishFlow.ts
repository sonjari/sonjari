/**
 * 「Sonjari 시작하기」가 하는 일 — **어느 것이 멈춰도 화면은 넘어간다** (2026-10-06 스토어판 첫 설치, 6GB 노트북).
 *
 * 예전에는 세 가지를 차례로 끝날 때까지 기다렸다: 끝냈다고 적기(시간 제한 없는 fetch) → 시작 프로그램 등록
 * (Windows 가 답할 때까지 막힘) → 창 바꾸기. 하나라도 답이 안 오면 단추가 죽은 것처럼 보였고, 처리 중 표시도 없었다.
 * 그 노트북에서는 모델 실행기가 멈춰 있었고, 「눌러도 아무 반응이 없다」가 나왔다.
 *
 * 규칙
 * - 적기는 `recordMs` 까지만 기다린다. 못 적으면 다음 실행에 마법사가 한 번 더 뜰 뿐이다.
 * - 시작 프로그램 등록은 **기다리지 않는다.** Windows 확인 창이 뜨거나 답이 없어도 화면은 넘어간다.
 * - 창 바꾸기가 `switchMs` 안에 안 되면 같은 창에서 작업 화면으로 간다.
 */
export interface FinishDeps {
  /** 끝냈다고 백엔드에 적는다. */
  record: () => Promise<unknown>;
  /** 시작 프로그램 등록 — 사람이 체크했을 때만 준다. */
  startup?: () => Promise<unknown>;
  /** 앱이 작업 창을 열고 마법사 창을 닫는다(포장된 앱에서만). */
  switchWindow?: () => Promise<unknown>;
  /** 같은 창에서 작업 화면으로 간다 — 마지막 길. */
  goSameWindow: () => void;
  recordMs?: number;
  switchMs?: number;
}

export interface FinishOutcome {
  recorded: "ok" | "failed" | "timeout";
  switched: "window" | "same_window";
}

export const FINISH_RECORD_MS = 5000;
export const FINISH_SWITCH_MS = 8000;

const TIMED_OUT = Symbol("timed_out");

function within<T>(work: Promise<T>, ms: number): Promise<T | typeof TIMED_OUT> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => resolve(TIMED_OUT), ms);
    work.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

export async function finishSetupFlow(deps: FinishDeps): Promise<FinishOutcome> {
  let recorded: FinishOutcome["recorded"] = "ok";
  try {
    if ((await within(deps.record(), deps.recordMs ?? FINISH_RECORD_MS)) === TIMED_OUT) recorded = "timeout";
  } catch {
    recorded = "failed";
  }
  if (deps.startup) {
    try {
      void deps.startup().catch(() => undefined);
    } catch {
      /* 패키지가 아니거나 사용자가 거절했다 — 앱은 그대로 쓴다 */
    }
  }
  if (deps.switchWindow) {
    try {
      if ((await within(deps.switchWindow(), deps.switchMs ?? FINISH_SWITCH_MS)) !== TIMED_OUT) {
        return { recorded, switched: "window" };
      }
    } catch {
      /* 창 전환이 안 되면 같은 창에서 작업 화면으로 간다 */
    }
  }
  deps.goSameWindow();
  return { recorded, switched: "same_window" };
}
