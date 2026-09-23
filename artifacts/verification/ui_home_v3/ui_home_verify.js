/* 首页改造验收 —— playwright-core + 系统 Edge：迁移/排序/hover菜单/重命名/拖拽 */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const EV = "D:/09work/quant_workbench_v3/quant_workbench_package/artifacts/verification/ui_home_v3";
const results = [];
const rec = (name, ok, detail) => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}: ${detail}`); };

const OLD_STATE = {
  groups: [
    { id: "1S", name: "1S", cards: [{ id: "1S1", name: "1S1", ruleStem: "strategy_10cm_v6", desc: "" }, { id: "1S2A1", name: "1S2A1" }, { id: "1S4C", name: "1S4C" }] },
    { id: "1Z", name: "1Z", cards: [{ id: "1Z1A", name: "1Z1A" }] },
    { id: "12", name: "1/2", cards: [{ id: "111B", name: "111B" }] },
    { id: "3", name: "3", cards: [{ id: "3-1A", name: "3-1A" }] },
    { id: "2S", name: "2S", cards: [
      { id: "2S1c", name: "2S1", ruleStem: "strategy_20cm_v1", desc: "" },
      { id: "2S2A2a", name: "2S2A2a" }, { id: "2S2B1", name: "2S2B1" }, { id: "2S3A", name: "2S3A" }
    ] },
    { id: "g_u_1", name: "2S1", cards: [] },
    { id: "g_u_2", name: "2S2/2S3", cards: [] },
    { id: "g_u_3", name: "4", cards: [] },
  ],
  trash: [],
};

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await ctx.newPage();

  const groupNames = () => page.evaluate(() => [...document.querySelectorAll("#matrix > .group .gname")].map(e => e.textContent.trim()));
  const groupCards = (name) => page.evaluate((n) => {
    const gs = [...document.querySelectorAll("#matrix > .group")];
    const g = gs.find(x => x.querySelector(".gname").textContent.trim() === n);
    return g ? [...g.querySelectorAll(".card .rule-name")].map(e => e.textContent.trim()) : null;
  }, name);

  // ---------- 用例A：老状态迁移（2S 拆分 + 排序 + 新类别'4'归位） ----------
  await page.addInitScript((s) => localStorage.setItem("qw_state_v3", JSON.stringify(s)), OLD_STATE);
  await page.goto("http://127.0.0.1:8000/", { waitUntil: "load", timeout: 30000 });
  await page.waitForSelector(".card", { timeout: 15000 });

  let names = await groupNames();
  rec("A1_2s_split", !names.includes("2S") && names.includes("2S1") && names.includes("2S2/2S3"),
      `类别=${names.join(",")}`);
  let c1 = await groupCards("2S1"), c2 = await groupCards("2S2/2S3");
  rec("A2_split_cards", c1.length === 1 && c1[0] === "2S1" && c2.length === 3 && c2.includes("2S3A"),
      `2S1=[${c1}] 2S2/2S3=[${c2}]`);
  rec("A3_desc_order", JSON.stringify(names) === JSON.stringify(["4", "3", "1/2", "1Z", "1S", "2S1", "2S2/2S3"]),
      `顺序=${names.join(" → ")}`);
  const stemKept = await page.evaluate(() => {
    const gs = JSON.parse(localStorage.getItem("qw_state_v3")).groups;
    const c = gs.find(g => g.name === "2S1").cards.find(c => c.name === "2S1");
    return c && c.ruleStem === "strategy_20cm_v1";
  });
  rec("A4_rulestem_kept", stemKept, "拆分后 ruleStem 绑定保留");
  await page.screenshot({ path: path.join(EV, "caseA_migrated.png") });

  // ---------- 用例B：＋号 hover 菜单不再消失 ----------
  await page.hover("#addGroupTop");
  await page.waitForTimeout(250);
  const menuVisible1 = await page.evaluate(() => getComputedStyle(document.querySelector(".plus-menu")).display !== "none");
  // 模拟真实鼠标轨迹：从按钮中心缓慢移到「增加模型」上（穿过缝隙）
  const btn = await page.locator("#addGroupTop").boundingBox();
  const item = await page.locator("#addModelBtn").boundingBox();
  await page.mouse.move(btn.x + btn.width / 2, btn.y + btn.height / 2);
  for (let i = 1; i <= 8; i++) {
    await page.mouse.move(
      btn.x + btn.width / 2 + (item.x + item.width / 2 - btn.x - btn.width / 2) * i / 8,
      btn.y + btn.height / 2 + (item.y + item.height / 2 - btn.y - btn.height / 2) * i / 8);
    await page.waitForTimeout(30);
  }
  await page.waitForTimeout(200);
  const menuVisible2 = await page.evaluate(() => getComputedStyle(document.querySelector(".plus-menu")).display !== "none");
  await page.click("#addModelBtn");
  const modalShown = await page.evaluate(() => document.getElementById("addModelModal").classList.contains("show"));
  rec("B1_hover_menu_stays", menuVisible1 && menuVisible2, `hover时显示=${menuVisible1} 穿缝后仍显示=${menuVisible2}`);
  rec("B2_menu_item_clickable", modalShown, "点击「增加模型」弹出新增弹窗");
  await page.evaluate(() => document.getElementById("addModelModal").classList.remove("show"));
  await page.mouse.move(400, 500);

  // ---------- 用例C：类别重命名（点击 gname → prompt，按名字定位避免重名歧义） ----------
  let dialogReply = null;
  page.on("dialog", async d => { const r = dialogReply; dialogReply = null; await d.accept(r == null ? "" : r); });
  const clickGname = (n) => page.evaluate((nm) => {
    [...document.querySelectorAll("#matrix > .group .gname")].find(e => e.textContent.trim() === nm).click();
  }, n);
  const clickCardName = (gn, cn) => page.evaluate(({ gname, cname }) => {
    const gs = [...document.querySelectorAll("#matrix > .group")];
    const g = gs.find(x => x.querySelector(".gname").textContent.trim() === gname);
    [...g.querySelectorAll(".card .rule-name")].find(e => e.textContent.trim() === cname).click();
  }, { gname: gn, cname: cn });

  dialogReply = "新序列X";
  await clickGname("3");
  await page.waitForTimeout(300);
  names = await groupNames();
  rec("C1_group_rename", names.includes("新序列X"), `点击类别名重命名 → ${names.join(",")}`);
  // 还原名字
  dialogReply = "3";
  await clickGname("新序列X");
  await page.waitForTimeout(300);

  // ---------- 用例D：卡片重命名（点击卡片上的模型名 → prompt，且不进详情） ----------
  dialogReply = "1Z1Z";
  await clickCardName("1Z", "1Z1A");
  await page.waitForTimeout(400);
  const cards1z = await groupCards("1Z");
  const stillHome = await page.evaluate(() => document.getElementById("homePage").style.display !== "none");
  rec("D1_card_rename", cards1z.includes("1Z1Z") && stillHome, `点击模型名改名=[${cards1z}] 未跳详情=${stillHome}`);

  // ---------- 用例E：类别拖拽排序（HTML5 DnD 事件派发） ----------
  const before = await groupNames();
  await page.evaluate(() => {
    const gs = [...document.querySelectorAll("#matrix > .group")];
    const src = gs.find(x => x.querySelector(".gname").textContent.trim() === "3");
    const dst = gs.find(x => x.querySelector(".gname").textContent.trim() === "4");
    const dt = new DataTransfer();
    src.querySelector(".group-header").dispatchEvent(new DragEvent("dragstart", { bubbles: true, dataTransfer: dt }));
    dst.dispatchEvent(new DragEvent("dragover", { bubbles: true, dataTransfer: dt }));
    dst.dispatchEvent(new DragEvent("drop", { bubbles: true, dataTransfer: dt }));
    src.querySelector(".group-header").dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer: dt }));
  });
  await page.waitForTimeout(300);
  const after = await groupNames();
  const persisted = await page.evaluate(() => JSON.parse(localStorage.getItem("qw_state_v3")).groups.map(g => g.name));
  rec("E1_group_drag", before[0] === "4" && after[0] === "3" && persisted[0] === "3",
      `拖拽前=${before.join(",")} 拖拽后=${after.join(",")} 持久化=${persisted.join(",")}`);

  // ---------- 用例F：卡片跨类别拖拽 ----------
  await page.evaluate(() => {
    const gs = [...document.querySelectorAll("#matrix > .group")];
    const src = gs.find(x => x.querySelector(".gname").textContent.trim() === "1Z");
    const dst = gs.find(x => x.querySelector(".gname").textContent.trim() === "1S");
    const card = src.querySelector(".card");
    const dstContainer = dst.querySelector(".group-card-container");
    const dstCard = dstContainer.querySelector(".card");
    const dt = new DataTransfer();
    card.dispatchEvent(new DragEvent("dragstart", { bubbles: true, dataTransfer: dt }));
    (dstCard || dstContainer).dispatchEvent(new DragEvent("dragover", { bubbles: true, dataTransfer: dt }));
    (dstCard || dstContainer).dispatchEvent(new DragEvent("drop", { bubbles: true, dataTransfer: dt }));
    card.dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer: dt }));
  });
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(EV, "caseF_after_drags.png") });
  const ls = await page.evaluate(() => JSON.parse(localStorage.getItem("qw_state_v3")).groups.map(g => ({ n: g.name, c: g.cards.map(x => x.name) })));
  const srcG = ls.find(g => g.n === "1Z"), dstG = ls.find(g => g.n === "1S");
  rec("F1_card_cross_group", srcG.c.length === 0 && dstG.c.includes("1Z1Z"),
      `1Z=[${srcG.c}] 1S含拖入卡片=${dstG.c.includes("1Z1Z")}`);
  rec("F_state_consistent", ls.every(g => Array.isArray(g.c)), `持久化状态完整：${ls.map(g => g.n + "(" + g.c.length + ")").join(" ")}`);

  await page.screenshot({ path: path.join(EV, "final_home.png") });
  fs.writeFileSync(path.join(EV, "ui_home_verify_results.json"), JSON.stringify(results, null, 1));
  const fails = results.filter(r => !r.ok).length;
  console.log(`\nSUMMARY: ${results.length - fails}/${results.length} PASS`);
  await browser.close();
  process.exit(fails ? 1 : 0);
})().catch(e => {
  console.error("ABORT:", e.message);
  fs.writeFileSync(path.join(EV, "ui_home_verify_results.json"), JSON.stringify(results, null, 1));
  process.exit(2);
});
