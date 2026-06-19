import { expect, test } from '@playwright/test'

const username = process.env.E2E_ADMIN_USERNAME || 'admin'
const password = process.env.E2E_ADMIN_PASSWORD || 'admin'

async function fillCredentials(page) {
  await page.getByPlaceholder('admin').fill(username)
  await page.locator('input[type="password"]').fill(password)
}

async function loginOrBootstrap(page) {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()

  await fillCredentials(page)
  await page.getByRole('button', { name: '登录' }).click()

  try {
    await page.waitForURL(/\/business-tasks/, { timeout: 8_000 })
    return
  } catch {
    // Fresh local databases may not have an admin user yet.
  }

  await fillCredentials(page)
  await page.getByRole('button', { name: '初始化管理员' }).click()
  await expect(page.getByText(/管理员已初始化|Users already exist|已经存在/)).toBeVisible({
    timeout: 10_000,
  })

  await fillCredentials(page)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/business-tasks/, { timeout: 10_000 })
}

test('admin can inspect the business task hub', async ({ page }, testInfo) => {
  await loginOrBootstrap(page)

  await expect(page.getByRole('heading', { name: '业务工单中心' })).toBeVisible()
  await expect(page.getByRole('button', { name: '一键演示矩阵乘法' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '工单列表' })).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('business-tasks-hub.png'),
    fullPage: true,
  })
})

test('admin sidebar navigation responds from benchmark page', async ({ page }, testInfo) => {
  await loginOrBootstrap(page)

  await page.goto('/benchmark')
  await expect(page.getByRole('button', { name: '拓扑节点' })).toBeVisible()

  await page.getByRole('button', { name: '拓扑节点' }).click()
  await page.waitForURL(/\/nodes/, { timeout: 10_000 })
  await expect(page.getByRole('heading', { name: /节点|拓扑/ })).toBeVisible()

  await page.getByRole('button', { name: '系统设置' }).click()
  await page.waitForURL(/\/settings/, { timeout: 10_000 })
  await expect(page.getByRole('heading', { name: '运行配置与系统参数' })).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('admin-sidebar-navigation.png'),
    fullPage: true,
  })
})

test('optional headed matmul demo trigger is visible', async ({ page }, testInfo) => {
  test.skip(
    process.env.E2E_TRIGGER_MATMUL_DEMO !== '1',
    'Set E2E_TRIGGER_MATMUL_DEMO=1 to click the UI demo button.'
  )

  await loginOrBootstrap(page)

  await page.getByRole('button', { name: '一键演示矩阵乘法' }).click()
  await expect(
    page.getByText(/矩阵乘法示例任务|至少需要 3 个可调度拓扑节点|任务已提交|演示完成/)
  ).toBeVisible({ timeout: 300_000 })

  await page.screenshot({
    path: testInfo.outputPath('matmul-demo-trigger.png'),
    fullPage: true,
  })
})
