/* 通用问答 UI 验收 —— playwright-core + Edge */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const EV = "D:/09work/quant_workbench_v3/quant_workbench_package/artifacts/verification/ask_general";
const results = [];
const rec = (name, ok, detail) => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}: ${detail}`); };

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await ctx.newPage();
  try {
    await page.goto("http://127.0.0.1:8000/", { waitUntil: "load", timeout: 30000 });
    await page.waitForSelector(".card", { timeout: 15000 });

    // 进入 2S1（strategy_20cm_v1）详情
    await page.evaluate(() => {
      // 直接对卡片元素派发 click（target=卡片本身，不会命中 .rule-name 触发重命名）
      const card = document.querySelector('.card[data-stem="strategy_20cm_v1"]');
      (card || document.querySelector(".card")).click();
    });
    await page.waitForTimeout(800);
    await page.click("#askModelBtn");
    await page.waitForTimeout(200);

    // 用例1：口径类问题（原本报错，现应给确定性解答）
    await page.fill("#askInput", "怎么计算区间涨幅的");
    await page.click("#askSubmit");
    await page.waitForFunction(() => {
      const a = document.getElementById("askAnswer");
      return a && a.textContent.includes("区间涨幅口径");
    }, { timeout: 60000 });
    const g1 = await page.evaluate(() => document.getElementById("askAnswer").textContent);
    rec("Q1_general_answered", g1.includes("区间末收盘") && g1.includes("相关列"), "口径解答 + 本模型相关列");
    await page.screenshot({ path: path.join(EV, "ui_case1_change.png") });

    // 用例2：个股质询回归（原路径不受影响）
    await page.fill("#askInput", "688037 20200116");
    await page.click("#askSubmit");
    await page.waitForFunction(() => {
      const a = document.getElementById("askAnswer");
      return a && (a.textContent.includes("封死涨停") || a.textContent.includes("一致性"));
    }, { timeout: 120000 });
    const g2 = await page.evaluate(() => document.getElementById("askAnswer").textContent);
    rec("Q2_stock_path_ok", g2.includes("封死涨停"), "个股路径回归正常");
    await page.screenshot({ path: path.join(EV, "ui_case2_stock.png") });

    // 用例3：无法归类 → 能力清单（不再是红色报错）
    await page.fill("#askInput", "今天天气怎么样");
    await page.click("#askSubmit");
    await page.waitForFunction(() => {
      const a = document.getElementById("askAnswer");
      return a && a.textContent.includes("未能归类");
    }, { timeout: 60000 });
    const g3 = await page.evaluate(() => document.getElementById("askAnswer").textContent);
    rec("Q3_unknown_menu", g3.includes("个股质询") && g3.includes("口径类"), "兜底返回能力清单");
    await page.screenshot({ path: path.join(EV, "ui_case3_unknown.png") });

    fs.writeFileSync(path.join(EV, "ui_verify_results.json"), JSON.stringify(results, null, 1));
    const fails = results.filter(r => !r.ok).length;
    console.log(`SUMMARY: ${results.length - fails}/${results.length} PASS`);
    await browser.close();
    process.exit(fails ? 1 : 0);
  } catch (e) {
    console.error("ABORT:", e.message);
    fs.writeFileSync(path.join(EV, "ui_verify_results.json"), JSON.stringify(results, null, 1));
    process.exit(2);
  }
})();
