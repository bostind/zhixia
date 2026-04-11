import { test, expect } from "@playwright/test";

const BASE_URL = process.env.ZHIXIA_TEST_URL || "http://127.0.0.1:1420";

test.describe("知匣 UI", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
    // 等待后端连接
    await page.waitForSelector(".status-dot.connected", { timeout: 30000 });
  });

  test("should display search input and submit query", async ({ page }) => {
    const input = page.locator(".search-input");
    await expect(input).toBeVisible();
    await input.fill("张总负责的预算文件在哪");
    await page.click(".search-btn");
    // 等待结果出现
    await page.waitForSelector(".constellation.visible", { timeout: 30000 });
    // 至少有一个 star-card
    const cards = page.locator(".star-card");
    await expect(cards.first()).toBeVisible();
  });

  test("should show relation lines for cross-file query", async ({ page }) => {
    await page.fill(".search-input", "和张总相关的所有文件");
    await page.click(".search-btn");
    await page.waitForSelector(".constellation.visible", { timeout: 30000 });
    // 检查是否有关联文本或连线
    await expect(page.locator("text=张总").first()).toBeVisible();
  });

  test("should switch to library view", async ({ page }) => {
    await page.click("[title='索引库']");
    await expect(page.locator("text=已索引文件库")).toBeVisible();
    // 索引库中的卡片应该可见
    await expect(page.locator(".star-card").first()).toBeVisible();
  });

  test("should open settings panel and save LLM config", async ({ page }) => {
    await page.click("[title='目录设置']");
    await expect(page.locator("text=LLM 配置")).toBeVisible();
    await page.fill("input[type='password']", "sk-test123");
    await page.click("text=保存配置");
    // 等待 alert 或提示（Playwright 默认会处理 alert）
    page.on("dialog", (dialog) => dialog.accept());
  });

  test("should trigger manual reindex", async ({ page }) => {
    await page.click("text=手动分析");
    page.on("dialog", (dialog) => dialog.accept());
    await expect(page.locator("text=分析中...")).toBeVisible({ timeout: 5000 });
  });
});
