import { expect, test } from '@playwright/test'

const username = process.env.E2E_ADMIN_USERNAME || 'codex-e2e-admin'
const password = process.env.E2E_ADMIN_PASSWORD || '123456'

async function ensureAdminUser(request) {
  let login = await request.post('/api/auth/login', {
    data: { username, password },
  })
  if (login.ok()) return

  await request.post('/api/auth/users', {
    data: { username, password, role: 'admin' },
  }).catch(() => null)
  await request.post('/api/auth/bootstrap', {
    data: { username, password, role: 'admin' },
  }).catch(() => null)

  login = await request.post('/api/auth/login', {
    data: { username, password },
  })
  expect(login.ok()).toBeTruthy()
}

async function fillCredentials(page) {
  await page.getByPlaceholder('admin').fill(username)
  await page.locator('input[type="password"]').fill(password)
}

async function loginOrBootstrap(page, request) {
  await ensureAdminUser(request)
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()

  await fillCredentials(page)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/business-tasks/, { timeout: 10_000 })
}

const mockNodes = [
  {
    id: 'compute-1-id',
    hostname: 'compute-1',
    node_kind: 'worker',
    is_schedulable: true,
    gpu_count: 1,
    gpu_model: 'NVIDIA TITAN Xp',
    gpu_memory_mb: 12288,
    cpu_cores: 24,
    cpu_model: 'Intel Xeon E5',
    memory_mb: 65536,
  },
  {
    id: 'h1-id',
    hostname: 'h1',
    node_kind: 'terminal',
    is_schedulable: true,
  },
  {
    id: 'h2-id',
    hostname: 'h2',
    node_kind: 'terminal',
    is_schedulable: true,
  },
]

const mockSystemSettings = {
  benchmark_routing_mode: 'internal_auto',
  expert_mode: true,
  show_internal_controls: false,
  show_routing_dag_json: false,
  benchmark_execution_defaults: {
    default_task_count: 30,
    max_parallel: 2,
    per_compute_slot_limit: 1,
  },
}

function installAdminSession(page) {
  return page.addInitScript(() => {
    window.localStorage.setItem('access_token', 'fake-admin-token')
    window.localStorage.setItem('role', 'admin')
    window.localStorage.setItem('username', 'admin')
  })
}

async function mockAdminApi(page) {
  await page.route('**/api/auth/me', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'admin', username: 'admin', role: 'admin' }),
  }))
  await page.route('**/api/admin/system-settings', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(mockSystemSettings),
  }))
  await page.route('**/api/nodes**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(mockNodes),
  }))
}

async function mockBenchmarkReadApis(page) {
  await page.route('**/api/baselines**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        node_id: 'compute-1-id',
        task_type: 'high_throughput_matmul',
        metric_key: 'effective_gflops',
        baseline_value: 5500,
        unit: 'GFLOPS',
        stable: true,
        raw_values: [5480, 5500, 5520],
        diagnostics: { actual_backends: ['cupy_gpu'] },
      },
    ]),
  }))
  await page.route('**/api/orders/benchmark/recalculate', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ succeeded: [], failed: {} }),
  }))
  await page.route('**/api/business-tasks/summary**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ items: [] }),
  }))
}

async function mockBusinessTaskHubApis(page) {
  await page.route('**/api/business-tasks**', async route => {
    const url = new URL(route.request().url())
    const isBenchmark = url.searchParams.get('is_benchmark') === 'true'
    const items = isBenchmark
      ? [
          {
            order_id: 'order-benchmark-1',
            task_type: 'high_throughput_matmul',
            order_status: 'completed',
            deployment_status: 'completed',
            benchmark_run_id: 'high_throughput_matmul-e2e',
            is_benchmark: true,
            created_at: new Date().toISOString(),
          },
        ]
      : [
          {
            order_id: 'order-normal-1',
            owner_username: 'admin',
            task_type: 'high_throughput_matmul',
            modality: 'high_throughput',
            business_priority: 1,
            routing_policy: 'high_throughput',
            order_status: 'completed',
            deployment_status: 'completed',
            business_success: true,
            metric_key: 'effective_gflops',
            actual_value: 5520,
            target_value: 5000,
            unit: 'GFLOPS',
            is_benchmark: false,
            created_at: new Date().toISOString(),
          },
        ]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items, total: items.length }),
    })
  })
}

