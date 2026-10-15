// @vitest-environment jsdom
// 구글 연결을 시작할 수 없는 빌드(공개판)엔 구글을 진열하지 않는다 (2026-10-01).
// 공개판 패키지엔 OAuth 클라이언트가 없어 구글 도구가 꺼져 있는데, 서랍엔 회색 구글 카드와
// 「이 빌드에는 Google 연결 설정이 포함되지 않았습니다」, 회색 「구글」 도구 묶음이 그대로 보였다.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import type { GoogleStatus } from "../types";
import { CapabilityDrawer } from "./CapabilityDrawer";

const CAPS = {
  tools: [
    { name: "browser_open", description: "", risk_level: "L0", enabled: true, parameters: {} },
    { name: "google_gmail_search", description: "", risk_level: "L0", enabled: false, parameters: {} },
    { name: "google_drive_read", description: "", risk_level: "L0", enabled: false, parameters: {} },
  ],
  tool_count: 3,
  by_risk: { L0: 3 },
  recipes: [],
  sites: [],
};

async function mount(google: Partial<GoogleStatus> | null, connected = false) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const client = { getCapabilities: vi.fn(async () => CAPS) } as unknown as JarvisClient;
  await act(async () => root.render(
    <CapabilityDrawer client={client} open onClose={() => {}} connected={connected}
      google={google as GoogleStatus | null} googleBusy={false} onConnectGoogle={() => {}} />,
  ));
  await act(async () => { await Promise.resolve(); });
  return { host, root };
}

it("a build that cannot start Google shows no Google card, no Google tools and no empty 연결 box", async () => {
  const { host, root } = await mount({ enabled: true, configured: false, connected: false });
  try {
    expect(host.textContent).toContain("browser_open");
    expect(host.textContent).not.toContain("구글 · Drive");
    expect(host.textContent).not.toContain("이 빌드에는 Google 연결 설정이 포함되지 않았습니다");
    expect(host.textContent).not.toContain("google_gmail_search");
    expect(host.querySelector(".capability-group.connections")).toBeNull();
  } finally {
    await act(async () => root.unmount());
  }
});

it("a build that can start Google still shows the card and the tools", async () => {
  const { host, root } = await mount({ enabled: true, configured: true, connected: false });
  try {
    expect(host.textContent).toContain("구글 · Drive");
    expect(host.textContent).toContain("google_gmail_search");
  } finally {
    await act(async () => root.unmount());
  }
});

it("someone already connected keeps seeing it", async () => {
  const { host, root } = await mount({ enabled: true, configured: false, connected: true, email: "a@b.c" });
  try {
    expect(host.textContent).toContain("구글 · Drive");
    expect(host.textContent).toContain("google_drive_read");
  } finally {
    await act(async () => root.unmount());
  }
});

it("the camera connection keeps the 연결 box even without Google", async () => {
  const { host, root } = await mount({ enabled: true, configured: false, connected: false }, true);
  try {
    expect(host.querySelector(".capability-group.connections")).not.toBeNull();
    expect(host.textContent).not.toContain("구글 · Drive");
  } finally {
    await act(async () => root.unmount());
  }
});
