// E2E cho bong bóng chat có avatar bot `square` (src/bubble-avatar.ts). WebSocket giả phát các lượt chat.
// Chạy: PW=<module playwright> node frontend/e2e/bubbles.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) failed++;
};

async function open(browser, opts = {}) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, ...opts });
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(400);
  return { page, send: (m) => sock.send(JSON.stringify(m)) };
}
const painted = (page, sel) => page.$eval(sel, (c) => { const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) return true; return false; });

(async () => {
  const browser = await chromium.launch();
  const { page, send } = await open(browser);

  // 1. lượt stream: bong bóng có avatar + tên
  send({ type: "stream_start" });
  await page.waitForSelector(".chat-bubble.assistant .bubble-avatar canvas", { timeout: 4000 }).catch(() => {});
  check(!!(await page.$(".chat-bubble.assistant .bubble-avatar canvas")), "1a. bong bóng đang stream có avatar");
  check((await page.textContent(".chat-bubble.assistant .bubble-name").catch(() => "")) === "JARVIS", "1b. tên mặc định JARVIS");
  await page.waitForTimeout(300);
  check(await painted(page, ".chat-bubble.assistant .bubble-avatar canvas").catch(() => false), "1c. avatar có vẽ điểm ảnh");
  const box = await page.$eval(".chat-bubble.assistant .bubble-avatar", (e) => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }).catch(() => [0, 0]);
  check(box[0] >= 26 && box[0] <= 34 && box[0] === box[1], "1d. avatar vuông 26–34px", box.join("x"));

  // 2. trạng thái avatar theo trạng thái JARVIS (chỉ avatar mới nhất chạy)
  const av = () => page.$eval(".chat-bubble.assistant:last-of-type .bubble-avatar", (e) => e.dataset.state).catch(() => null);
  await page.click("#btn-mute"); await page.waitForTimeout(250); // mic mặc định tắt; bật = nghe
  check((await av()) === "sleeping", "2a. nghe/rảnh → bot ngủ", await av());
  send({ type: "status", state: "thinking" }); await page.waitForTimeout(250);
  check((await av()) === "working", "2b. nghĩ → bot làm việc", await av());
  send({ type: "status", state: "speaking" }); await page.waitForTimeout(250);
  check((await av()) === "default", "2c. nói → bot bình thường", await av());

  // 3. tên agent lấy từ thẻ agent của lượt này; thẻ agent không có avatar
  send({ type: "interactive", card: { id: "t1", type: "tracker", title: "💻 Agent Desktop", status: "active", label: "Thực thi: mở Task Manager" } });
  await page.waitForTimeout(300);
  check((await page.textContent(".chat-bubble.assistant .bubble-name")) === "Agent Desktop", "3a. tên bong bóng = agent của lượt", await page.textContent(".chat-bubble.assistant .bubble-name"));
  const cardHasAvatar = await page.$eval('[data-card-id="t1"]', (e) => !!e.closest(".chat-bubble").querySelector(".bubble-avatar"));
  check(!cardHasAvatar, "3b. thẻ agent không có avatar");

  // 4. text chunk + stream_end: avatar/tên không bị xoá khi nội dung thay
  send({ type: "text_chunk", text: "Tôi đã mở Task Manager thành công, thưa Ngài." });
  send({ type: "stream_end" });
  await page.waitForTimeout(900);
  const kept = await page.evaluate(() => { const b = [...document.querySelectorAll(".chat-bubble.assistant.has-head")].pop(); return { av: !!b.querySelector(".bubble-avatar canvas"), name: !!b.querySelector(".bubble-name"), text: b.querySelector(".bubble-text")?.textContent || "" }; });
  check(kept.av && kept.name && kept.text.includes("Task Manager"), "4. sau khi nhận chữ, avatar + tên + nội dung đều còn", JSON.stringify(kept));

  // 5. lượt thứ hai: chỉ avatar mới nhất chạy, avatar cũ đứng yên
  send({ type: "stream_start" });
  await page.waitForTimeout(500);
  const live = await page.$$eval(".bubble-avatar", (els) => els.map((e) => e.dataset.live).join(","));
  check(live === "0,1", "5a. avatar cũ đóng băng, chỉ avatar mới nhất chạy", live);
  check(await painted(page, ".chat-bubble.assistant.has-head .bubble-avatar canvas"), "5b. avatar cũ vẫn hiện hình (khung tĩnh)");

  // 6. đường text (không stream) cũng có avatar
  send({ type: "text", text: "Tôi ở đây, thưa Ngài." });
  await page.waitForTimeout(900);
  const textBubble = await page.evaluate(() => { const b = [...document.querySelectorAll(".chat-bubble.assistant.has-head")].pop(); return { av: !!b.querySelector(".bubble-avatar canvas"), name: b.querySelector(".bubble-name")?.textContent, has: b.textContent.includes("Tôi ở đây") }; });
  check(textBubble.av && textBubble.has, "6. tin nhắn dạng text cũng có avatar", JSON.stringify(textBubble));

  // 7. bố cục: avatar nằm trong khung chat, bong bóng có đuôi góc trái trên
  const lay = await page.evaluate(() => {
    const h = document.getElementById("chat-history").getBoundingClientRect();
    const b = [...document.querySelectorAll(".chat-bubble.assistant.has-head")].pop();
    const a = b.querySelector(".bubble-avatar").getBoundingClientRect(), br = b.getBoundingClientRect(), cs = getComputedStyle(b);
    return { inside: a.left >= h.left - 1, gap: Math.round(br.left - a.right), tl: cs.borderTopLeftRadius, tr: cs.borderTopRightRadius };
  });
  check(lay.inside && lay.gap >= 4 && lay.gap <= 14, "7a. avatar nằm trong khung chat, cách bong bóng 4–14px", JSON.stringify(lay));
  check(parseFloat(lay.tl) <= 6 && parseFloat(lay.tr) >= 10, "7b. bong bóng bo góc: nhọn phía avatar", `${lay.tl} / ${lay.tr}`);

  // 8. bong bóng người dùng bo góc đối xứng ngược lại
  await page.evaluate(() => { const i = document.getElementById("command-input"); i.value = "mở task manager"; i.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  await page.waitForTimeout(400);
  const user = await page.evaluate(() => { const b = document.querySelector(".chat-bubble.user"); if (!b) return null; const cs = getComputedStyle(b); return { self: cs.alignSelf, br: cs.borderBottomRightRadius, bl: cs.borderBottomLeftRadius }; });
  check(user && user.self === "flex-end" && parseFloat(user.br) <= 6 && parseFloat(user.bl) >= 10, "8. bong bóng người dùng căn phải, nhọn góc dưới phải", JSON.stringify(user));

  // 8b. tương tác như libraries.dev/bots: nhìn theo chuột, lại gần thì nhảy tưng tưng, bấm thì nhảy vui hơn
  send({ type: "status", state: "idle" }); await page.waitForTimeout(300); // về trạng thái rảnh → bot ngủ
  const c = await page.$eval(".bubble-avatar[data-live='1']", (e) => { const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
  const ds = () => page.$eval(".bubble-avatar[data-live='1']", (e) => ({ follow: e.dataset.follow, hops: Number(e.dataset.hops || 0), awake: e.dataset.awake }));
  await page.mouse.move(c.x + 600, c.y - 40); await page.waitForTimeout(150);
  const far = await ds();
  check(far.follow === "0" && far.hops === 0 && far.awake !== "1", "8b1. chuột ở xa: bot ngủ, không nhìn theo, không nhảy", JSON.stringify(far));
  await page.mouse.move(c.x + 110, c.y - 30); await page.waitForTimeout(150);
  const mid = await ds();
  check(mid.follow === "1" && mid.hops === 0 && mid.awake === "1", "8b2. chuột lại vài bề ngang đầu: bot tỉnh dậy và nhìn theo chuột (chưa nhảy)", JSON.stringify(mid));
  await page.mouse.move(c.x + 26, c.y + 4); await page.waitForTimeout(250);
  const near1 = await ds();
  check(near1.hops >= 1, "8b3. chuột lại sát: bot nhảy mừng", JSON.stringify(near1));
  await page.waitForTimeout(1800);
  const near2 = await ds();
  check(near2.hops > near1.hops, "8b4. chuột vẫn ở gần: tiếp tục nhảy tưng tưng", `${near1.hops} → ${near2.hops}`);
  await page.mouse.move(c.x + 600, c.y - 40); await page.waitForTimeout(150);
  const gone = await ds();
  const h0 = gone.hops;
  await page.mouse.click(c.x, c.y); await page.waitForTimeout(700);
  const clicked = await ds();
  check(clicked.hops >= h0 + 2, "8b5. bấm vào bot: nhảy hai lần (vui hơn)", `${h0} → ${clicked.hops}`);
  await page.mouse.move(c.x + 600, c.y - 40);
  const frozenFollow = await page.$eval(".bubble-avatar[data-live='0']", (e) => e.dataset.follow || "").catch(() => "n/a");
  check(frozenFollow !== "1", "8b6. avatar cũ (đóng băng) không phản ứng với chuột", frozenFollow);

  // 9. giảm chuyển động: avatar vẫn hiện, không chạy vòng lặp
  const rm = await open(browser, { reducedMotion: "reduce" });
  rm.send({ type: "stream_start" });
  await rm.page.waitForSelector(".bubble-avatar canvas", { timeout: 4000 }).catch(() => {});
  await rm.page.waitForTimeout(300);
  check(await painted(rm.page, ".bubble-avatar canvas").catch(() => false), "9. giảm chuyển động: avatar vẫn vẽ (khung tĩnh)");
  const rc = await rm.page.$eval(".bubble-avatar", (e) => { const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
  await rm.page.mouse.move(rc.x + 20, rc.y); await rm.page.mouse.click(rc.x, rc.y); await rm.page.waitForTimeout(500);
  check(!(await rm.page.$eval(".bubble-avatar", (e) => Number(e.dataset.hops || 0))), "9b. giảm chuyển động: bot không nhảy khi lại gần/bấm");
  await rm.page.close();

  // 10. mobile: avatar + bong bóng nằm gọn trong khung chat
  const m = await open(browser, { viewport: { width: 375, height: 812 } });
  m.send({ type: "stream_start" });
  m.send({ type: "text_chunk", text: "Một câu trả lời đủ dài để xuống dòng trên màn hình điện thoại nhỏ, thưa Ngài." });
  m.send({ type: "stream_end" });
  await m.page.waitForTimeout(900);
  const mob = await m.page.evaluate(() => {
    const h = document.getElementById("chat-history").getBoundingClientRect();
    const b = [...document.querySelectorAll(".chat-bubble.assistant.has-head")].pop();
    const a = b.querySelector(".bubble-avatar").getBoundingClientRect(), br = b.getBoundingClientRect();
    return { l: a.left >= h.left - 1, r: br.right <= h.right + 1 };
  });
  check(mob.l && mob.r, "10. mobile: không tràn khung chat", JSON.stringify(mob));
  await m.page.close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
