import { defineConfig } from '@playwright/test'

const PORT = Number(process.env.E2E_PORT ?? 8765)

export default defineConfig({
  testDir: 'e2e',
  timeout: 90_000,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${PORT}`, headless: true },
  webServer: {
    // 빌드된 대시보드를 MES 서버가 서빙한다. 포트 충돌을 피하려고 별도 설정 폴더를 쓴다.
    command: `cd .. && uv run python scripts/e2e_server.py ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/summary`,
    timeout: 60_000,
    reuseExistingServer: false,
  },
})
