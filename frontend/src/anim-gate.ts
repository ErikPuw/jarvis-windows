// One switch for every decorative animation loop (status orb, command-bar aura, mascot, bot in the
// bubble, send-button shader). main.ts flips it whenever something covers the screen (settings, map,
// media), the same moments the Three.js orb is paused, so a covered page costs no frames — on a phone
// the hidden loops were still drawing 60 times a second and heating it. A hidden tab stops them too.
let paused = false;
const listeners = new Set<(paused: boolean) => void>();

export const animPaused = (): boolean => paused || document.hidden;

function notify(): void { for (const f of [...listeners]) f(animPaused()); }

export function setAnimPaused(p: boolean): void {
  if (p === paused) return;
  paused = p;
  notify();
}

/** Calls `f` with the new state whenever animations are paused or resumed. */
export function onAnimGate(f: (paused: boolean) => void): void {
  listeners.add(f);
}

document.addEventListener("visibilitychange", notify);

export interface Loop { wake(): void }

/**
 * requestAnimationFrame loop that stops while animations are paused and restarts on resume. `frame`
 * gets the frame time and the (clamped) ms since its previous run; returning false puts the loop to
 * sleep until wake(). `minMs` caps the rate (e.g. 1000/30), which also keeps 120 Hz screens at 60 fps.
 */
export function gatedLoop(frame: (now: number, dt: number) => boolean | void, minMs = 1000 / 60): Loop {
  let raf = 0;
  let prev = 0;
  const tick = (now: number): void => {
    raf = 0;
    if (animPaused()) return;
    raf = requestAnimationFrame(tick);
    const dt = prev ? now - prev : 0;
    if (dt && dt < minMs - 2) return; // frame cap: skip, keep `prev`
    prev = now;
    if (frame(now, Math.min(dt, 100)) === false) { cancelAnimationFrame(raf); raf = 0; prev = 0; }
  };
  const wake = (): void => {
    if (raf || animPaused()) return;
    prev = 0;
    raf = requestAnimationFrame(tick);
  };
  onAnimGate((p) => { if (!p) wake(); });
  wake();
  return { wake };
}
