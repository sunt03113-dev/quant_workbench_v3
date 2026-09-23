// 诊断3：Edge 内 fetch 是否可用
const { chromium } = require("playwright-core");
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true,
    args: ["--proxy-server=direct://", "--proxy-bypass-list=*"] });
  const page = await (await browser.newContext()).newPage();
  const errs = [];
  page.on("requestfailed", r => errs.push(r.url() + " :: " + (r.failure() || {}).errorText));
  await page.goto("http://localhost:8000/", { waitUntil: "domcontentloaded", timeout: 30000 });
  const res = await page.evaluate(async () => {
    try {
      const r = await fetch("/api/data/latest");
      return { ok: r.status, txt: (await r.text()).slice(0, 80) };
    } catch (e) { return { err: String(e) }; }
  });
  require("fs").writeFileSync(__dirname + "/debug_fetch.json",
    JSON.stringify({ res, errs: errs.slice(0, 5) }, null, 1));
  console.log("done");
  await browser.close();
})();
