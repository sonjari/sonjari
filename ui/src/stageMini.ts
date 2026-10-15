/**
 * 브라우저 무대 작은 창을 언제 띄우고 닫나 (2026-09-24).
 *
 * 바깥 AI(Claude·Codex 가 MCP 로)가 맡긴 일은 온텔릭 작업 화면이 닫혀 있어도 돈다. 그때 사람은 온텔릭이 브라우저에서 뭘 하는지
 * 볼 곳이 없었다(크롬은 화면 밖이다). 늘 떠 있는 HUD 가 이벤트를 보고, **바깥에서 맡긴 일이 브라우저를 쓰는 순간** 작은 창을 띄운다.
 * 일이 다 끝나면 6초 뒤 닫는다 — 끝난 화면을 잠깐은 볼 수 있게.
 */
import type { JarvisEvent } from "./types";

const EXTERNAL_ORIGINS = new Set(["mcp"]);
const BROWSER_TOOL = /^(browser_|site_)/;
const DONE = new Set(["job_completed", "job_failed", "job_cancelled"]);
export const CLOSE_AFTER_MS = 6_000;

export class StageMiniWatcher {
  private readonly external = new Set<string>();
  private open = false;
  private closeTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly openWindow: () => void,
    private readonly closeWindow: () => void,
  ) {}

  onEvent(event: JarvisEvent): void {
    const payload = event.payload ?? {};
    const jobId = String(payload.job_id ?? "");
    if (!jobId) return;
    if (event.event === "agent_started") {
      if (EXTERNAL_ORIGINS.has(String(payload.origin ?? ""))) this.external.add(jobId);
      return;
    }
    if (event.event === "agent_progress") {
      if (!this.external.has(jobId) || !BROWSER_TOOL.test(String(payload.tool ?? ""))) return;
      this.cancelClose();
      if (!this.open) {
        this.open = true;
        this.openWindow();
      }
      return;
    }
    if (DONE.has(event.event) && this.external.delete(jobId) && this.open && this.external.size === 0) {
      this.cancelClose();
      this.closeTimer = setTimeout(() => {
        this.closeTimer = null;
        this.open = false;
        this.closeWindow();
      }, CLOSE_AFTER_MS);
    }
  }

  private cancelClose(): void {
    if (this.closeTimer !== null) clearTimeout(this.closeTimer);
    this.closeTimer = null;
  }
}
