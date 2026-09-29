// E2E cho mascot cạnh nút gửi (port vanilla của nilbuild/page-mascot, MIT).
// Mọi /api và /ws đều bị mock — không chạm JARVIS thật.
// Chạy: PW=<module playwright> node frontend/e2e/mascot.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) failed++;
};

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true } }));
  // keys present → first-time setup does not open Settings over the bar
  await page.route("**/api/settings/status**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  const m = await page.waitForSelector("#jarvis-mascot", { timeout: 5000 }).catch(() => null);
  check(!!m, "1. có #jarvis-mascot");
  if (!m) { await browser.close(); process.exit(1); }

  await page.waitForTimeout(700); // wait out the bar show transition
  const box = await m.boundingBox();
  const send = await (await page.$("#cmd-send")).boundingBox();
  const bar = await (await page.$("#command-bar-inner")).boundingBox();
  check(box.y + box.height > bar.y + 4 && box.y + box.height <= bar.y + 22, "2a. đè lên mép trên command-bar", JSON.stringify({ box, bar }));
  check(await page.evaluate(() => { const r = document.getElementById("cmd-send").getBoundingClientRect(); const el = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return !!el && !!el.closest("#cmd-send"); }), "2c. không che nút gửi");
  check(Math.abs((box.x + box.width / 2) - (send.x + send.width / 2)) < box.width, "2b. thẳng hàng nút gửi (bên phải)");
  const imgs = await page.$$eval("#jarvis-mascot .mascot-layer", (els) => els.map((e) => getComputedStyle(e).backgroundImage));
  check(imgs.length === 2 && imgs[0].includes("fox-directions") && imgs[1].includes("fox-reactions"), "3. dùng 2 sprite fox", imgs.join(" | "));

  const pos = () => page.$eval("#jarvis-mascot .mascot-dir", (e) => e.style.backgroundPosition);
  await page.mouse.move(5, box.y + box.height / 2);
  check((await pos()) === "0% 50%", "4a. nhìn sang trái khi chuột bên trái", await pos());
  await page.mouse.move(box.x + box.width / 2, 5);
  check((await pos()) === "50% 0%", "4b. nhìn lên khi chuột phía trên", await pos());

  await page.mouse.click(box.x + box.width / 2, box.y + box.height * 0.4); // head = hit area
  const reactOpacity = await page.$eval("#jarvis-mascot .mascot-react", (e) => e.style.opacity);
  check(reactOpacity === "1", "5a. bấm → hiện biểu cảm", reactOpacity);
  await page.waitForTimeout(800);
  check((await page.$eval("#jarvis-mascot .mascot-react", (e) => e.style.opacity)) === "0", "5b. biểu cảm tự tắt");

  const mood = await page.evaluate(() => { window.dispatchEvent(new CustomEvent("jarvis:mascot", { detail: "thinking" })); return document.getElementById("jarvis-mascot").dataset.mood; });
  check(mood === "thinking", "6. nhận trạng thái JARVIS", mood);

  await page.setViewportSize({ width: 375, height: 812 });
  const mb = await m.boundingBox();
  check(mb && mb.x + mb.width <= 375, "7. mobile không tràn", JSON.stringify(mb));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