test('admin can inspect the business task hub', async ({ page }, testInfo) => {
  await installAdminSession(page)
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (text) => {
          window.__lastCopiedOrderId = text
        },
      },
    })
  })
  await mockAdminApi(page)
  await mockBusinessTaskHubApis(page)

  await page.goto('/business-tasks')

  await expect(page.getByRole('heading', { name: '业务工单中心' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '工单列表' })).toBeVisible()
  await expect(page.getByRole('button', { name: '应用筛选' })).toBeVisible()
  await expect(page.getByText('清理实例会释放远端容器和实例记录')).toBeVisible()
  await page.getByRole('button', { name: '复制' }).first().click()
  await expect.poll(() => page.evaluate(() => window.__lastCopiedOrderId)).toBe('order-normal-1')

  await page.screenshot({
    path: testInfo.outputPath('business-tasks-hub.png'),
    fullPage: true,
  })
})

test('user can copy order id from my orders list and detail toolbar', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('access_token', 'fake-user-token')
    window.localStorage.setItem('role', 'user')
    window.localStorage.setItem('username', 'demo-user')
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (text) => {
          window.__lastCopiedOrderId = text
        },
      },
    })
  })
  await page.route('**/api/auth/me', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'user-1', username: 'demo-user', role: 'user' }),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [
        {
          id: 'user-order-copy-1',
          task_type: 'high_throughput_matmul',
          status: 'completed',
          routing_status: 'completed',
          deployment_status: 'stopped',
          created_at: new Date().toISOString(),
        },
      ],
    }),
  }))
  await page.route('**/api/orders/user-order-copy-1', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: 'user-order-copy-1',
      task_type: 'high_throughput_matmul',
      status: 'completed',
      routing_status: 'completed',
      business_task: {
        task_type: 'high_throughput_matmul',
        data_profile: { matrix_size: 1024, batch_count: 50 },
        business_objective: { metric_key: 'effective_gflops', operator: '>=', target_value: 5000, unit: 'GFLOPS' },
      },
      node_placements: [],
      created_at: new Date().toISOString(),
    }),
  }))

  await page.goto('/my-orders')
  await expect(page.getByText('工单ID：user-order-c')).toBeVisible()
  await page.getByRole('button', { name: '复制' }).first().click()
  await expect.poll(() => page.evaluate(() => window.__lastCopiedOrderId)).toBe('user-order-copy-1')
  await page.getByText('矩阵乘法计算任务').click()
  await expect(page.getByText('任务工单详情')).toBeVisible()
  await page.getByRole('button', { name: '复制工单ID' }).click()
  await expect.poll(() => page.evaluate(() => window.__lastCopiedOrderId)).toBe('user-order-copy-1')
})

test('admin sidebar navigation responds from benchmark page', async ({ page }, testInfo) => {
  await installAdminSession(page)
  await mockAdminApi(page)
  await mockBenchmarkReadApis(page)

  await page.goto('/benchmark', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('1 × NVIDIA TITAN Xp')).toBeVisible()
  await expect(page.getByText('执行引擎：cupy_gpu')).toBeVisible()
  await expect(page.getByText('未记录设备')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '拓扑节点' })).toBeVisible()

  await page.getByRole('button', { name: '拓扑节点' }).click()
  await page.waitForURL(/\/nodes/, { timeout: 10_000 })
  await expect(page.getByRole('heading', { name: '拓扑节点' })).toBeVisible()

  await page.getByRole('button', { name: '系统设置' }).click()
  await page.waitForURL(/\/settings/, { timeout: 10_000 })
  await expect(page.getByRole('heading', { name: '运行配置与系统参数' })).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('admin-sidebar-navigation.png'),
    fullPage: true,
  })
})

