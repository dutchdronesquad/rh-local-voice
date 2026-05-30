/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SERVICE_VERSION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
