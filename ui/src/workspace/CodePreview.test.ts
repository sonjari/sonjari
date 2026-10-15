import { describe, expect, it } from "vitest";
import { localPreviewUrl } from "./CodePreview";

describe("localPreviewUrl", () => {
  it("opens only local HTTP development servers", () => {
    expect(localPreviewUrl(" http://localhost:5173/ ")).toBe("http://localhost:5173/");
    expect(localPreviewUrl("http://127.0.0.1:3000/app")).toBe("http://127.0.0.1:3000/app");
    expect(localPreviewUrl("https://example.com")).toBeNull();
    expect(localPreviewUrl("http://localhost.example.com:5173")).toBeNull();
    expect(localPreviewUrl("file:///C:/secret.txt")).toBeNull();
    expect(localPreviewUrl("http://user:pass@localhost:5173")).toBeNull();
  });
});
