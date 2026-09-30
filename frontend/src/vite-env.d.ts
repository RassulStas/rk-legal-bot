/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API origin, e.g. https://api.example.com. Unset = same-origin (reverse proxy). */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