test('benchmark running state survives sidebar navigation', async ({ page }, testInfo) => {
  await installAdminSession(page)
  await page.addInitScript(() => {
    window.localStorage.setItem('access_token', 'fake-admin-token')
    window.localStorage.setItem('role', 'admin')
    window.localStorage.setItem('username', 'admin')
    window.localStorage.setItem('manage-deploy:benchmark-run-id', 'high_throughput_matmul-e2e-running')
    window.localStorage.setItem('manage-deploy:benchmark-run-session', JSON.stringify({
      taskType: 'high_throughput_matmul',
      benchmarkRunId: 'high_throughput_matmul-e2e-running',
      phase: 'running',
      updatedAt: new Date().toISOString(),
    }))
  })
  await mockAdminApi(page)
  await page.route('**/api/baselines**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        node_id: 'compute-1-id',
        task_type: 'high_throughput_matmul',
        metric_key: 'effective_gflops',
        baseline_value: 5500,
        unit: 'GFLOPS',
        stable: true,
        raw_values: [5480, 5500, 5520],
      },
    ]),
  }))
  await page.route('**/api/orders/benchmark/recalculate', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ succeeded: [], failed: {} }),
  }))
  await page.route('**/api/business-tasks/summary**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        task_type: 'high_throughput_matmul',
        count: 30,
        evaluated_count: 3,
        success_count: 3,
        business_success_rate: 1,
      },
    ]),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [
        {
          id: 'order-running-1',
          task_type: 'high_throughput_matmul',
          status: 'materialized',
          routing_status: 'completed',
          deployment_status: 'running',
          materialized_instance_id: 'instance-running-1',
          runtime_config: {
            benchmark: { run_id: 'high_throughput_matmul-e2e-running' },
            business_task: { modality: '高通量计算模态' },
            routing_result: { placements: [{ task_node_id: 'compute', topology_node_id: 'compute-1', gpu_device: '0' }] },
          },
          created_at: new Date().toISOString(),
        },
      ],
    }),
  }))
  await page.route('**/api/orders/benchmark/managed-run/status**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      phase: 'running',
      message: '测评运行中：已评估 3/30，本轮启动 0 个，运行中 1 个，待启动 26 个，已释放实例 0 个。',
      running: true,
      progress: {
        total: 30,
        evaluated: 3,
        success: 3,
        active: 1,
        started: 0,
        cleaned: 0,
        pending_to_start: 26,
      },
    }),
  }))

  await page.goto('/benchmark')
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()
  await expect(page.locator('.step-card').getByRole('button', { name: '测评运行中' })).toBeDisabled()
  await expect(page.getByText('1 × NVIDIA TITAN Xp')).toBeVisible()

  await page.getByRole('button', { name: '拓扑节点' }).click()
  await page.waitForURL(/\/nodes/, { timeout: 10_000 })
  await page.getByRole('button', { name: '业务测评' }).click()
  await page.waitForURL(/\/benchmark/, { timeout: 10_000 })
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()
  await expect(page.locator('.step-card').getByRole('button', { name: '测评运行中' })).toBeDisabled()
  await expect(page.getByText(/当前测评轮次正在执行|测评运行中：已评估 3\/30/)).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('benchmark-running-state-survives-navigation.png'),
    fullPage: true,
  })
})

test('benchmark full-flow click locks immediately before batch API returns', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('access_token', 'fake-admin-token')
    window.localStorage.setItem('role', 'admin')
    window.localStorage.setItem('username', 'admin')
  })
  await page.route('**/api/auth/me', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'admin', username: 'admin', role: 'admin' }),
  }))
  await page.route('**/api/admin/system-settings', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      benchmark_routing_mode: 'internal_auto',
      expert_mode: true,
      show_internal_controls: false,
      show_routing_dag_json: false,
      benchmark_execution_defaults: {
        default_task_count: 30,
        max_parallel: 2,
        per_compute_slot_limit: 1,
      },
    }),
  }))
  await page.route('**/api/nodes**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        id: 'compute-1-id',
        hostname: 'compute-1',
        node_kind: 'worker',
        is_schedulable: true,
        gpu_count: 1,
        gpu_model: 'NVIDIA TITAN Xp',
      },
      {
        id: 'h1-id',
        hostname: 'h1',
        node_kind: 'terminal',
        is_schedulable: true,
      },
      {
        id: 'h2-id',
        hostname: 'h2',
        node_kind: 'terminal',
        is_schedulable: true,
      },
    ]),
  }))
  await page.route('**/api/baselines**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        node_id: 'compute-1-id',
        task_type: 'high_throughput_matmul',
        metric_key: 'effective_gflops',
        baseline_value: 5500,
        unit: 'GFLOPS',
        stable: true,
        raw_values: [5480, 5500, 5520],
      },
    ]),
  }))
  await page.route('**/api/orders/benchmark/recalculate', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ succeeded: [], failed: {} }),
  }))
  await page.route('**/api/business-tasks/summary**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ items: [] }),
  }))
  await page.route('**/api/orders/batch-benchmark', async () => {
    await new Promise(() => {})
  })

  await page.goto('/benchmark')
  await page.getByRole('button', { name: '开始完整测试流程' }).click()
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()

  await page.getByRole('button', { name: '拓扑节点' }).click()
  await page.waitForURL(/\/nodes/, { timeout: 10_000 })
  await page.getByRole('button', { name: '业务测评' }).click()
  await page.waitForURL(/\/benchmark/, { timeout: 10_000 })
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()

  const session = await page.evaluate(() => JSON.parse(window.localStorage.getItem('manage-deploy:benchmark-run-session')))
  expect(session.taskType).toBe('high_throughput_matmul')
  expect(session.phase).toBe('creating')
  expect(session.benchmarkRunId).toContain('high_throughput_matmul-')
})

