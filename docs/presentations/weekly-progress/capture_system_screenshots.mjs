import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";

const require = createRequire(new URL("../../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright");

const baseUrl = process.env.PRESENTATION_BASE_URL || "http://10.112.244.94:8182";
const username = process.env.E2E_ADMIN_USERNAME || "admin";
const password = process.env.E2E_ADMIN_PASSWORD || "admin";
const outDir = path.resolve("docs/presentations/weekly-progress/screenshots");

async function pause(ms = 1200) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function screenshot(page, name, options = {}) {
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

  if (page.url().includes("/login")) {
    await page.getByPlaceholder("admin").fill(username);
    await page.locator('input[type="password"]').fill(password);
    await page.getByRole("button", { name: "登录" }).click();
    await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 15000 });
  }
}

async function openAndCapture(page, route, waitText, fileName) {
  await page.goto(`${baseUrl}${route}`, { waitUntil: "domcontentloaded" });
  await page.locator("body").waitFor({ timeout: 15000 });
  if (waitText) {
    await page
      .getByText(waitText, { exact: false })
      .first()
      .waitFor({ timeout: 5000 })
      .catch(() => {});
  }
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await pause();
  await screenshot(page, fileName);
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

  await openAndCapture(
    page,
    "/intent-evaluation",
    "数据集意图解析参数提取准确率",
    "intent-evaluation-page.png"
  );

  await openAndCapture(page, "/benchmark", "业务目标", "benchmark-page.png");

  await openAndCapture(page, "/business-tasks", "业务工单中心", "business-tasks-page.png");

  const benchmarkOption = page.getByText("压测工单", { exact: false }).first();
  if (await benchmarkOption.isVisible().catch(() => false)) {
    await benchmarkOption.click().catch(() => {});
    await pause(800);
  }

  const detailButton = page.getByRole("button", { name: /详情|查看/ }).first();
  if (await detailButton.isVisible().catch(() => false)) {
    await detailButton.click();
    await pause(1200);
    await screenshot(page, "business-task-detail.png", { fullPage: false });
  }
} finally {
  await browser.close();
}
