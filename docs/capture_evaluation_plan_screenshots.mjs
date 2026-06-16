import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("playwright");

const baseUrl = process.env.EVALUATION_BASE_URL || "http://10.112.244.94:8182";
const username = process.env.E2E_ADMIN_USERNAME || "admin";
const password = process.env.E2E_ADMIN_PASSWORD || "admin";
const userUsername = process.env.E2E_USER_USERNAME || "user";
const userPassword = process.env.E2E_USER_PASSWORD || "user";
const matmulRunId = process.env.MATMUL_BENCHMARK_RUN_ID || "high_throughput_matmul-20260612095418";
const videoRunId = process.env.VIDEO_BENCHMARK_RUN_ID || "video-route-pool-check-20260612160633";
const outDir = path.resolve("docs/assets/evaluation-plan");

async function pause(ms = 1000) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function save(page, name, options = {}) {
  const file = path.join(outDir, name);
  await page.screenshot({
    path: file,
    fullPage: options.fullPage ?? true,
    animations: "disabled",
  });
  console.log(file);
}

async function login(page, loginUsername = username, loginPassword = password) {
  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" });
  if (page.url().includes("/login")) {
    await page.getByPlaceholder("admin").fill(loginUsername);
    await page.locator('input[type="password"]').fill(loginPassword);
    await page.getByRole("button", { name: "登录" }).click();
    await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 15000 });
  }
}

async function logout(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" });
  const logoutButton = page.getByRole("button", { name: "退出登录" });
  if (await logoutButton.count()) {
    await logoutButton.first().click();
    await page.waitForURL((url) => url.pathname.includes("/login"), { timeout: 10000 }).catch(() => {});
  }
}

async function openPage(page, route, waitText) {
  await page.goto(`${baseUrl}${route}`, { waitUntil: "domcontentloaded" });
  await page.locator("body").waitFor({ timeout: 15000 });
  if (waitText) {
    await page.getByText(waitText, { exact: false }).first().waitFor({ timeout: 10000 });
  }
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await pause(1200);
}

async function selectTaskType(page, visibleName) {
  const current = page.locator(".task-select .el-select__placeholder").first();
  if ((await current.textContent().catch(() => ""))?.includes(visibleName)) {
    return;
  }
  await page.locator(".task-select").first().click({ force: true });
  await page.getByRole("option", { name: visibleName }).click();
  await pause(1200);
}

async function openFirstOrderDetail(page) {
  const details = page.getByRole("button", { name: "详情", exact: true });
  const detailCount = await details.count();
  if (detailCount > 0) {
    await details.first().click();
  } else {
    const firstRow = page.locator(".evidence-table .el-table__body-wrapper tbody tr").first();
    if (!(await firstRow.count())) return false;
    await firstRow.dblclick();
  }
  await page.getByText("任务工单详情", { exact: false }).first().waitFor({ timeout: 10000 });
  return true;
}

async function captureBenchmark(page, runId, taskName, prefix) {
  await openPage(page, `/benchmark?benchmark_run_id=${encodeURIComponent(runId)}`, "业务测评");
  await selectTaskType(page, taskName);
  await save(page, `${prefix}-benchmark-setup.png`);

  await page.getByText("计算成功率", { exact: false }).first().click().catch(() => {});
  await pause(1200);
  await page.getByText("测试工单列表", { exact: false }).first().scrollIntoViewIfNeeded().catch(() => {});
  await pause(800);
  await save(page, `${prefix}-benchmark-result.png`);

  if (await openFirstOrderDetail(page)) {
    await pause(1600);
    await save(page, `${prefix}-order-detail-overview.png`, { fullPage: false });
    if (prefix === "video") {
      await page.getByText("带框预览", { exact: false }).first().scrollIntoViewIfNeeded().catch(() => {});
      await pause(800);
      await save(page, "video-order-detail-result-preview.png", { fullPage: false });
    }
    await page.keyboard.press("Escape").catch(() => {});
    await pause(700);
  }

  await page.getByText("业务目标成功率需达到", { exact: false }).first().scrollIntoViewIfNeeded().catch(() => {});
  await pause(800);
  await save(page, `${prefix}-benchmark-evidence-table.png`);
}

async function captureIntentEvaluation(page) {
  await openPage(page, "/intent-evaluation", "数据集意图解析参数提取准确率");
  await save(page, "intent-evaluation-dashboard.png");
  await page.getByText("评测样本", { exact: false }).first().scrollIntoViewIfNeeded().catch(() => {});
  await pause(800);
  await save(page, "intent-evaluation-samples.png");
}

async function captureIntentChat(page) {
  await openPage(page, "/intent-chat", "对话列表");
  await save(page, "intent-chat-page.png");
}

await fs.mkdir(outDir, { recursive: true });

const browser = await chromium.launch({
  headless: process.env.HEADED_UI !== "1",
});
const context = await browser.newContext({
  viewport: { width: 1366, height: 900 },
  deviceScaleFactor: 1,
});
const page = await context.newPage();
page.setDefaultTimeout(15000);

try {
  await login(page, username, password);
  await captureBenchmark(page, matmulRunId, "矩阵乘法计算任务", "matmul");
  await captureBenchmark(page, videoRunId, "视频AI推理任务", "video");
  await openPage(page, "/settings", "系统设置");
  await save(page, "system-settings-runtime-mode.png");
  await captureIntentEvaluation(page);
  await logout(page);
  await login(page, userUsername, userPassword);
  await captureIntentChat(page);
} finally {
  await browser.close();
}
