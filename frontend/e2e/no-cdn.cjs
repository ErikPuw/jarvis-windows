// E2E: trang không gọi CDN bên thứ ba lúc nạp (trước đây index.html nạp hls.js từ cdn.jsdelivr.net ở MỌI lần mở trang,
// dù chỉ dùng khi phát luồng .m3u8; Edge báo "Tracking Prevention blocked access to storage"). hls.js giờ là gói npm,
// chỉ được tải khi thật sự phát luồng HLS. WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/no-cdn.cjs
const { chromium } = require(process.env.PW || "playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  check(!/<script[^>]+src=["']https?:/i.test(html) && !/<link[^>]+href=["']https?:\/\/(?!localhost)/i.test(html), "1. index.html không còn script/link tới máy chủ bên ngoài");

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const reqs = [];
  page.on("request", (r) => reqs.push(r.url()));
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/fake/**", (r) => r.fulfill({ status: 200, contentType: "application/vnd.apple.mpegurl", body: "#EXTM3U\n" }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);
  const external = reqs.filter((u) => /^https?:/.test(u) && !/^https?:\/\/(localhost|127\.0\.0\.1)[:/]/.test(u));
  check(external.length === 0, "2. nạp trang không gọi máy chủ bên ngoài nào", external.slice(0, 3).join(" "));
  check(!reqs.some((u) => /hls/i.test(u)), "3. chưa phát luồng thì chưa tải hls.js");

  sock.send(JSON.stringify({ type: "media_open", query: "iptv", title: "Kênh thử", embed_url: BASE + "fake/stream.m3u8" }));
  await page.waitForTimeout(2500);
  const native = await page.evaluate(() => { const v = document.getElementById("iptv-video"); return !!v && !!v.src; });
  const loaded = reqs.some((u) => /hls/i.test(u));
  check(loaded || native, "4. phát luồng .m3u8 → hls.js được tải lúc đó (hoặc dùng HLS gốc của trình duyệt)", `hls.js tải=${loaded} gốc=${native}`);

  // trình duyệt không có HLS gốc (Chrome/Edge cũ, Firefox): hls.js phải được tải theo yêu cầu và chạy được
  const p2 = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await p2.addInitScript(() => { HTMLMediaElement.prototype.canPlayType = () => ""; });
  const reqs2 = []; const errs = [];
  p2.on("request", (r) => reqs2.push(r.url())); p2.on("pageerror", (e) => errs.push(e.message));
  let sock2 = null;
  await p2.routeWebSocket(/\/ws/, (ws) => { sock2 = ws; });
  await p2.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await p2.route("**/fake/**", (r) => r.fulfill({ status: 200, contentType: "application/vnd.apple.mpegurl", body: "#EXTM3U\n" }));
  await p2.goto(BASE);
  for (let i = 0; i < 50 && !sock2; i++) await p2.waitForTimeout(100);
  await p2.waitForTimeout(1200);
  const before = reqs2.some((u) => /hls/i.test(u));
  sock2.send(JSON.stringify({ type: "media_open", query: "iptv", title: "Kênh thử", embed_url: BASE + "fake/stream.m3u8" }));
  await p2.waitForTimeout(3000);
  check(!before && reqs2.some((u) => /hls/i.test(u)) && errs.length === 0, "5. không có HLS gốc: hls.js chỉ tải lúc phát luồng và chạy không lỗi", `trước=${before} sau=${reqs2.some((u) => /hls/i.test(u))} lỗi=${errs.join("|").slice(0, 80)}`);
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
