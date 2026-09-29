// E2E cho command-hub giai đoạn 1: beam trên thanh lệnh, orb trạng thái, nút mới, viền kim loại nút gửi.
// WebSocket và /api bị mock — không chạm JARVIS thật.
// Chạy: PW=<module playwright> node frontend/e2e/command-hub.cjs   (cần `npm run dev` ở :5173)
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
  await page.waitForTimeout(500);
  return { page, send: (m) => sock.send(JSON.stringify(m)) };
}

(async () => {
  const browser = await chromium.launch();
  const { page, send } = await open(browser);

  // 1. orb trạng thái
  const orb = await page.waitForSelector("#status-orb canvas", { timeout: 5000 }).catch(() => null);
  check(!!orb, "1a. có #status-orb canvas");
  if (!orb) { await browser.close(); process.exit(1); }
  const painted = () => page.$eval("#status-orb canvas", (c) => { const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) return true; return false; });
  await page.waitForTimeout(300);
  check(await painted(), "1b. orb có vẽ điểm ảnh");
  const size = await page.$eval("#status-orb", (e) => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; });
  check(size[0] >= 24 && size[0] <= 32, "1c. orb cỡ 24–32px", size.join("x"));

  // 2. trạng thái JARVIS → trạng thái orb + nhãn tiếng Việt
  const st = async (state) => { send({ type: "status", state }); await page.waitForTimeout(250); return page.evaluate(() => [document.getElementById("status-orb").dataset.orb, document.getElementById("status-text").textContent]); };
  // mic starts muted; "listening" comes from turning the mic on, not from a ws message
  await page.click("#btn-mute");
  await page.waitForTimeout(250);
  const [lo, lt] = await page.evaluate(() => [document.getElementById("status-orb").dataset.orb, document.getElementById("status-text").textContent]);
  check(lo === "listening" && lt === "Đang nghe…", '2. mở mic → orb listening, nhãn "Đang nghe…"', `${lo} / ${lt}`);
  const cases = [["thinking", "connecting", "Đang nghĩ…"], ["working", "solving", "Đang làm việc…"], ["speaking", "composing", "Đang trả lời…"]];
  for (const [jarvis, orbState, label] of cases) {
    const [o, t] = await st(jarvis);
    check(o === orbState && t === label, `2. ${jarvis} → orb ${orbState}, nhãn "${label}"`, `${o} / ${t}`);
  }
  await page.click("#btn-mute"); // tắt mic lại → idle không chuyển thành listening
  const [io, it] = await st("idle");
  check(io === "working" && it === "Sẵn sàng", "2e. idle → orb working (chậm), nhãn 'Sẵn sàng'", `${io} / ${it}`);
  const slow = await page.$eval("#status-orb", (e) => e.dataset.speed);
  check(parseFloat(slow) < 1, "2f. idle chạy chậm hơn", slow);

  // 2i. đổi trạng thái → các chấm bay sang hình mới (biến hình), không đập hình khác vào
  await st("thinking"); await page.waitForTimeout(900); // ổn định
  send({ type: "status", state: "working" });
  await page.waitForTimeout(150);
  const morphing = await page.$eval("#status-orb", (e) => e.dataset.morph || "");
  await page.waitForTimeout(1200);
  const settled = await page.$eval("#status-orb", (e) => e.dataset.morph || "");
  check(morphing === "1" && settled === "", "2i. đổi trạng thái → orb biến hình rồi ổn định", `${morphing || "-"} → ${settled || "-"}`);
  const blend = await page.evaluate(async () => {
    const m = await import("/src/status-orb.ts");
    const D = (x, y) => ({ x, y, z: 0, r: 2, white: 0.5, a: 1 });
    const A = { dots: [D(16, 6), D(16, 26)], lines: [] }, B = { dots: [D(6, 16), D(26, 16), D(16, 6)], lines: [] };
    const pos = (f) => f.dots.map((d) => `${Math.round(d.x)},${Math.round(d.y)}`).sort().join(" ");
    const f0 = m.blendFrames(A, B, 0, 32), f1 = m.blendFrames(A, B, 1, 32), fh = m.blendFrames(A, B, 0.5, 32);
    return { p0: pos(f0), pA: pos(A), p1: pos(f1), pB: pos(B), nh: fh.dots.length, extraFade: Math.min(...fh.dots.map((d) => d.a ?? 1)) };
  }).catch((e) => ({ err: String(e) }));
  check(blend.p0 === blend.pA && blend.p1 === blend.pB && blend.nh === 3 && blend.extraFade < 0.9, "2j. blendFrames: k=0 là hình cũ, k=1 là hình mới, giữa chừng chấm dư mờ dần", JSON.stringify(blend));

  // 2g. hàng trạng thái nằm trong luồng, giữa khung chat và thanh lệnh — không bị đè
  await page.evaluate(() => { const h = document.getElementById("chat-history"); for (let i = 0; i < 6; i++) { const d = document.createElement("div"); d.className = "chat-bubble assistant"; d.textContent = "tin nhắn " + i; h.appendChild(d); } });
  await st("thinking");
  const lay = await page.evaluate(() => {
    const row = document.getElementById("status-row"), bar = document.getElementById("command-bar").getBoundingClientRect();
    if (!row) return null;
    const r = row.getBoundingClientRect();
    const hist = document.getElementById("chat-history").getBoundingClientRect();
    return { inside: !!row.closest("#command-container"), aboveBar: r.bottom <= bar.top + 1, belowChat: r.top >= hist.bottom - 1, textGap: Math.round(bar.top - document.getElementById("status-text").getBoundingClientRect().bottom) };
  });
  check(lay && lay.inside && lay.aboveBar && lay.belowChat && lay.textGap >= 0, "2g. hàng trạng thái nằm giữa khung chat và thanh lệnh, không đè", JSON.stringify(lay));

  // 2h. thanh lệnh ẩn: orb + nhãn vẫn hiện (chỉ khung chat và thanh lệnh mờ đi)
  await page.evaluate(() => document.getElementById("command-container").classList.remove("visible"));
  await page.waitForTimeout(700);
  const hid = await page.evaluate(() => {
    const orb = document.getElementById("status-orb"), txt = document.getElementById("status-text");
    const chain = (el) => { let o = 1; for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
    const r = orb.getBoundingClientRect();
    return { orb: chain(orb), text: chain(txt), w: Math.round(r.width), label: txt.textContent, bar: parseFloat(getComputedStyle(document.getElementById("command-bar")).opacity), onscreen: r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth };
  });
  check(hid.orb > 0.95 && hid.text > 0.5 && hid.w >= 24 && hid.onscreen && hid.label && hid.bar < 0.05, "2h. thanh lệnh ẩn: orb và nhãn vẫn hiện, thanh lệnh mờ", JSON.stringify(hid));
  await page.evaluate(() => document.getElementById("command-container").classList.add("visible"));
  await page.waitForTimeout(500);

  // 3. beam trên thanh lệnh
  await st("thinking");
  const beam = await page.$eval("#command-bar-inner .cmd-beam", (e) => { const cs = getComputedStyle(e); return { anim: cs.animationName, op: parseFloat(cs.opacity) }; }).catch(() => null);
  check(beam && beam.anim !== "none" && beam.op >= 0.8, "3a. nghĩ → beam chạy rõ", JSON.stringify(beam));
  await st("idle"); // still muted, so idle stays idle
  await page.waitForTimeout(700); // opacity transition (0.5s)
  const faint = await page.$eval("#command-bar-inner .cmd-beam", (e) => parseFloat(getComputedStyle(e).opacity)).catch(() => 1);
  check(faint > 0 && faint <= 0.4, "3b. rảnh → beam mờ", String(faint));

  // 3c. viền thanh lệnh vẫn còn rõ (vệt beam chạy đè lên viền, không thay viền)
  const border = await page.evaluate(() => {
    const cs = getComputedStyle(document.getElementById("command-bar-inner"));
    return { w: cs.borderTopWidth, a: (cs.borderTopColor.match(/rgba?\(([^)]+)\)/)?.[1].split(",").map(Number)[3]) ?? 1 };
  });
  check(border.w === "1px" && border.a >= 0.2, "3c. viền thanh lệnh vẫn còn rõ", JSON.stringify(border));

  // 4. nút mới
  await page.evaluate(() => { const i = document.getElementById("command-input"); i.value = ""; });
  await page.click("#btn-slash");
  const v1 = await page.$eval("#command-input", (i) => [i.value, document.activeElement === i]);
  check(v1[0] === "/" && v1[1], "4a. nút / chèn '/' và focus", JSON.stringify(v1));
  await page.evaluate(() => { document.getElementById("command-input").value = ""; });
  await page.click("#btn-mention");
  const v2 = await page.$eval("#command-input", (i) => i.value);
  check(v2 === "@", "4b. nút @ chèn '@'", v2);
  check(!(await page.$("#btn-cmd-mic")), "4c. đã bỏ nút mic trong thanh lệnh (mic đã ở hàng nút trên cùng, gần nút gửi)");
  check(!!(await page.$("#btn-slash morph-icon")) && !!(await page.$("#btn-mention morph-icon")), "4d. nút / và @ dùng morphicons");
  check(!!(await page.$("#jarvis-mascot")), "4e. vẫn còn mascot");

  // 5. nút gửi: viền kim loại tròn, icon nằm giữa
  const ring = await page.evaluate(() => {
    const wrap = document.getElementById("cmd-send-wrap"), btn = document.getElementById("cmd-send");
    if (!wrap || !btn) return null;
    const mi = btn.querySelector("morph-icon");
    const glyph = (mi && (mi.shadowRoot ? mi.shadowRoot.querySelector("svg") : mi.querySelector("svg"))) || mi || btn;
    const w = wrap.getBoundingClientRect(), i = glyph.getBoundingClientRect();
    return { w: Math.round(w.width), h: Math.round(w.height), dx: Math.abs(w.x + w.width / 2 - (i.x + i.width / 2)), dy: Math.abs(w.y + w.height / 2 - (i.y + i.height / 2)), radius: getComputedStyle(wrap).borderRadius, metal: wrap.dataset.metal };
  });
  check(ring && ring.w >= 28 && ring.w <= 34 && ring.w === ring.h && ring.radius.includes("50%"), "5a. vòng tròn 28–34px bao nút gửi", JSON.stringify(ring));
  check(ring && ring.dx <= 1 && ring.dy <= 1, "5b. icon máy bay giấy nằm chính giữa vòng", `${ring && ring.dx.toFixed(2)},${ring && ring.dy.toFixed(2)}`);
  check(ring && (ring.metal === "on" || ring.metal === "off"), "5c. có trạng thái shader (on/off nếu máy không hỗ trợ WebGL2)", ring && ring.metal);
  if (ring && ring.metal === "on") {
    const px = await page.$eval("#cmd-send-wrap canvas", (c) => { const g = c.getContext("webgl2") || c.getContext("webgl"); return !!g || c.width > 0; });
    check(px, "5d. canvas shader tồn tại");
  }
  await page.click("#btn-mute"); // trả lại

  // 6. giảm chuyển động → beam và orb đứng yên
  const rm = await open(browser, { reducedMotion: "reduce" });
  const rmBeam = await rm.page.$eval("#command-bar-inner .cmd-beam", (e) => getComputedStyle(e).animationName).catch(() => "");
  check(rmBeam === "none", "6. giảm chuyển động → beam đứng yên", rmBeam);
  rm.send({ type: "status", state: "working" }); await rm.page.waitForTimeout(150);
  check((await rm.page.$eval("#status-orb", (e) => e.dataset.morph || "")) === "", "6b. giảm chuyển động → orb đổi trạng thái tức thì, không biến hình");
  await rm.page.close();
  await page.close();

  // 7. mobile: các nút không tràn khỏi thanh lệnh
  const m = await open(browser, { viewport: { width: 375, height: 812 } });
  const over = await m.page.evaluate(() => {
    const bar = document.getElementById("command-bar-inner").getBoundingClientRect();
    return [...document.querySelectorAll("#command-bar-inner button, #cmd-send-wrap")].filter((b) => b.offsetParent && (b.getBoundingClientRect().right > bar.right + 1 || b.getBoundingClientRect().left < bar.left - 1)).map((b) => b.id);
  });
  check(over.length === 0, "7. mobile: nút nằm gọn trong thanh lệnh", over.join(","));
  await m.page.close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
