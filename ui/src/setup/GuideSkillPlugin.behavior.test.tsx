// @vitest-environment jsdom
/**
 * 손자리 클로드 플러그인이 같은 가이드를 싣고 있으면 앱은 사본을 넣지 않는다 (2026-11-13 대표 「중복으로 들어가는 거 아니가」).
 * 지키는 것: 첫 실행 자동 넣기를 건너뛴다 · 왜 안 넣는지 한 줄로 말한다 · 넣기/빼기 단추를 숨긴다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { GuideSkillRow } from "./ConnectPanel";
import type { GuideSkillStatus, SetupApi } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function statusWith(plugin: string): GuideSkillStatus {
  return {
    name: "sonjari-guide",
    claude_code: { installed: false, path: "C:/u/.claude/skills/sonjari-guide/SKILL.md", available: true, foreign: false, plugin },
    zip: { exists: false, path: "" },
    notes: {},
  } as unknown as GuideSkillStatus;
}

async function mount(api: SetupApi): Promise<HTMLElement> {
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => {
    createRoot(host).render(<GuideSkillRow api={api} busy="" setBusy={() => undefined} auto />);
  });
  await act(async () => { await Promise.resolve(); });
  return host;
}

it("does not add the guide again when the Claude plugin already carries it", async () => {
  const guideSkill = vi.fn(async () => ({ ok: true }));
  const api = { guideSkillStatus: async () => statusWith("C:/u/.claude/plugins/cache/x/sonjari/0.4.44/skills/sonjari-guide/SKILL.md"),
    guideSkill } as unknown as SetupApi;
  const host = await mount(api);
  expect(guideSkill).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Claude 플러그인에 같은 가이드가 있어 따로 넣지 않습니다");
  expect((host.querySelector(".imp-row-actions") as HTMLElement).hidden).toBe(true);
});

it("still adds the guide on first run when there is no plugin", async () => {
  const guideSkill = vi.fn(async () => ({ ok: true }));
  const api = { guideSkillStatus: async () => statusWith(""), guideSkill } as unknown as SetupApi;
  await mount(api);
  expect(guideSkill).toHaveBeenCalledWith("install_claude_code");
});
