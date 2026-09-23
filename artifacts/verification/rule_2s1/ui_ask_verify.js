/* 工作台内问答 UI 验证 —— playwright-core + 系统 Edge（无 Chromium 下载）
   用例：点「询问模型」→ 内联面板出现 → 输入质询 → 提交 → 回答区出现结论与证据。 */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const EV = "D:/09work/quant_workbench_v3/quant_workbench_package/artifacts/verification/rule_2s1";
const results = [];
const rec = (name, ok, detail) => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}: ${detail}`); };

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await ctx.newPage();
  try {
    await page.goto("http://127.0.0.1:8000/", { waitUntil: "load", timeout: 30000 });
    await page.waitForSelector(".card", { timeout: 15000 });

    const stem = await page.evaluate(() => {
      const el = [...document.querySelectorAll(".card[data-stem]")]
        .find(c => c.dataset.stem && c.dataset.stem.includes("strategy_20cm_v1"));
      return el ? el.dataset.stem : null;
    });
    rec("card_with_stem", !!stem, `stem=${stem}`);
    if (!stem) throw new Error("无可用卡片（strategy_20cm_v1）");

    await page.click(`.card[data-stem="${stem}"]`);
    await page.waitForFunction(() => {
      const b = document.getElementById("askModelBtn");
      return b && b.style.display !== "none" && b.offsetParent !== null;
    }, { timeout: 10000 });
    await page.waitForTimeout(800);
    rec("ask_btn_visible", true, `详情页按钮可见（stem=${stem}）`);

    await page.click("#askModelBtn");
    await page.waitForSelector("#askPanel", { state: "visible", timeout: 5000 });
    await page.screenshot({ path: path.join(EV, "ui_step2_panel_open.png") });
    rec("panel_opens_inline", true, "点击后内联面板展开（无 prompt、无剪贴板）");

    await page.fill("#askInput", "688037 20200117");
    await page.click("#askSubmit");
    await page.waitForFunction(() => {
      const a = document.getElementById("askAnswer");
      return a && a.style.display !== "none" && a.innerText.includes("核验") && !a.innerText.includes("核验中");
    }, { timeout: 180000 });
    const answer = await page.evaluate(() => document.getElementById("askAnswer").innerText);
    fs.writeFileSync(path.join(EV, "ui_answer_text.txt"), answer, "utf8");
    const okAns = answer.includes("不是遗漏") || answer.includes("未封死涨停") || answer.includes("不在本模型宇宙内");
    rec("answer_rendered", okAns, answer.split("\n")[0].slice(0, 120));
    const hasEvidence = answer.includes("核验证据") &&
      (answer.includes("重跑命中") || answer.includes("不在本模型宇宙内"));
    rec("evidence_rendered", hasEvidence, "回答区含核验证据（或在池判定即止）");

    // 再问一次命中日（换日期），确认面板可连续使用
    await page.fill("#askInput", "688037 20200116");
    await page.click("#askSubmit");
    await page.waitForFunction(() => {
      const a = document.getElementById("askAnswer");
      return a && a.innerText.includes("封死涨停");
    }, { timeout: 180000 });
    rec("second_query_ok", true, "连续第二次质询（涨停日）返回封板结论");
    await page.screenshot({ path: path.join(EV, "ui_step3_answer.png") });
  } catch (e) {
    rec("fatal", false, String(e).slice(0, 300));
    try { await page.screenshot({ path: path.join(EV, "ui_fatal.png") }); } catch (_) {}
  } finally {
    fs.writeFileSync(path.join(EV, "ui_ask_verify_results.json"),
      JSON.stringify({ generated_at: new Date().toISOString(), results }, null, 1), "utf8");
    await browser.close();
  }
})();
