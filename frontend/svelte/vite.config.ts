import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { defineConfig, loadEnv } from "vite";
import { sveltekit } from "@sveltejs/kit/vite";

const appDirectory = fileURLToPath(new URL(".", import.meta.url));
const repositoryRoot = resolve(appDirectory, "../..");

export default defineConfig(({ mode }) => {
  const appEnv = loadEnv(mode, appDirectory, "VITE_");
  const repoEnv = loadEnv(mode, repositoryRoot, "");

  return {
    plugins: [sveltekit()],
    define: {
      "import.meta.env.VITE_AGENT_API_BASE_URL": JSON.stringify(
        appEnv.VITE_AGENT_API_BASE_URL ||
          repoEnv.AGENT_API_BASE_URL ||
          "http://127.0.0.1:18080",
      ),
    },
    server: { port: Number(repoEnv.FRONTEND_WEB_PORT_DEBUG ?? 8081) },
    preview: { port: Number(repoEnv.FRONTEND_WEB_PORT_RELEASE ?? 8090) },
  };
});
