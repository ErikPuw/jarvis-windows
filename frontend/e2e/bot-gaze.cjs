// E2E: bot nhìn về khung chat khi nói/nghĩ, 3 chấm suy nghĩ, gật đầu khi nghe thấy tiếng.
//  - speaking/thinking: đầu quay về phía bong bóng trợ lý mới nhất (đo vị trí thật, kéo chat đi chỗ khác thì bot nhìn theo).
//  - thinking: 3 chấm hiện dần trên đầu bot (vẽ trong vùng trống phía trên canvas), speaking/listening thì không có.
//  - listening: nhìn thẳng ra người nói; mỗi khi nhận dạng giọng nói trả về kết quả (jarvis:heard) thì gật đầu một cái (nảy nhẹ, không xoay),
//    chặn dồn dập ≥ 1,5s mới gật tiếp.
// WebSocket và /api bị mock; SpeechRecognition là bản giả. Chạy: PW=<module playwright> node frontend/e2e/bot-gaze.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
  await ctx.addInitScript(() => {
    window.SpeechRecognition = class { constructor() { window.__sr = this; } start() { setTimeout(() => this.onstart && this.onstart(), 0); } stop() { this.onend && this.onend(); } abort() {} };
  });
  const page = await ctx.newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(1500);
  const emit = async (s) => { await page.evaluate((st) => window.dispatchEvent(new CustomEvent("jarvis:mascot", { detail: st })), s); await page.waitForTimeout(700); };
  const ds = () => page.$eval("#jarvis-bot", (e) => ({ look: e.dataset.look || "", gaze: (e.dataset.gaze || "").split(",").map(Number), dots: e.dataset.dots || "", nods: Number(e.dataset.nods || 0), jumps: e.dataset.idlejumps }));

  // một bong bóng trợ lý có thật để bot nhìn
  sock.send(JSON.stringify({ type: "stream_start" })); await page.waitForTimeout(150);
  sock.send(JSON.stringify({ type: "text_chunk", text: "Xin chào, tôi là JARVIS." })); await page.waitForTimeout(300);
  sock.send(JSON.stringify({ type: "stream_end" })); await page.waitForTimeout(300);

  // hướng mong đợi tính thẳng từ vị trí thật của bot và bong bóng (vector đơn vị × 0,85)
  const expected = () => page.evaluate(() => {
    const r = document.getElementById("jarvis-bot").getBoundingClientRect(), b = [...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop().getBoundingClientRect();
    const dx = (b.left + b.right) / 2 - (r.left + r.width / 2), dy = (b.top + b.bottom) / 2 - (r.top + r.height / 2), d = Math.hypot(dx, dy);
    return [(dx / d) * 0.85, (dy / d) * 0.85];
  });
  const close = (a, b) => Math.abs(a[0] - b[0]) < 0.06 && Math.abs(a[1] - b[1]) < 0.06;
  await emit("speaking");
  const sp = await ds(), e1 = await expected();
  check(sp.look === "chat" && close(sp.gaze, e1), "1a. speaking → đầu quay đúng hướng bong bóng trợ lý mới nhất", `gaze=${sp.gaze} mong đợi=${e1.map((v) => v.toFixed(2))}`);
  await page.evaluate(() => { const b = [...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop(); b.style.transform = "translateY(-300px)"; });
  await page.waitForTimeout(800);
  const sp2 = await ds(), e2 = await expected();
  check(close(sp2.gaze, e2) && sp2.gaze[1] < sp.gaze[1] - 0.2, "1b. bong bóng bị đẩy lên cao → bot ngước theo", `${sp.gaze} → ${sp2.gaze} (mong đợi ${e2.map((v) => v.toFixed(2))})`);
  await page.evaluate(() => { const b = [...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop(); b.style.transform = "translateX(500px) translateY(200px)"; });
  await page.waitForTimeout(800);
  const sp3 = await ds(), e3 = await expected();
  check(close(sp3.gaze, e3) && sp3.gaze[1] > sp.gaze[1] + 0.3, "1c. bong bóng dời xuống thấp (và sang phải) → bot nhìn theo, cúi xuống", `${sp.gaze} → ${sp3.gaze} (mong đợi ${e3.map((v) => v.toFixed(2))})`);
  await page.evaluate(() => { document.querySelectorAll("#chat-history .chat-bubble").forEach((b) => (b.style.transform = "")); });

  // 3 chấm suy nghĩ: vùng trống phía trên đầu bot (mười mấy px trên cùng của canvas)
  const topInk = () => page.$eval("#jarvis-bot canvas", (c) => {
    const g = c.getContext("2d", { willReadFrequently: true }), dpr = c.width / 48, d = g.getImageData(0, 0, c.width, Math.round(8 * dpr)).data;
    let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 60) n++; return n;
  });
  await emit("thinking");
  const th = await ds();
  const inks = []; for (let i = 0; i < 8; i++) { inks.push(await topInk()); await page.waitForTimeout(150); }
  check(th.look === "chat" && th.dots === "1" && inks.every((n) => n > 8), "2a. thinking → nhìn chat, 3 chấm hiện trên đầu (luôn có ít nhất 1 chấm)", `${th.look} dots=${th.dots} ink=${inks}`);
  check(new Set(inks).size >= 2, "2b. các chấm hiện dần (số điểm ảnh đổi theo nhịp 1→2→3)", `ink=${inks}`);
  await emit("speaking");
  check((await topInk()) === 0 && (await ds()).dots === "", "2c. speaking → không còn chấm", String(await topInk()));
  await emit("listening");
  const li = await ds();
  check(/^front/.test(li.look) && li.dots === "" && (await topInk()) === 0, "3a. listening → nhìn thẳng ra người nói, không chấm", JSON.stringify(li));

  // gật đầu khi nghe thấy tiếng (kết quả nhận dạng giọng nói, tạm hoặc cuối)
  await page.evaluate(() => document.getElementById("btn-mute").click()); // bật mic → voiceInput.start()
  await page.waitForTimeout(400);
  await emit("listening");
  const heard = (final = false) => page.evaluate((f) => window.__sr.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: "xin" }], { isFinal: f })] }), final);
  const n0 = (await ds()).nods;
  await heard(); await page.waitForTimeout(100); await heard(); await page.waitForTimeout(100); await heard();
  const n1 = (await ds()).nods;
  check(n1 === n0 + 1, "4a. nghe thấy tiếng (3 kết quả dồn dập) → gật đầu đúng 1 lần", `${n0} → ${n1}`);
  await page.waitForTimeout(1700); await heard();
  const n2 = (await ds()).nods;
  check(n2 === n1 + 1, "4b. 1,7s sau nghe tiếp → gật thêm một lần", `${n1} → ${n2}`);
  await emit("thinking"); await page.waitForTimeout(1700); await heard();
  check((await ds()).nods === n2, "4c. không phải đang nghe (đang nghĩ) thì không gật", String((await ds()).nods));

  // nhập liệu: thấy gõ vào ô lệnh thì nhìn xuống ô (xuống-trái / xuống / xuống-phải), ngừng gõ 3s thì quay lại như cũ
  await emit("listening");
  await page.click("#command-input");
  await page.keyboard.type("ab", { delay: 80 });
  await page.waitForTimeout(300);
  const ty = await page.$eval("#jarvis-bot", (e) => ({ look: e.dataset.look, typing: e.dataset.typing || "" }));
  check(/^down/.test(ty.look) && ty.typing === "1", "5a. đang gõ vào ô lệnh (nghe) → bot nhìn xuống ô nhập", JSON.stringify(ty));
  const seen = new Set();
  for (let i = 0; i < 9; i++) { await page.keyboard.type("x", { delay: 10 }); seen.add(await page.$eval("#jarvis-bot", (e) => e.dataset.look)); await page.waitForTimeout(700); }
  check(["down-left", "down", "down-right"].every((d) => seen.has(d)), "5b. khi gõ: đổi giữa xuống-trái, xuống, xuống-phải", [...seen].join(","));
  await page.waitForTimeout(3300);
  const after = await page.$eval("#jarvis-bot", (e) => ({ look: e.dataset.look, typing: e.dataset.typing || "" }));
  check(/^front/.test(after.look) && after.typing === "", "5c. ngừng gõ 3s → quay lại nhìn thẳng (listening)", JSON.stringify(after));
  await emit("thinking");
  await page.keyboard.type("y", { delay: 10 }); await page.waitForTimeout(300);
  check((await ds()).look === "chat", "5d. đang nghĩ mà gõ → vẫn nhìn khung chat (chỉ idle/listening mới nhìn xuống ô)", (await ds()).look);

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
