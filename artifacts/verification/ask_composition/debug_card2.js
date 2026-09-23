// 诊断2：文本定位 111A 卡片点击
const { chromium } = require("playwright-core");
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true,
    args: ["--proxy-server=direct://", "--proxy-bypass-list=*"] });
  const page = await (await browser.newContext({ viewport: { width: 1680, height: 950 } })).newPage();
  const fs = require("fs");
  const out = {};
  await page.goto("http://localhost:8000/", { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForSelector(".card", { timeout: 30000 });
  out.clickInfo = await page.evaluate(() => {
    const card = [...document.querySelectorAll(".card")].find(c => (c.textContent || "").includes("111A"));
    if (!card) return { found: false };
    card.click();
    return { found: true, cid: card.dataset.cid || "(no-cid)", stem: card.dataset.stem || "(no-stem)",
             text: (card.textContent || "").slice(0, 40) };
  });
  await page.waitForTimeout(2500);
  out.after = await page.evaluate(() => {
    const btn = document.getElementById("askModelBtn");
    return { btnShown: btn ? getComputedStyle(btn).display !== "none" : null,
             hash: location.hash };
  });
  fs.writeFileSync(__dirname + "/debug_card2.json", JSON.stringify(out, null, 1));
  console.log("done");
  await browser.close();
})();