test('benchmark full-flow click locks while refreshing page data', async ({ page }) => {
  let baselineRequests = 0
  await page.addInitScript(() => {
    window.localStorage.setItem('access_token', 'fake-admin-token')
    window.localStorage.setItem('role', 'admin')
    window.localStorage.setItem('username', 'admin')
  })
  await page.route('**/api/auth/me', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'admin', username: 'admin', role: 'admin' }),
  }))
  await page.route('**/api/admin/system-settings', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      benchmark_routing_mode: 'internal_auto',
      expert_mode: true,
      show_internal_controls: false,
      show_routing_dag_json: false,
      benchmark_execution_defaults: {
        default_task_count: 30,
        max_parallel: 2,
        per_compute_slot_limit: 1,
      },
    }),
  }))
  await page.route('**/api/nodes**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        id: 'compute-1-id',
        hostname: 'compute-1',
        node_kind: 'worker',
        is_schedulable: true,
        gpu_count: 1,
        gpu_model: 'NVIDIA TITAN Xp',
      },
      {
        id: 'h1-id',
        hostname: 'h1',
        node_kind: 'terminal',
        is_schedulable: true,
      },
      {
        id: 'h2-id',
        hostname: 'h2',
        node_kind: 'terminal',
        is_schedulable: true,
      },
    ]),
  }))
  await page.route('**/api/baselines**', async route => {
    baselineRequests += 1
    if (baselineRequests > 1) {
      await new Promise(() => {})
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          node_id: 'compute-1-id',
          task_type: 'high_throughput_matmul',
          metric_key: 'effective_gflops',
          baseline_value: 5500,
          unit: 'GFLOPS',
          stable: true,
          raw_values: [5480, 5500, 5520],
        },
      ]),
    })
  })
  await page.route('**/api/orders/benchmark/recalculate', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ succeeded: [], failed: {} }),
  }))
  await page.route('**/api/business-tasks/summary**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ items: [] }),
  }))

  await page.goto('/benchmark')
  await page.getByRole('button', { name: '开始完整测试流程' }).click()
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()

  await page.getByRole('button', { name: '拓扑节点' }).click()
  await page.waitForURL(/\/nodes/, { timeout: 10_000 })
  await page.getByRole('button', { name: '业务测评' }).click()
  await page.waitForURL(/\/benchmark/, { timeout: 10_000 })
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()

  const session = await page.evaluate(() => JSON.parse(window.localStorage.getItem('manage-deploy:benchmark-run-session')))
  expect(session.phase).toBe('creating')
})

test('benchmark batch baseline lock survives sidebar navigation', async ({ page }) => {
  let batchBaselineRequests = 0
  await installAdminSession(page)
  await mockAdminApi(page)
  await page.route('**/api/baselines**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        node_id: 'compute-1-id',
        task_type: 'high_throughput_matmul',
        metric_key: 'effective_gflops',
        baseline_value: 5500,
        unit: 'GFLOPS',
        stable: true,
        raw_values: [5480, 5500, 5520],
      },
    ]),
  }))
  await page.route('**/api/baselines/batch-run', async () => {
    batchBaselineRequests += 1
    await new Promise(() => {})
  })
  await page.route('**/api/orders/benchmark/recalculate', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ succeeded: [], failed: {} }),
  }))
  await page.route('**/api/business-tasks/summary**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ items: [] }),
  }))

  await page.goto('/benchmark')
  await page.getByRole('button', { name: '批量测试计算节点' }).click()
  await expect(page.getByRole('button', { name: /基线测试中|批量测试计算节点/ })).toBeDisabled()

  await page.getByRole('button', { name: '拓扑节点' }).click()
  await page.waitForURL(/\/nodes/, { timeout: 10_000 })
  await page.getByRole('button', { name: '业务测评' }).click()
  await page.waitForURL(/\/benchmark/, { timeout: 10_000 })
  await expect(page.getByRole('button', { name: /基线测试中|批量测试计算节点/ })).toBeDisabled()
  await expect.poll(() => batchBaselineRequests).toBe(1)
  const lock = await page.evaluate(() => JSON.parse(window.localStorage.getItem('manage-deploy:benchmark-baseline-run-lock')))
  expect(lock.taskType).toBe('high_throughput_matmul')
  expect(lock.scope).toBe('batch')
})

