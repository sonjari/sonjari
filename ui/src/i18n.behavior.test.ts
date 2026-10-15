// 영어판 1단계 (2026-10-02) — 사전이 코드를 따라오는지, 영어로 바꾸면 실제로 영어가 나오는지.
import ts from "typescript";
import { afterEach, describe, expect, it } from "vitest";
import en from "./i18n/en.json";
import { lang, setLangForTest, t } from "./i18n";

// 소스는 vite 로 읽는다 — 화면 쪽 타입 설정에는 Node 타입(fs·path)이 없다.
const SOURCES = import.meta.glob(["./**/*.ts", "./**/*.tsx", "!./**/*.test.ts", "!./**/*.test.tsx"], {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;

function usedKeys(): Map<string, string> {
  const found = new Map<string, string>();
  for (const [file, text] of Object.entries(SOURCES)) {
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const visit = (node: ts.Node) => {
      if (ts.isCallExpression(node) && node.expression.getText(sf) === "t" && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) {
        found.set(node.arguments[0].text, file);
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return found;
}

afterEach(() => setLangForTest("ko"));

describe("화면 언어", () => {
  it("시험에서는 한국어로 시작한다(가짜 브라우저가 en-US 여도)", () => {
    expect(lang()).toBe("ko");
    expect(t("저장")).toBe("저장");
  });

  it("코드의 t(\"…\") 문장은 전부 영어 사전에 있다 — 새 문장을 넣고 번역을 빼먹으면 여기서 걸린다", () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
    const dict = en as Record<string, string>;
    const missing = [...usedKeys()].filter(([key]) => !(key in dict)).map(([key, file]) => `${file}: ${key}`);
    expect(missing).toEqual([]);
  });

  it("t(\"…{0}\", 인자) 의 인자 안 한국어도 감싸져 있다 — 1차 필터가 건너뛰어 「— 그대로 씁니다」가 영어 화면에 남았다", () => {
    const leaks: string[] = [];
    for (const [file, text] of Object.entries(SOURCES)) {
      if (file.includes("/fixtures/") || file.includes("fixtureSetupApi")) continue;
      const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
      const visit = (node: ts.Node) => {
        if (ts.isCallExpression(node) && node.expression.getText(sf) === "t") {
          node.arguments.slice(1).forEach((arg) => {
            const inner = (n: ts.Node) => {
              if ((ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) && /[가-힣]/.test(n.text)) leaks.push(`${file}: ${n.text}`);
              else if (!(ts.isCallExpression(n) && n.expression.getText(sf) === "t")) ts.forEachChild(n, inner);
            };
            inner(arg);
          });
        }
        ts.forEachChild(node, visit);
      };
      visit(sf);
    }
    expect(leaks).toEqual([]);
  });

  it("영어 사전의 자리표시({0})는 한국어와 같다", () => {
    const holes = (s: string) => (s.match(/\{\d+\}/g) ?? []).sort().join(",");
    const bad = Object.entries(en as Record<string, string>).filter(([ko, eng]) => holes(ko) !== holes(eng));
    expect(bad).toEqual([]);
  });

  it("영어로 바꾸면 사전의 영어가 나오고 자리표시가 채워진다", () => {
    setLangForTest("en");
    expect(t("화면 언어")).toBe("Display language");
    expect(t("{0}시간 뒤", 3)).toBe("in 3 h");
    expect(t("사전에 없는 문장")).toBe("사전에 없는 문장");
  });
});
