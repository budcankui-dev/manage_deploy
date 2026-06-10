import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("playwright");

const baseUrl = process.env.EVALUATION_BASE_URL || "http://10.112.244.94:8182";
const username = process.env.E2E_ADMIN_USERNAME || "admin";
const password = process.env.E2E_ADMIN_PASSWORD || "admin";
const matmulRunId = process.env.MATMUL_BENCHMARK_RUN_ID || "matmul-formal-20260610-01";
const videoRunId = process.env.VIDEO_BENCHMARK_RUN_ID || "video-formal-20260610-01";
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

async function login(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" });
  if (!page.url().includes("/login")) return;

  await page.getByPlaceholder("admin").fill(username);
  await page.locator('input[type="password"]').fill(password);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 15000 });
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

async function captureBenchmark(page, runId, taskName, prefix) {
  await openPage(page, `/benchmark?benchmark_run_id=${encodeURIComponent(runId)}`, "业务测评");
  await selectTaskType(page, taskName);
  await save(page, `${prefix}-benchmark-setup.png`);

  await page.getByText("计算成功率", { exact: false }).first().click().catch(() => {});
  await pause(1200);
  await page.getByText("运行证据", { exact: false }).first().scrollIntoViewIfNeeded().catch(() => {});
  await pause(800);
  await save(page, `${prefix}-benchmark-result.png`);

  const details = page.getByRole("button", { name: "详情" });
  const count = await details.count();
  if (count > 0) {
    await details.nth(0).click();
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
  await openPage(page, "/intent-chat", "智联计算系统");
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
  await login(page);
  await captureBenchmark(page, matmulRunId, "矩阵乘法计算任务", "matmul");
  await captureBenchmark(page, videoRunId, "视频AI推理任务", "video");
  await captureIntentChat(page);
  await captureIntentEvaluation(page);
} finally {
  await browser.close();
}