test('benchmark full-flow survives transient status polling failure and unlocks on completion', async ({ page }) => {
  let createdRunId = ''
  let statusRequests = 0
  let completed = false
  await installAdminSession(page)
  await mockAdminApi(page)
  await page.route('**/api/baselines**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        node_id: 'compute-1-id',
        task_type: 'high_throughput_matmul',
        metric_key: 'effective_gflops',
        baseline_value: 5500,
        unit: 'GFLOPS',
        stable: true,
        raw_values: [5480, 5500, 5520],
      },
    ]),
  }))
  await page.route('**/api/orders/batch-benchmark', async route => {
    const payload = route.request().postDataJSON()
    createdRunId = payload.benchmark_run_id
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ benchmark_run_id: createdRunId, created: 30, failed: [] }),
    })
  })
  await page.route('**/api/orders/batch-auto-route', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ routed: 30, failed: [] }),
  }))
  await page.route('**/api/orders/benchmark/managed-run', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      phase: 'running',
      message: '已启动后台测评推进，页面会自动刷新进度。',
      running: true,
      progress: { total: 30, evaluated: 0, success: 0, active: 1, started: 1, cleaned: 0, pending_to_start: 29 },
    }),
  }))
  await page.route('**/api/orders/benchmark/managed-run/status**', async route => {
    statusRequests += 1
    if (statusRequests === 2) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'temporary status backend unavailable' }),
      })
      return
    }
    if (statusRequests >= 3) completed = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(completed
        ? {
            phase: 'completed',
            message: '本轮 30 个测评任务已全部完成评估。',
            running: false,
            progress: { total: 30, evaluated: 30, success: 30, active: 0, started: 0, cleaned: 30, pending_to_start: 0 },
          }
        : {
            phase: 'running',
            message: '测评运行中：已评估 0/30，本轮启动 1 个，运行中 1 个，待启动 29 个，已释放实例 0 个。',
            running: true,
            progress: { total: 30, evaluated: 0, success: 0, active: 1, started: 1, cleaned: 0, pending_to_start: 29 },
          }),
    })
  })
  await page.route('**/api/orders/benchmark/recalculate', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ succeeded: completed ? Array.from({ length: 30 }, (_, i) => `order-${i}`) : [], failed: {} }),
  }))
  await page.route('**/api/business-tasks/summary**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(createdRunId
      ? [
          {
            task_type: 'high_throughput_matmul',
            count: 30,
            evaluated_count: completed ? 30 : 0,
            success_count: completed ? 30 : 0,
            business_success_rate: completed ? 1 : null,
            acceptance_passed: completed,
            sample_count_passed: completed,
            required_evaluated_count: 30,
            required_success_rate: 0.9,
          },
        ]
      : []),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: createdRunId
        ? [
            {
              id: 'order-transient-1',
              task_type: 'high_throughput_matmul',
              status: completed ? 'completed' : 'materialized',
              routing_status: 'completed',
              deployment_status: completed ? 'completed' : 'running',
              business_success: completed ? true : null,
              actual_value: completed ? 5520 : null,
              target_value: 5000,
              unit: 'GFLOPS',
              materialized_instance_id: completed ? null : 'instance-transient-1',
              runtime_config: {
                benchmark: { run_id: createdRunId },
                business_task: { modality: '高通量计算模态' },
                routing_result: { placements: [{ task_node_id: 'compute', topology_node_id: 'compute-1', gpu_device: '0' }] },
              },
              created_at: new Date().toISOString(),
            },
          ]
        : [],
    }),
  }))

  await page.goto('/benchmark')
  await page.getByRole('button', { name: '开始完整测试流程' }).click()
  await expect(page.getByText('100.0%')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('目标：≥ 90% 且 ≥ 30 个已评估任务，判定通过')).toBeVisible()
  await expect(page.locator('section').getByRole('button', { name: '开始完整测试流程' })).toBeEnabled()
  await expect(page.locator('.step-card').getByRole('button', { name: '运行测评' })).toBeEnabled()
  await expect.poll(() => statusRequests).toBeGreaterThanOrEqual(3)
})

