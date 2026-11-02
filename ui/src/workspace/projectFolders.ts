/**
 * 프로젝트 폴더 — 코워크 · 코드 둘 다 「이 일은 이 폴더에서」를 정해 두고 오간다 (2026-10-30 대표).
 *
 * 대표: 「코워크 환경에서도 프로젝트 폴더를 지정해서 왔다갔다 하는 게 맞지 않겠나 · 클로드 코워크도 그렇게 한다」.
 * 사용자처럼 유니티 프로젝트 · 맥스 작업 폴더를 오가는 사람에게는 폴더가 곧 일의 단위다.
 *
 * - 모드마다 지금 폴더를 따로 기억한다(코드 = 저장소, 코워크 = 만든 파일이 갈 곳).
 * - 최근 폴더 목록은 둘이 같이 쓴다(최대 6개).
 * - 대화마다 그 대화에서 쓴 폴더를 기억해 그 대화로 돌아가면 그 폴더로 돌아온다.
 * 이 PC 화면에만 남는다(localStorage) — 못 읽으면 빈 값으로 그대로 돈다.
 */
import type { WorkspaceMode } from "../types";

const COWORK_FOLDER_KEY = "jarvis.cowork.folder";
const RECENT_KEY = "jarvis.folders.recent";
const BY_SESSION_KEY = "jarvis.folders.by-session";
const RECENT_MAX = 6;
const SESSIONS_MAX = 200;

type BySession = Record<string, Partial<Record<WorkspaceMode, string>>>;

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 저장 못 해도 지금 화면은 그대로 쓴다 */
  }
}

export function savedCoworkFolder(): string {
  try {
    return window.localStorage.getItem(COWORK_FOLDER_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveCoworkFolder(path: string): void {
  try {
    window.localStorage.setItem(COWORK_FOLDER_KEY, path);
  } catch {
    /* 무시 */
  }
}

export function recentFolders(): string[] {
  const rows = read<unknown>(RECENT_KEY, []);
  return Array.isArray(rows) ? rows.filter((row): row is string => typeof row === "string" && row.trim() !== "") : [];
}

/** 쓴 폴더를 최근 목록 맨 앞에 — 대소문자 · 끝 구분자만 다른 같은 폴더는 하나로. */
export function rememberRecentFolder(path: string): string[] {
  const value = path.trim();
  if (!value) return recentFolders();
  const same = (a: string) => a.replace(/[\\/]+$/, "").toLowerCase() === value.replace(/[\\/]+$/, "").toLowerCase();
  const next = [value, ...recentFolders().filter((row) => !same(row))].slice(0, RECENT_MAX);
  write(RECENT_KEY, next);
  return next;
}

export function folderForSession(sessionId: string, mode: WorkspaceMode): string {
  if (!sessionId) return "";
  const rows = read<BySession>(BY_SESSION_KEY, {});
  const value = rows && typeof rows === "object" ? rows[sessionId]?.[mode] : "";
  return typeof value === "string" ? value : "";
}

export function rememberSessionFolder(sessionId: string, mode: WorkspaceMode, path: string): void {
  const value = path.trim();
  if (!sessionId || !value) return;
  const rows = read<BySession>(BY_SESSION_KEY, {});
  const safe: BySession = rows && typeof rows === "object" ? rows : {};
  const before = safe[sessionId] ?? {};
  delete safe[sessionId];   // 다시 넣어 맨 뒤(가장 최근)로
  safe[sessionId] = { ...before, [mode]: value };
  const keys = Object.keys(safe);
  for (const old of keys.slice(0, Math.max(0, keys.length - SESSIONS_MAX))) delete safe[old];
  write(BY_SESSION_KEY, safe);
}
