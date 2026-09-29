// Vanilla port of nilbuild/page-mascot (MIT, https://github.com/nilbuild/page-mascot):
// head follows the pointer, click = reaction. Added: reacts to JARVIS state via
// the "jarvis:mascot" event (detail = orb state or "error").
const DIRECTIONS = ["up-left", "up", "up-right", "left", "center", "right", "down-left", "down", "down-right"];
const REACTIONS = ["blink", "heart", "sparkle", "surprised", "wink", "bashful", "sleepy", "dizzy", "delighted"];
const CLOCKWISE = ["right", "down-right", "down", "down-left", "left", "up-left", "up", "up-right"];
const SECTOR = (Math.PI * 2) / CLOCKWISE.length;
const HYSTERESIS = 0.12;
const DEAD_ZONE = 40; // original 70 is for a 140px mascot
const PAYOFFS = ["heart", "sparkle", "delighted"];
const SQUASH: Keyframe[] = [
  { transform: "scale(1, 1)", easing: "ease-in" },
  { transform: "scale(1.10, 0.86)", offset: 0.18, easing: "ease-out" },
  { transform: "scale(0.95, 1.08)", offset: 0.45, easing: "ease-in-out" },
  { transform: "scale(1.03, 0.97)", offset: 0.72, easing: "ease-in-out" },
  { transform: "scale(1, 1)" },
];
// Face held while JARVIS is in a state; null = free (follow pointer + blink).
const MOOD_FACE: Record<string, string | null> = {
  working: "sparkle", speaking: "delighted", restarting: "dizzy", error: "dizzy",
};
const SLEEP_AFTER_MS = 60_000;

const cell = (i: number) => `${(i % 3) * 50}% ${Math.floor(i / 3) * 50}%`;
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));

export function mountMascot(host: HTMLElement, name = "fox") {
  const btn = document.createElement("button");
  btn.id = "jarvis-mascot";
  btn.type = "button";
  btn.setAttribute("aria-label", "JARVIS mascot");
  btn.innerHTML = `<span class="mascot-squash"><span class="mascot-layer mascot-dir"></span><span class="mascot-layer mascot-react"></span></span>`;
  const squash = btn.firstElementChild as HTMLElement;
  const dir = btn.querySelector(".mascot-dir") as HTMLElement;
  const react = btn.querySelector(".mascot-react") as HTMLElement;
  dir.style.backgroundImage = `url(/mascots/${name}-directions.webp)`;
  react.style.backgroundImage = `url(/mascots/${name}-reactions.webp)`;
  host.appendChild(btn);

  let direction = "center";
  let boopFace: string | null = null; // click reaction, beats mood
  let mood = "idle";
  let sleepy = false;
  const render = () => {
    const face = boopFace ?? MOOD_FACE[mood] ?? (sleepy ? "sleepy" : null);
    const look = mood === "thinking" && !face ? "up-left" : direction;
    dir.style.backgroundPosition = cell(DIRECTIONS.indexOf(look));
    dir.style.opacity = face ? "0" : "1";
    react.style.backgroundPosition = cell(REACTIONS.indexOf(face ?? "blink"));
    react.style.opacity = face ? "1" : "0";
  };

  let timers: number[] = [];
  const later = (ms: number, face: string | null) => timers.push(window.setTimeout(() => { boopFace = face; render(); }, ms));
  const clearTimers = () => { timers.forEach(clearTimeout); timers = []; };

  let sleepTimer = 0;
  const armSleep = () => {
    clearTimeout(sleepTimer);
    sleepy = false;
    if (mood === "idle") sleepTimer = window.setTimeout(() => { sleepy = true; render(); }, SLEEP_AFTER_MS);
  };

  window.addEventListener("jarvis:mascot", (e) => {
    mood = String((e as CustomEvent).detail);
    btn.dataset.mood = mood;
    armSleep();
    render();
  });

  // Idle blink every 4–7s while nothing else holds the face.
  const blink = () => {
    if (!boopFace && !MOOD_FACE[mood] && !sleepy && !document.hidden) {
      boopFace = "blink"; render(); later(140, null);
    }
    window.setTimeout(blink, 4000 + Math.random() * 3000);
  };
  window.setTimeout(blink, 4000);

  if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    let sector = -1;
    window.addEventListener("pointermove", (ev) => {
      if (sleepy) armSleep();
      const box = btn.getBoundingClientRect();
      const dx = ev.clientX - (box.left + box.width / 2);
      const dy = ev.clientY - (box.top + box.height / 2);
      if (Math.hypot(dx, dy) < DEAD_ZONE) { sector = -1; direction = "center"; render(); return; }
      const angle = Math.atan2(dy, dx);
      if (sector !== -1 && Math.abs(wrap(angle - sector * SECTOR)) < SECTOR / 2 + HYSTERESIS) return;
      sector = (Math.round(angle / SECTOR) + CLOCKWISE.length) % CLOCKWISE.length;
      direction = CLOCKWISE[sector];
      render();
    }, { passive: true });
  }

  const boops = { count: 0, at: 0 };
  btn.addEventListener("click", () => {
    clearTimers();
    armSleep();
    const now = Date.now();
    boops.count = now - boops.at < 1600 ? boops.count + 1 : 1;
    boops.at = now;
    if (boops.count >= 4) {
      boops.count = 0;
      boopFace = "dizzy"; later(1100, null);
    } else {
      boopFace = "blink";
      later(120, PAYOFFS[(boops.count - 1) % PAYOFFS.length]);
      later(560, null);
    }
    render();
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      squash.animate(SQUASH, { duration: 420, easing: "linear" });
    }
  });

  armSleep();
  render();
}
