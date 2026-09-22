/* 「询问模型」入口 UI 验证 —— playwright-core + 系统 Edge（无 Chromium 下载） */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const EV = "D:/09work/quant_workbench_v3/quant_workbench_package/artifacts/verification/ui_ask_entry";
const results = [];
const rec = (name, ok, detail) => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}: ${detail}`); };

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    permissions: ["clipboard-read", "clipboard-write"],
  });
  const page = await ctx.newPage();
  try {
    await page.goto("http://127.0.0.1:8000/", { waitUntil: "load", timeout: 30000 });
    await page.waitForSelector(".card", { timeout: 15000 });
    await page.screenshot({ path: path.join(EV, "step1_home.png") });
    rec("home_loaded", true, "首页加载且存在模型卡片");

    // 选一个有结果的卡片（带 data-stem）
    const stem = await page.evaluate(() => {
      const el = [...document.querySelectorAll(".card[data-stem]")].find(c => c.dataset.stem);
      return el ? el.dataset.stem : null;
    });
    rec("card_with_stem", !!stem, `stem=${stem}`);
    if (!stem) throw new Error("无可用卡片");

    await page.click(`.card[data-stem="${stem}"]`);
    await page.waitForFunction(() => {
      const d = document.getElementById("detailEl") || document.querySelector("#detail");
      return d && getComputedStyle(d).display !== "none";
    }, { timeout: 10000 }).catch(() => {});
    await page.waitForFunction(() => {
      const b = document.getElementById("askModelBtn");
      return b && b.style.display !== "none" && b.offsetParent !== null;
    }, { timeout: 10000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(EV, "step2_detail.png") });
    rec("ask_btn_visible", true, `详情页「询问模型」按钮可见（stem=${stem}）`);

    // 捕获 prompt 对话框内容
    let dialogMsg = null;
    page.once("dialog", async d => { dialogMsg = d.message(); await d.accept("688037 20200117"); });
    await page.click("#askModelBtn");
    await page.waitForTimeout(600);
    rec("prompt_dialog", !!dialogMsg && (dialogMsg.includes("质询对象（可留空）") || dialogMsg.includes("【工作台质询】")),
        dialogMsg ? dialogMsg.slice(0, 120).replace(/\n/g, " | ") : "未弹出对话框");
    fs.writeFileSync(path.join(EV, "prompt_text.txt"), dialogMsg || "", "utf8");

    // 剪贴板内容比对
    await page.waitForTimeout(500);
    let clip = null;
    try { clip = await page.evaluate(() => navigator.clipboard.readText()); }
    catch (e) { clip = "CLIPBOARD_READ_FAILED: " + e.message; }
    const clipOk = typeof clip === "string" && clip.includes("【工作台质询】") && clip.includes(`stem：${stem}`);
    fs.writeFileSync(path.join(EV, "clipboard_text.txt"), String(clip), "utf8");
    rec("clipboard_content", clipOk, clipOk ? `含 stem=${stem} 的质询全文已写入剪贴板` : String(clip).slice(0, 120));
    await page.screenshot({ path: path.join(EV, "step3_after_click.png") });
  } catch (e) {
    rec("fatal", false, String(e).slice(0, 300));
    try { await page.screenshot({ path: path.join(EV, "fatal.png") }); } catch (_) {}
  } finally {
    fs.writeFileSync(path.join(EV, "ui_verify_results.json"),
      JSON.stringify({ generated_at: new Date().toISOString(), results }, null, 1), "utf8");
    await browser.close();
  }
})();
