/**
 * Claude 갈래를 만들지 정한다 (2026-10-26).
 *
 * - 파일럿 시범판(앱 전체가 클로드)은 갈래가 없다 — `PilotClient` 가 그대로 돈다(깨지 않게 남겨 둠).
 * - 리허설(`?fixture=claude-hands` · 개발 빌드 전용)은 손으로 만든 흐름으로 돈다. 다른 리허설 장면에는 갈래를 안 붙인다.
 * - 앱(Tauri)에서만 진짜 갈래 — 브라우저 미리보기에는 CLI 가 없다.
 */
import { lang } from "../i18n";
import { isTauri, type JarvisClient } from "../backend";
import type { BackendBootstrap, JarvisEvent } from "../types";
import { ClaudeLane } from "./lane";
import { createTauriRunner } from "./tauriRunner";

export async function createClaudeLane(
  bootstrap: BackendBootstrap,
  emit: (event: JarvisEvent) => void,
  client: () => JarvisClient | null,
): Promise<ClaudeLane | null> {
  if (bootstrap.mode === "pilot") return null;
  if (import.meta.env.DEV) {
    const name = new URLSearchParams(window.location.search).get("fixture") ?? "";
    if (name) {
      const fixtures = await import("../fixtures/claudeHands");
      return fixtures.createFixtureLane(name, emit);
    }
  }
  if (!isTauri()) return null;
  return new ClaudeLane({ emit, runner: createTauriRunner(client), lang });
}
