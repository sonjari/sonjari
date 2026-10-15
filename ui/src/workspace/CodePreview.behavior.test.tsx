// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { CodePreview } from "./CodePreview";

it("opens the agent's local page and clears it when the workspace changes", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const feedback = vi.fn();
  try {
    await act(async () => root.render(<CodePreview workspace="C:/first" agentUrl="http://127.0.0.1:4123/index.html" onFeedback={feedback} />));
    expect(host.querySelector("iframe")?.getAttribute("src")).toBe("http://127.0.0.1:4123/index.html");

    await act(async () => root.render(<CodePreview workspace="C:/other" onFeedback={feedback} />));
    expect(host.querySelector("iframe")).toBeNull();
    expect(host.textContent).toContain("실행 화면을 기다리고 있습니다");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
