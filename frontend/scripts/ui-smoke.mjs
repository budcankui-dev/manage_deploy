import { chromium } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'

const baseUrl = process.env.UI_SMOKE_BASE_URL || process.env.FRONTEND_BASE_URL || 'http://127.0.0.1:5173'
const outputDir = process.env.UI_SMOKE_OUTPUT_DIR || path.resolve('output/ui-smoke')
const adminUsername = process.env.E2E_ADMIN_USERNAME || 'admin'
const adminPassword = process.env.E2E_ADMIN_PASSWORD || 'admin'
const userUsername = process.env.E2E_USER_USERNAME || `ui-smoke-${Date.now().toString(36)}`
const userPassword = process.env.E2E_USER_PASSWORD || '123456'
const viewports = [
  { width: 1440, height: 900, name: '1440x900' },
  { width: 1920, height: 1080, name: '1920x1080' },
]

const pages = [
  { path: '/intent-chat', role: 'user', waitFor: 'text=智能解析服务' },
  { path: '/business-tasks', role: 'admin', waitFor: 'text=业务工单中心' },
  { path: '/benchmark', role: 'admin', waitFor: 'text=业务测评' },
  { path: '/nodes', role: 'admin', waitFor: 'text=拓扑节点' },
  { path: '/templates', role: 'admin', waitFor: 'text=任务模板' },
  { path: '/settings', role: 'admin', waitFor: 'text=系统设置' },
  { path: '/intent-evaluation', role: 'admin', waitFor: 'text=意图参数解析准确率' },
]

function absoluteUrl(routePath) {
  return new URL(routePath, baseUrl).toString()
}

function apiUrl(routePath) {
  return new URL(`/api${routePath}`, baseUrl).toString()
}

function safeName(value) {
  return value.replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-|-$/g, '')
}

async function login(page, role) {
  const username = role === 'admin' ? adminUsername : userUsername
  const password = role === 'admin' ? adminPassword : userPassword
  const postJson = async (routePath, data) => fetch(apiUrl(routePath), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  const loginPayload = { username, password }
  let response = await postJson('/auth/login', loginPayload)

  if (!response.ok && role === 'admin') {
    await postJson('/auth/bootstrap', { ...loginPayload, role: 'admin' })
    response = await postJson('/auth/login', loginPayload)
  }

  if (!response.ok && role === 'user') {
    await postJson('/auth/register', { ...loginPayload, role: 'user' })
    response = await postJson('/auth/login', loginPayload)
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`${role} 登录失败：${username} ${response.status} ${detail}`.trim())
  }

  const auth = await response.json()
  await page.addInitScript(({ token, roleName, usernameValue }) => {
    window.localStorage.setItem('access_token', token)
    window.localStorage.setItem('role', roleName)
    window.localStorage.setItem('username', usernameValue)
  }, {
    token: auth.access_token,
    roleName: auth.role || role,
    usernameValue: username,
  })
}

async function inspectLayout(page) {
  return page.evaluate(() => {
    const issues = []
    const viewportWidth = window.innerWidth
    const doc = document.documentElement
    if (doc.scrollWidth > viewportWidth + 4) {
      issues.push({
        type: 'horizontal-overflow',
        text: `页面横向溢出 ${doc.scrollWidth - viewportWidth}px`,
        selector: 'document',
      })
    }

    const isVisible = (el) => {
      const style = window.getComputedStyle(el)
      const rect = el.getBoundingClientRect()
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0
    }

    const selectorFor = (el) => {
      if (el.id) return `#${el.id}`
      const cls = Array.from(el.classList || []).slice(0, 3).join('.')
      return `${el.tagName.toLowerCase()}${cls ? `.${cls}` : ''}`
    }

    const labelSelectors = [
      '.el-descriptions__label',
      '.intent-summary-label',
      '.detail-desc .el-descriptions__label',
      '.el-form-item__label',
      'th',
    ]
    document.querySelectorAll(labelSelectors.join(',')).forEach((el) => {
      if (!isVisible(el)) return
      const text = (el.innerText || '').replace(/\s+/g, '')
      if (text.length < 2 || text.length > 12) return
      const rect = el.getBoundingClientRect()
      const hasChinese = /[\u4e00-\u9fa5]/.test(text)
      const tooNarrow = rect.width < 34 && rect.height > 46
      const verticalLike = hasChinese && rect.height / Math.max(rect.width, 1) > 2.6
      if (tooNarrow || verticalLike) {
        issues.push({
          type: 'vertical-label',
          text,
          selector: selectorFor(el),
          rect: {
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          },
        })
      }
    })

    document.querySelectorAll('body *').forEach((el) => {
      if (!isVisible(el)) return
      if (el.closest('.el-table')) return
      if (el.closest('.el-scrollbar__view')) return
      const rect = el.getBoundingClientRect()
      if (rect.right > viewportWidth + 8 && rect.width > 80) {
        const text = (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 80)
        issues.push({
          type: 'element-overflow-right',
          text,
          selector: selectorFor(el),
          rect: {
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            width: Math.round(rect.width),
          },
        })
      }
    })

    return issues.slice(0, 30)
  })
}

async function run() {
  await fs.mkdir(outputDir, { recursive: true })
  const browser = await chromium.launch({ headless: process.env.HEADED_UI !== '1' })
  const allIssues = []
  try {
    for (const viewport of viewports) {
      for (const item of pages) {
        const context = await browser.newContext({ viewport })
        const page = await context.newPage()
        const routeLabel = `${viewport.name}-${item.role}-${safeName(item.path)}`
        try {
          await login(page, item.role)
          await page.goto(absoluteUrl(item.path), { waitUntil: 'domcontentloaded' })
          await page.waitForLoadState('networkidle').catch(() => {})
          if (item.waitFor) {
            await page.locator(item.waitFor).first().waitFor({ timeout: 10_000 }).catch(() => {})
          }
          const screenshot = path.join(outputDir, `${routeLabel}.png`)
          await page.screenshot({ path: screenshot, fullPage: true })
          const issues = await inspectLayout(page)
          if (issues.length) {
            allIssues.push({ page: item.path, role: item.role, viewport: viewport.name, screenshot, issues })
          }
        } catch (error) {
          allIssues.push({
            page: item.path,
            role: item.role,
            viewport: viewport.name,
            issues: [{ type: 'page-check-failed', text: error.message }],
          })
        } finally {
          await context.close()
        }
      }
    }
  } finally {
    await browser.close()
  }

  const reportPath = path.join(outputDir, 'report.json')
  await fs.writeFile(reportPath, JSON.stringify({
    baseUrl,
    checkedAt: new Date().toISOString(),
    issueGroups: allIssues,
  }, null, 2))

  if (allIssues.length) {
    console.error(`UI smoke 发现 ${allIssues.length} 组问题，报告：${reportPath}`)
    for (const group of allIssues) {
      console.error(`- ${group.viewport} ${group.role} ${group.page}`)
      for (const issue of group.issues.slice(0, 5)) {
        console.error(`  · ${issue.type}: ${issue.text || issue.selector || ''}`)
      }
    }
    process.exit(1)
  }

  console.log(`UI smoke 通过，截图目录：${outputDir}`)
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
