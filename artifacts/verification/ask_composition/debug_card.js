// 诊断：卡片 stem 列表 + 点击后详情状态
const { chromium } = require("playwright-core");
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true,
    args: ["--proxy-server=direct://", "--proxy-bypass-list=*"] });
  const page = await (await browser.newContext({ viewport: { width: 1680, height: 950 } })).newPage();
  const fs = require("fs");
  const out = {};
  await page.goto("http://localhost:8000/", { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForSelector(".card", { timeout: 30000 });
  out.stems = await page.evaluate(() =>
    [...document.querySelectorAll(".card")].slice(0, 40).map(c => c.dataset.stem || "(none)"));
  const hit = await page.evaluate(() => {
    const card = document.querySelector('.card[data-stem="strategy_111a_r1_v1"]');
    if (!card) return "no-card";
    card.click();
    return "clicked";
  });
  out.hit = hit;
  await page.waitForTimeout(1200);
  out.after = await page.evaluate(() => {
    const btn = document.getElementById("askModelBtn");
    return { btnShown: btn ? getComputedStyle(btn).display !== "none" : null,
             detailVisible: !!document.querySelector("#detailView:not([style*='display: none'])"),
             bodyViews: [...document.querySelectorAll("section, .view")].map(v => v.id || v.className).slice(0, 12) };
  });
  fs.writeFileSync(__dirname + "/debug_card.json", JSON.stringify(out, null, 1));
  console.log(JSON.stringify(out).slice(0, 400));
  await browser.close();
})();
