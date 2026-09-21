import { expect, test } from '@playwright/test'

// 백엔드(빌드된 대시보드 포함)를 띄워 개요 화면이 실데이터로 동작하는지 확인한다
test('개요 화면에 22개 장비와 실시간 연결이 보인다', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('ws-state')).toHaveText(/연결/, { timeout: 15_000 })
  await expect(page.getByTestId('kpi-ok')).toHaveText('22/22', { timeout: 30_000 })
  await expect(page.locator('[data-node="SAL-01"]')).toHaveAttribute('data-status', 'OK')
  await page.getByRole('link', { name: '수집현황' }).click()
  await expect(page.getByRole('cell', { name: 'SAN-01' })).toBeVisible()
})

test('버스 단선을 주입하면 토폴로지에 끊김이 표시된다', async ({ page, request }) => {
  await page.goto('/')
  await expect(page.getByTestId('kpi-ok')).toHaveText('22/22', { timeout: 30_000 })
  const r = await request.post('/api/sim/faults', { data: { target: 'M2', type: 'bus_cut', duration_s: 60 } })
  expect(r.ok()).toBeTruthy()
  await expect(page.locator('[data-node="M2"]')).toHaveAttribute('data-status', 'DOWN', { timeout: 45_000 })
  await expect(page.locator('[data-node="TC-01"]')).toHaveAttribute('data-status', 'DOWN')
  await expect(page.locator('[data-node="M1"]')).toHaveAttribute('data-status', 'OK')
  await request.delete('/api/sim/faults')
})
