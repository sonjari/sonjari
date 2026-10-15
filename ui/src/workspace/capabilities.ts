/**
 * 할 수 있는 일의 **정리** — 화면 없이 검사할 수 있게 여기 모은다 (R5).
 *
 * 도구 102개와 사이트 레시피와 아는 사이트가 전부 코드 안에만 있었다.
 * **쓸 수 있다는 걸 모르면 없는 기능과 같다.**
 *
 * 여기서 하는 일은 두 가지다. 102개를 사람이 훑을 수 있는 묶음으로 나누는 것과,
 * 위험 등급을 **숫자가 아니라 뜻**으로 말하는 것(L2 는 "되돌릴 수 없음"이다).
 */
import { t } from "../i18n";
import type { CapabilityTool } from "../types";
import { userLabel } from "./userLabel";

/**
 * 도구 이름의 앞머리 → 사람이 쓰는 말.
 *
 * 순서가 곧 화면 순서다. 자주 쓰는 것부터 위로 온다.
 * ★ 새 도구 무리를 만들면 여기에 넣어라. 안 넣으면 "그 밖에"로 흘러가고,
 *   그 묶음이 커질수록 목록은 다시 못 읽는 것이 된다.
 */
export const GROUPS: Array<{ key: string; label: string; prefixes: string[] }> = [
  { key: "browser", label: t("웹 브라우저"), prefixes: ["browser"] },
  { key: "site", label: t("사이트 절차"), prefixes: ["site"] },
  { key: "google", label: t("구글 (드라이브·지메일·캘린더)"), prefixes: ["google"] },
  { key: "naver", label: t("네이버"), prefixes: ["naver"] },
  { key: "inhouse", label: t("우리 데이터"), prefixes: ["inhouse", "admission", "student", "qb"] },
  { key: "computer", label: t("이 PC"), prefixes: ["windows", "local", "system", "gpu"] },
  { key: "camera", label: t("카메라 · 사람"), prefixes: ["camera", "person", "face", "vision", "gimbal", "osmo"] },
  { key: "ui", label: t("화면 보고 판단"), prefixes: ["ui"] },
  { key: "schedule", label: t("예약 · 되돌리기"), prefixes: ["schedule", "undo", "friction"] },
  { key: "plopfit", label: t("플롭핏"), prefixes: ["plopfit"] },
];

const PREFIX_TO_GROUP = new Map<string, string>(
  GROUPS.flatMap((group) => group.prefixes.map((prefix) => [prefix, group.key] as const)),
);

export function groupKeyOf(tool: CapabilityTool): string {
  return PREFIX_TO_GROUP.get(tool.name.split("_")[0] ?? "") ?? "other";
}

export interface CapabilityGroup {
  key: string;
  label: string;
  tools: CapabilityTool[];
}

/**
 * 묶음으로 나눈다. **빈 묶음은 안 그린다** — 있지도 않은 능력을 진열하면
 * 목록 전체가 못 미더워진다.
 *
 * `risk` 를 주면 그 등급만 남긴다. 등급으로 거를 수 있어야 "되돌릴 수 없는 것이
 * 정확히 무엇인가"를 한눈에 볼 수 있고, 그게 이 화면에서 제일 중요한 질문이다.
 */
export function groupTools(tools: CapabilityTool[], risk = ""): CapabilityGroup[] {
  const kept = risk ? tools.filter((tool) => tool.risk_level === risk) : tools;
  const buckets = new Map<string, CapabilityTool[]>();
  for (const tool of kept) {
    const key = groupKeyOf(tool);
    (buckets.get(key) ?? buckets.set(key, []).get(key)!).push(tool);
  }
  const ordered: CapabilityGroup[] = [];
  for (const group of GROUPS) {
    const rows = buckets.get(group.key);
    if (rows?.length) ordered.push({ key: group.key, label: group.label, tools: sortByName(rows) });
  }
  const rest = buckets.get("other");
  if (rest?.length) ordered.push({ key: "other", label: t("그 밖에"), tools: sortByName(rest) });
  return ordered;
}

function sortByName(tools: CapabilityTool[]): CapabilityTool[] {
  return [...tools].sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * 위험 등급의 **뜻**. 숫자만 보여 주면 아무 말도 안 한 것이다.
 *
 * P3 색 규칙 그대로: L2 는 되돌릴 수 없으므로 빨강, L1 은 무채(조작은 되돌릴 수
 * 있다), L0 은 무채. 여기서 L1 을 주황으로 칠하면 안 된다 — 주황은 "사람이 눌러야
 * 움직인다"는 뜻이고, L1 은 자비스가 그냥 한다.
 */
export const RISK_ORDER = ["L0", "L1", "L2"] as const;

export const RISK_MEANING: Record<string, { label: string; detail: string; tone: "mute" | "fail" }> = {
  L0: { label: t("읽기만"), detail: t("보기만 하고 아무것도 바꾸지 않습니다"), tone: "mute" },
  L1: { label: t("조작"), detail: t("바꾸지만 되돌릴 수 있습니다"), tone: "mute" },
  L2: { label: t("되돌릴 수 없음"), detail: t("실행 전에 {0} 승인을 받습니다", userLabel()), tone: "fail" },
  L3: { label: t("되돌릴 수 없음"), detail: t("실행 전에 {0} 승인을 받습니다", userLabel()), tone: "fail" },
  L4: { label: t("되돌릴 수 없음"), detail: t("실행 전에 {0} 승인을 받습니다", userLabel()), tone: "fail" },
};

export function riskMeaning(level: string) {
  return RISK_MEANING[level] ?? { label: level, detail: "", tone: "mute" as const };
}

/** 꺼져 있는 도구는 목록에 있어도 쓸 수 없다. 그 사실을 숨기지 않는다. */
export function disabledCount(tools: CapabilityTool[]): number {
  return tools.filter((tool) => !tool.enabled).length;
}
