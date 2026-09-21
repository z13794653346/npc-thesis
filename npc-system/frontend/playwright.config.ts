import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const python = process.platform === 'win32' ? '.venv-win/Scripts/python.exe' : '.venv/bin/python'

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  workers: 1,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:8000', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: {
    command: `${python} -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000`,
    cwd: root,
    url: 'http://127.0.0.1:8000/api/health',
    reuseExistingServer: false,
    env: { DEEPSEEK_API_KEY: '', NPC_DEBUG: 'false', NPC_DB_PATH: `artifacts/e2e-${process.pid}.sqlite3` },
  },
})