test('benchmark run button clears stale in-page runner lock and restarts backend run', async ({ page }) => {
  const staleRunId = 'high_throughput_matmul-stale-lock'
  let statusRequests = 0
  let startRequests = 0
  let completed = false

  await installAdminSession(page)
  await mockAdminApi(page)
  await page.addInitScript((runId) => {
    window.__manageDeployBenchmarkRunnerKey = `high_throughput_matmul:${runId}`
    window.localStorage.setItem('manage-deploy:benchmark-run-session', JSON.stringify({
      taskType: 'high_throughput_matmul',
      benchmarkRunId: runId,
      phase: 'running',
      updatedAt: new Date().toISOString(),
    }))
  }, staleRunId)
  await page.route('**/api/baselines**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        node_id: 'compute-1-id',
        task_type: 'high_throughput_matmul',
        metric_key: 'effective_gflops',
        baseline_value: 5500,
        unit: 'GFLOPS',
        stable: true,
        raw_values: [5480, 5500, 5520],
      },
    ]),
  }))
  await page.route('**/api/orders/batch-auto-route', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ routed: 1, failed: [] }),
  }))
  await page.route('**/api/orders/benchmark/managed-run/status**', async route => {
    statusRequests += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(completed
        ? {
            phase: 'completed',
            message: '本轮 30 个测评任务已全部完成评估。',
            running: false,
            progress: { total: 30, evaluated: 30, success: 30, active: 0, started: 0, cleaned: 30, pending_to_start: 0 },
          }
        : {
            phase: 'idle',
            message: '当前轮次没有后台测评任务。',
            running: false,
            progress: null,
          }),
    })
  })
  await page.route('**/api/orders/benchmark/managed-run', async route => {
    startRequests += 1
    completed = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        phase: 'running',
        message: '已启动后台测评推进，页面会自动刷新进度。',
        running: true,
        progress: { total: 30, evaluated: 0, success: 0, active: 1, started: 1, cleaned: 0, pending_to_start: 29 },
      }),
    })
  })
  await page.route('**/api/orders/benchmark/recalculate', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ succeeded: completed ? Array.from({ length: 30 }, (_, i) => `order-${i}`) : [], failed: {} }),
  }))
  await page.route('**/api/business-tasks/summary**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        task_type: 'high_throughput_matmul',
        count: 30,
        evaluated_count: completed ? 30 : 0,
        success_count: completed ? 30 : 0,
        business_success_rate: completed ? 1 : null,
        acceptance_passed: completed,
        sample_count_passed: completed,
        required_evaluated_count: 30,
        required_success_rate: 0.9,
      },
    ]),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [
        {
          id: 'order-stale-lock-1',
          task_type: 'high_throughput_matmul',
          status: completed ? 'completed' : 'materialized',
          routing_status: 'completed',
          deployment_status: completed ? 'completed' : 'pending',
          business_success: completed ? true : null,
          actual_value: completed ? 5520 : null,
          target_value: 5000,
          unit: 'GFLOPS',
          materialized_instance_id: completed ? null : 'instance-stale-lock-1',
          runtime_config: {
            benchmark: { run_id: staleRunId },
            business_task: { modality: '高通量计算模态' },
            routing_result: { placements: [{ task_node_id: 'compute', topology_node_id: 'compute-1', gpu_device: '0' }] },
          },
          created_at: new Date().toISOString(),
        },
      ],
    }),
  }))

  await page.goto(`/benchmark?benchmark_run_id=${staleRunId}`)
  await page.locator('.step-card').getByRole('button', { name: '运行测评' }).click()
  await expect(page.getByText('100.0%')).toBeVisible({ timeout: 15_000 })
  await expect.poll(() => statusRequests).toBeGreaterThanOrEqual(2)
  expect(startRequests).toBe(1)
})

test('optional headed matmul demo trigger is visible', async ({ page, request }, testInfo) => {
  test.skip(
    process.env.E2E_TRIGGER_MATMUL_DEMO !== '1',
    'Set E2E_TRIGGER_MATMUL_DEMO=1 to click the UI demo button.'
  )

  await loginOrBootstrap(page, request)

  await page.getByRole('button', { name: '一键演示矩阵乘法' }).click()
  await expect(
    page.getByText(/矩阵乘法示例任务|至少需要 3 个可调度拓扑节点|任务已提交|演示完成/)
  ).toBeVisible({ timeout: 300_000 })

  await page.screenshot({
    path: testInfo.outputPath('matmul-demo-trigger.png'),
    fullPage: true,
  })
})
