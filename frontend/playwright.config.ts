import { defineConfig } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../', import.meta.url))
const baseURL = 'http://127.0.0.1:8011'

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  use: {
    baseURL,
    channel: process.env.SCOPEBRIEF_E2E_CHANNEL || undefined,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'uv run --frozen uvicorn scopebrief.app:app --host 127.0.0.1 --port 8011',
    cwd: root,
    url: baseURL + '/api/health',
    env: {
      SCOPEBRIEF_DB: join(tmpdir(), 'scopebrief-test-' + randomUUID() + '.db'),
      SCOPEBRIEF_DEMO: '1',
      SCOPEBRIEF_SECURE_COOKIE: '0',
      SCOPEBRIEF_MODEL_BASE_URL: '',
      SCOPEBRIEF_MODEL_NAME: '',
    },
    timeout: 30_000,
  },
})
