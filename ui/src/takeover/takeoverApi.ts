/**
 * 이어받기 화면이 부르는 곳 — 백엔드 `/v1/takeover/*` (전략안 §44).
 *
 * 화면은 판정하지 않는다. 무엇이 멈췄는지·어디서 이어야 하는지는 백엔드가 기록과 git 에서 정한다.
 */
import { t } from "../i18n";
import type { BackendBootstrap } from "../types";

export interface TakeoverGit {
  repo: boolean;
  reason?: string;
  root?: string;
  branch?: string;
  head?: string;
  changed_count?: number;
  untracked_count?: number;
}

export interface TakeoverCard {
  tool: string;
  tool_name: string;
  session_path: string;
  title: string;
  cwd: string;
  stop_kind: "rate_limit" | "api_error" | "aborted" | "none";
  stopped_minutes_ago: number | null;
  resets_at: number | null;
  first_request: string;
  last_request: string;
  last_reply: string;
  files: string[];
  recent_commands: string[];
  open_tasks: string[];
  request_count: number;
  git: TakeoverGit;
  resumed_from_earlier_session?: boolean;
}

export type TakeoverStatus =
  | "offered"
  | "card_only"
  | "continuing"
  | "review_pending"
  | "discarded"
  | "dismissed"
  | "expired";

export interface TakeoverRecord {
  id: number;
  status: TakeoverStatus;
  branch: string;
  worktree: string;
  base_ref: string;
  job_id: string;
  card: TakeoverCard;
  result: { changed_files?: string[]; diffstat_tail?: string; summary?: string; job_status?: string };
  created_at: number;
  updated_at: number;
}

export interface AcceptResult {
  answer: string;
  kind: "card" | "started" | "missing";
  takeover_id?: number;
  job_id?: string;
}

export interface TakeoverApi {
  sessions(hours?: number): Promise<{ sessions: TakeoverCard[]; cursor_supported: boolean; note: string }>;
  list(): Promise<{ items: TakeoverRecord[] }>;
  pick(sessionPath: string): Promise<{ ok: boolean; takeover_id?: number; error?: string }>;
  accept(id: number): Promise<AcceptResult>;
  discard(id: number): Promise<{ ok: boolean; error?: string }>;
}

export function createTakeoverApi(bootstrap: BackendBootstrap): TakeoverApi {
  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    if (!bootstrap.controlToken) {
      throw new Error(t("Sonjari에 연결하지 못했습니다. 앱 백엔드를 다시 시작해 주세요."));
    }
    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    headers.set("X-JARVIS-TOKEN", bootstrap.controlToken);
    const response = await fetch(`${bootstrap.baseUrl}${path}`, { ...init, headers });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`.trim());
    return response.json() as Promise<T>;
  }
  return {
    sessions: (hours = 12) => call(`/v1/takeover/sessions?hours=${hours}`),
    list: () => call("/v1/takeover"),
    pick: (sessionPath) => call("/v1/takeover/pick", { method: "POST", body: JSON.stringify({ session_path: sessionPath }) }),
    accept: (id) => call(`/v1/takeover/${id}/accept`, { method: "POST", body: "{}" }),
    discard: (id) => call(`/v1/takeover/${id}/discard`, { method: "POST", body: "{}" }),
  };
}
