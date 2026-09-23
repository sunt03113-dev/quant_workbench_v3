// 验收：结果构成类质询在 UI 内闭环（111A 卡片 + 用户原句）
const { chromium } = require("playwright-core");
const fs = require("fs");

(async () => {
  const out = {};
  const rec = (k, ok, note) => { out[k] = { ok, note }; console.log(ok ? "PASS" : "FAIL", k, note || ""); };
  const browser = await chromium.launch({ channel: "msedge", headless: true,
    args: ["--proxy-server=direct://", "--proxy-bypass-list=*"] });
  const ctx = await browser.newContext({ viewport: { width: 1680, height: 950 },
    permissions: [] });
  const page = await ctx.newPage();
  try {
    let loaded = false;
    for (let i = 0; i < 3 && !loaded; i++) {
      try { await page.goto("http://127.0.0.1:8000/", { waitUntil: "domcontentloaded", timeout: 60000 }); loaded = true; }
      catch (e) { console.log("goto retry", i + 1); }
    }
    if (!loaded) throw new Error("page.goto 三次超时");
    await page.waitForSelector(".card", { timeout: 30000 });
    // 测试环境是全新 localStorage：给 111A 卡补 ruleStem 绑定（复刻用户真实环境），再刷新
    await page.evaluate(() => {
      const s = JSON.parse(localStorage.getItem("qw_state_v3") || "null");
      if (s && Array.isArray(s.groups)) {
        for (const g of s.groups) for (const c of (g.cards || []))
          if (c.id === "111A" && !c.ruleStem) { c.ruleStem = "strategy_111a_r1_v1"; c.desc = "strategy_111a_r1_v1"; }
        localStorage.setItem("qw_state_v3", JSON.stringify(s));
      }
    });
    await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForSelector(".card", { timeout: 30000 });

    // 打开 111A 详情：直接对卡片元素 click（不命中规则名）
    await page.evaluate(() => {
      const card = document.querySelector('.card[data-stem="strategy_111a_r1_v1"]')
        || [...document.querySelectorAll(".card")].find(c => (c.textContent || "").includes("111A"));
      (card || document.querySelector(".card")).click();
    });
    await page.waitForTimeout(1200);
    const btnShown = await page.evaluate(() => {
      const btn = document.getElementById("askModelBtn");
      return btn ? getComputedStyle(btn).display !== "none" : false;
    });
    if (!btnShown) throw new Error("询问模型按钮未显示（ruleStem 未绑定？）");
    await page.click("#askModelBtn");
    await page.waitForSelector("#askInput", { timeout: 15000 });
    rec("detail_open", true, "详情页与质询面板可见");

    await page.fill("#askInput", "请询问这个结果中有没有包含30开头的股票的10cm阶段的吗?");
    await page.click("#askSubmit");
    await page.waitForSelector("#askAnswer .ask-verdict, #askAnswer", { timeout: 120000 });
    await page.waitForTimeout(1500);
    const ans = await page.evaluate(() => document.getElementById("askAnswer").innerText);
    rec("composition_answer", ans.includes("结果构成核查") && ans.includes("没有") && ans.includes("10cm"),
        (ans.match(/【[^】]+】/) || [""])[0]);
    rec("no_stats_fallback", !ans.includes("命中统计"), "不再掉入命中统计兜底");
    await page.screenshot({ path: __dirname + "/ui_composition_111A.png" });
  } catch (e) {
    rec("exception", false, String(e).slice(0, 200));
  }
  fs.writeFileSync(__dirname + "/ui_verify_results.json", JSON.stringify(out, null, 1));
  await browser.close();
})();
