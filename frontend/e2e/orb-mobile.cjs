// E2E: orb dùng 1000 hạt trên cả điện thoại lẫn máy tính, canvas vẫn 1080px cao.
// Đếm số hạt qua gl.drawArrays(POINTS). Chạy: PW=<module playwright> node frontend/e2e/orb-mobile.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function probe(browser, opts) {
  const ctx = await browser.newContext(opts);
  await ctx.addInitScript(() => {
    window.__n = 0;
    for (const C of [window.WebGL2RenderingContext, window.WebGLRenderingContext]) {
      const d = C.prototype.drawArrays;
      C.prototype.drawArrays = function (m, f, n) { if (m === 0 && this.canvas.id === "orb-canvas") window.__n = Math.max(window.__n, n); return d.call(this, m, f, n); };
    }
  });
  const page = await ctx.newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  const r = await page.evaluate(() => ({ n: window.__n, h: document.getElementById("orb-canvas").height, ih: innerHeight, dpr: devicePixelRatio }));
  await ctx.close();
  return r;
}

(async () => {
  const browser = await chromium.launch();
  const ph = await probe(browser, { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  check(ph.n === 1000, "1. điện thoại: 1000 hạt", String(ph.n));
  check(ph.h === 1080, "2. điện thoại: canvas vẫn 1080px cao", String(ph.h));
  const pc = await probe(browser, { viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });
  check(pc.n === 1000 && pc.h === 1080, "3. máy tính: 1000 hạt, canvas 1080px", `${pc.n} / ${pc.h}`);
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
