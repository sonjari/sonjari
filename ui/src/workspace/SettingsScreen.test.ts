import { describe, expect, it } from "vitest";

import type { SettingRow } from "../types";
import { REASONING_OPTIONS } from "./ReasoningPicker";
import { describeSource, settingErrorText, startupLabel, THINKING_LABELS, thinkingHelp } from "./SettingsScreen";

const row = (patch: Partial<SettingRow>): SettingRow => ({
  key: "voice_enabled", group: "voice", label: "말로 시키기", kind: "bool", help: "", choices: [], min: null, max: null,
  lab: false, value: true, source: "default", live: false, restart_required: false, ...patch,
});

describe("describeSource", () => {
  it("says a saved value is waiting for a restart instead of pretending it applied", () => {
    expect(describeSource(row({ source: "user", restart_required: true }))).toContain("다시 시작하면 적용");
  });

  it("separates live and restart-only defaults", () => {
    expect(describeSource(row({ live: true }))).toBe("기본값");
    expect(describeSource(row({ live: false }))).toContain("다시 시작해야");
    expect(describeSource(row({ source: "user", live: true }))).toContain("바로 적용됨");
  });
});

describe("settingErrorText", () => {
  it("turns backend codes into sentences", () => {
    expect(settingErrorText('400 {"detail":"too_small:approval_ttl_sec"}')).toBe("허용 범위보다 작습니다.");
    expect(settingErrorText('400 {"detail":"not_allowed:control_token"}')).toContain("바꿀 수 없는");
  });
});

describe("startupLabel", () => {
  it("tells the user where to turn it back on when they disabled it in Task Manager", () => {
    expect(startupLabel("disabled_by_user")).toContain("작업 관리자");
  });
});

describe("생각 깊이 선택지", () => {
  it("shows 자동 as a choice with the same one-line help as the input chip", () => {
    expect(THINKING_LABELS.auto).toBe("자동");
    expect(thinkingHelp("auto")).toBe("보통으로 시작해 막히면 깊게 생각합니다");
    expect(thinkingHelp("auto")).toBe(REASONING_OPTIONS.find((o) => o.id === "auto")?.help);
  });

  it("keeps the three old choices and gives each its chip help", () => {
    expect(THINKING_LABELS.off).toBe("빠르게");
    expect(THINKING_LABELS.adaptive).toBe("보통");
    expect(THINKING_LABELS.always).toBe("깊게");
    expect(thinkingHelp("off")).toBe("생각 없이 바로 합니다");
    expect(thinkingHelp("adaptive")).toBe("막힌 자리에서만 생각합니다");
    expect(thinkingHelp("always")).toContain("걸음마다 생각합니다");
    expect(thinkingHelp("unknown")).toBe("");
  });
});
