/// <reference types="svelte" />
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AGENT_API_BASE_URL?: string;
  readonly VITE_AGENT_USER_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
