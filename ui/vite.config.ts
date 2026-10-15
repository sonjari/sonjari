import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command, mode }) => {
  // ★ 2026-09-27 밤: 화면 확인용 `.env.local`(시험 백엔드 주소·시험 토큰)이 `vite build` 에도 읽혀
  //   포장 앱 번들에 그대로 구워졌다(굽던 exe 를 멈추고 다시 구웠다). 배포 빌드는 토큰·주소 덮어쓰기를 받지 않는다.
  if (command === "build") {
    const env = loadEnv(mode, ".", "VITE_");
    const baked = ["VITE_JARVIS_TOKEN", "VITE_JARVIS_URL"].filter((key) => env[key]);
    if (baked.length) {
      throw new Error(`배포 빌드에 ${baked.join(", ")} 가 들어가려 한다 — ui/.env.local 등을 치우고 다시 빌드하라.`);
    }
  }
  return {
    plugins: [react()],
    clearScreen: false,
    server: {
      host: "127.0.0.1",
      port: 1420,
      strictPort: true,
    },
    envPrefix: ["VITE_", "TAURI_"],
    css: {
      // Do not inherit the workspace-level Tailwind PostCSS config.
      postcss: { plugins: [] },
    },
  };
});
