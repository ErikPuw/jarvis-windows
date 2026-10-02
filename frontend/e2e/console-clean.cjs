// E2E: console sạch và âm thanh không chạy nền khi không nói.
//  - Không còn cảnh báo "THREE.Clock deprecated" và "The AudioContext was not allowed to start" lúc nạp trang.
//  - AudioContext của trình phát: chỉ chạy khi có tiếng, nói xong thì tự suspend (một context chạy mãi giữ luồng âm thanh
//    của hệ điều hành thức, tốn pin/nhiệt cả lúc im lặng), lượt nói sau thì tự chạy lại.
//  - Bảng debug hiệu năng chỉ xuất hiện khi có ?debug=1.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/console-clean.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function open(browser, url) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await ctx.addInitScript(() => {
    window.__ctxs = [];
    const AC = window.AudioContext;
    window.AudioContext = class extends AC { constructor(...a) { super(...a); window.__ctxs.push(this); } };
    window.__resumeCalls = 0;
    const rs = AC.prototype.resume; AC.prototype.resume = function (...a) { window.__resumeCalls++; return rs.apply(this, a); };
  });
  const page = await ctx.newPage();
  const logs = [];
  page.on("console", (m) => logs.push(`${m.type()}: ${m.text()}`));
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(url);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);
  return { page, logs, send: (m) => sock.send(JSON.stringify(m)) };
}
const state = (page) => page.evaluate(() => window.__ctxs[0]?.state);
const tone = (sec) => { const n = 24000 * sec, a = new Int16Array(n); for (let i = 0; i < n; i++) a[i] = Math.sin((2 * Math.PI * 330 * i) / 24000) * 9000; return Buffer.from(a.buffer).toString("base64"); };

(async () => {
  const browser = await chromium.launch({ args: ["--autoplay-policy=document-user-activation-required"] });

  const t = await open(browser, BASE);
  const warn = t.logs.filter((l) => /THREE\.Clock|AudioContext was not allowed/i.test(l));
  check(warn.length === 0, "1. nạp trang không còn cảnh báo THREE.Clock / AudioContext chưa được phép chạy", warn.join(" | ").slice(0, 160));
  check((await t.page.evaluate(() => window.__resumeCalls)) === 0, "2. chưa chạm gì thì không gọi resume() (đó là nguồn cảnh báo AudioContext chưa được phép chạy)", String(await t.page.evaluate(() => window.__resumeCalls)));
  await t.page.mouse.click(300, 300); await t.page.waitForTimeout(400);
  await t.page.mouse.click(320, 320); await t.page.keyboard.press("Shift"); await t.page.waitForTimeout(300);
  const resumed = t.logs.filter((l) => /\[audio\] context resumed/.test(l)).length;
  check(resumed === 1, "3. chạm lần đầu → mở khoá âm thanh đúng 1 lần (nhiều lần chạm liên tiếp không resume lặp)", `${resumed} lần`);

  // lượt nói: chạy khi có tiếng, nói xong thì suspend
  t.send({ type: "stream_start" });
  t.send({ type: "pcm_chunk", data: tone(1), sample_rate: 24000, gap_ms: 0 });
  await t.page.waitForTimeout(500);
  check((await state(t.page)) === "running", "4a. đang nói → AudioContext chạy", String(await state(t.page)));
  await t.page.waitForTimeout(4500); // 0,45s đệm + 1s tiếng + thời gian chờ trước khi suspend
  check((await state(t.page)) === "suspended", "4b. nói xong → AudioContext tự suspend (không chạy nền khi im lặng)", String(await state(t.page)));
  t.send({ type: "pcm_chunk", data: tone(1), sample_rate: 24000, gap_ms: 0 });
  await t.page.waitForTimeout(700);
  check((await state(t.page)) === "running", "4c. lượt nói sau → tự chạy lại", String(await state(t.page)));
  await t.page.context().close();

  // bảng debug
  const off = await open(browser, BASE);
  check(!(await off.page.$("#perf-debug")), "5a. không có ?debug thì không có bảng debug");
  await off.page.context().close();
  const on = await open(browser, BASE + "?debug=1");
  const txt1 = await on.page.$eval("#perf-debug", (e) => e.textContent).catch(() => "");
  await on.page.waitForTimeout(1600);
  const txt2 = await on.page.$eval("#perf-debug", (e) => e.textContent).catch(() => "");
  check(/fps/i.test(txt2) && /DOM/.test(txt2) && /AudioContext/.test(txt2) && /animation/i.test(txt2), "5b. ?debug=1 → bảng hiện fps, số DOM, hoạt ảnh CSS, trạng thái AudioContext", txt2.replace(/\s+/g, " ").slice(0, 200));
  check(txt1 !== txt2, "5c. bảng tự cập nhật mỗi giây");
  await on.page.context().close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
