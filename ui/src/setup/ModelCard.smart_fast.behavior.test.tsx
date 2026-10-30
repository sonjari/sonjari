// @vitest-environment jsdom
/**
 * 「똑똑함 · 빠름」 배지 (2026-10-28 밤 대표 결정 — 3.8 Swift 는 똑똑하다 · 3.6 2비트는 빠르다).
 *
 * 지키는 약속: 백엔드가 역할(`role`)을 줄 때만 새 배지가 붙고, 안 주면(옛 백엔드 · Swift 가 아닌 추천) 예전 배지 그대로다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it } from "vitest";
import { ModelGallery } from "./SetupWizard";
import { createFixtureSetupApi } from "./fixtureSetupApi";
import type { ModelPick } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement | null = null;
afterEach(() => {
  host?.remove();
  host = null;
});

async function render(withRoles: boolean) {
  const api = createFixtureSetupApi("3090")!;
  const view = await api.models();
  const swift = view.models.find((model) => model.family === "swift-27b")!;
  const other = view.models.find((model) => model.status === "verified" && model.family !== "swift-27b")!;
  const kinds = new Map<string, ModelPick["kind"]>([[swift.key, "verified"], [other.key, "open_alternative"]]);
  const roles = withRoles
    ? new Map<string, NonNullable<ModelPick["role"]>>([[swift.key, "smart"], [other.key, "fast"]])
    : undefined;
  host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  act(() => root.render(
    <ModelGallery plain models={[swift, other]} pickKinds={kinds} pickRoles={roles} usable={23.5} asked pulse=""
      onPulseEnd={() => {}} picked={null} onPick={() => {}} />,
  ));
  return [...host.querySelectorAll(".model-badge")].map((badge) => badge.textContent);
}

it("역할을 받으면 「똑똑함」 · 「빠름」 배지", async () => {
  expect(await render(true)).toEqual(["Sonjari 추천 · 똑똑함", "빠름"]);
});

it("역할이 없으면 예전 배지 그대로", async () => {
  expect(await render(false)).toEqual(["Sonjari 추천 · 실측", "조건 없는 대안"]);
});
