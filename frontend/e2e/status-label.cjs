// E2E cho chữ trạng thái: trượt mờ theo hướng khi đổi, cuộn vào sau 10s rảnh (CHỈ idle: hệ thống đã trả lời xong, mic tắt), cuộn ra khi có việc.
// Mọi trạng thái đang hoạt động (đang nghe, nghĩ, làm việc, nói) luôn hiện chữ, không tự mờ.
// Đồng hồ giả của Playwright (page.clock) để không phải chờ 10s thật; WebSocket và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/status-label.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) failed++;
};

async function open(browser, opts = {}) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, ...opts });
  await page.clock.install();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(300);
  const send = (state) => sock.send(JSON.stringify({ type: "status", state }));
  const quiet = () => page.$eval("#status-row", (r) => r.classList.contains("quiet"));
  const label = () => page.$eval("#status-text", (e) => { const cs = getComputedStyle(e); return { w: parseFloat(cs.maxWidth) || 0, op: parseFloat(cs.opacity), text: e.textContent }; });
  return { page, send, quiet, label };
}

(async () => {
  const browser = await chromium.launch();
  const { page, send, quiet, label } = await open(browser);

  // 1. đổi chữ: chữ cũ trượt ra (ghost), chữ mới trượt vào, theo hướng bận hơn / nhàn hơn
  send("thinking"); await page.waitForTimeout(400);
  send("working"); await page.waitForTimeout(60);
  const up = await page.evaluate(() => {
    const g = document.querySelector("#status-row .status-ghost"), l = document.getElementById("status-text");
    const w = l.getAnimations().filter((a) => a.constructor.name === "Animation"); // bỏ shimmer + CSS transition có sẵn
    const kf = w[0]?.effect?.getKeyframes()[0];
    return { ghost: g?.textContent, anims: w.length, from: kf?.transform };
  });
  check(up.ghost === "Đang nghĩ…" && up.anims >= 1, "1a. đổi chữ: có chữ cũ đang trượt ra + chữ mới trượt vào", JSON.stringify(up));
  check(String(up.from).includes("8px") && !String(up.from).includes("-8px"), "1b. lên trạng thái bận hơn → chữ mới trồi từ dưới lên", String(up.from));
  send("idle"); await page.waitForTimeout(60); // ngay sau "làm việc": app có thể tự về Sẵn sàng nếu chờ lâu
  const down = await page.evaluate(() => document.getElementById("status-text").getAnimations().filter((a) => a.constructor.name === "Animation").pop()?.effect?.getKeyframes()[0]?.transform);
  check(String(down).includes("-8px"), "1d. về trạng thái nhàn hơn → chữ mới trồi từ trên xuống", String(down));
  await page.waitForTimeout(500);
  check(!(await page.$("#status-row .status-ghost")), "1c. chữ cũ được dọn sau khi trượt xong");

  // 2. rảnh 10s → chữ cuộn vào, orb ở lại nhưng mờ
  await page.waitForTimeout(500);
  await page.clock.fastForward(8000);
  check(!(await quiet()), "2a. chưa đủ 10s → chữ vẫn hiện");
  await page.clock.fastForward(3000);
  await page.waitForTimeout(700); // CSS transition chạy theo giờ thật
  const l = await label();
  const orbOp = await page.$eval("#status-orb", (e) => parseFloat(getComputedStyle(e).opacity));
  check((await quiet()) && l.w === 0 && l.op < 0.05, "2b. sau 10s rảnh → chữ cuộn vào (thu về 0, mờ)", JSON.stringify(l));
  check(orbOp < 0.6 && orbOp > 0.2, "2c. orb ở lại, mờ hơn", String(orbOp));

  // 3. có việc → chữ cuộn ra ngay
  send("thinking"); await page.waitForTimeout(700);
  const l2 = await label();
  check(!(await quiet()) && l2.w > 40 && l2.op > 0.9 && l2.text === "Đang nghĩ…", "3a. có việc → chữ cuộn ra", JSON.stringify(l2));
  await page.clock.fastForward(30000);
  check(!(await quiet()), "3b. đang bận thì không bao giờ cuộn vào");

  // 4. đang nghe (mic bật) là trạng thái hoạt động: chữ hiện mãi; tắt mic về idle thì 10s sau mới cuộn vào
  send("idle"); await page.waitForTimeout(200);
  await page.click("#btn-mute"); await page.waitForTimeout(300);
  check((await label()).text === "Đang nghe…", "4a. bật mic → Đang nghe…");
  await page.clock.fastForward(30000); await page.waitForTimeout(700);
  const ln = await label();
  check(!(await quiet()) && ln.w > 40 && ln.op > 0.9 && ln.text === "Đang nghe…", "4b. đang nghe, im lặng 30s → chữ VẪN hiện (không tự mờ)", JSON.stringify(ln));
  await page.click("#btn-mute"); await page.waitForTimeout(300);
  check((await label()).text === "Sẵn sàng", "4c. tắt mic → Sẵn sàng (idle)");
  await page.clock.fastForward(10500); await page.waitForTimeout(700);
  check(await quiet(), "4d. idle 10s → chữ cuộn vào");

  // 5. gõ phím hoặc bấm chuột → cuộn ra và đếm lại
  await page.keyboard.press("Shift"); await page.waitForTimeout(700);
  check(!(await quiet()) && (await label()).w > 40, "5a. gõ phím → chữ cuộn ra");
  await page.clock.fastForward(8000);
  check(!(await quiet()), "5b. đếm lại 10s từ lần thao tác cuối");
  await page.clock.fastForward(3000); await page.waitForTimeout(300);
  check(await quiet(), "5c. đủ 10s sau thao tác cuối → cuộn vào lại");
  await page.close();

  // 6. giảm chuyển động: không trượt, vẫn ẩn/hiện (tức thì)
  const rm = await open(browser, { reducedMotion: "reduce" });
  rm.send("thinking"); await rm.page.waitForTimeout(300);
  rm.send("working"); await rm.page.waitForTimeout(60);
  const still = await rm.page.evaluate(() => ({ ghost: !!document.querySelector(".status-ghost"), anims: document.getElementById("status-text").getAnimations().filter((a) => a.constructor.name === "Animation").length }));
  check(!still.ghost && still.anims === 0, "6a. giảm chuyển động: đổi chữ tức thì, không trượt", JSON.stringify(still));
  rm.send("idle"); await rm.page.waitForTimeout(100);
  await rm.page.clock.fastForward(10500); await rm.page.waitForTimeout(150);
  const rl = await rm.label();
  check((await rm.quiet()) && rl.w === 0, "6b. giảm chuyển động: vẫn ẩn chữ khi rảnh 10s (tức thì)", JSON.stringify(rl));
  await rm.page.close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
