// Performance panel for debugging heat/CPU, loaded only with `?debug=1` (dynamic import, so it costs nothing otherwise).
// Once a second it prints what keeps the page busy: frames per second, requestAnimationFrame calls per caller (every
// loop that is still running shows up with its own rate), long tasks, DOM size, running CSS animations, the audio
// context state, whether the animation gate has paused the decorative loops, and the JS heap. Also on `window.__perf`.
// Read it together with Edge DevTools (see README, "Debug hiệu năng").
import { animPaused } from "./anim-gate";

export interface PerfSample {
  fps: number;
  rafPerSec: number;
  rafBy: Record<string, number>;
  longTasks: number;
  longTaskMaxMs: number;
  dom: number;
  bubbles: number;
  canvases: number;
  animations: number;
  animNames: string[];
  audio: string;
  gatePaused: boolean;
  heapMB: number | null;
}

const callerOf = (stack: string | undefined): string => {
  // stack[0] = "Error", [1] = the wrapper itself, [2] = whoever called requestAnimationFrame: "at fn (http://host/src/orb.ts?t=1:154:5)"
  const line = (stack ?? "").split(String.fromCharCode(10))[2] ?? "";
  const tail = line.slice(line.lastIndexOf("/") + 1).replace(")", "");
  const parts = tail.split(":");
  const q = parts[0].indexOf("?");
  const file = q >= 0 ? parts[0].slice(0, q) : parts[0];
  return file && parts.length >= 3 ? `${file}:${parts[parts.length - 2]}` : "other";
};

export function mountPerfDebug(audioCtx: AudioContext): void {
  if (document.getElementById("perf-debug")) return;
  const el = document.createElement("pre");
  el.id = "perf-debug";
  el.style.cssText = "position:fixed;top:4px;left:4px;z-index:2147483000;margin:0;padding:6px 8px;max-width:92vw;pointer-events:none;" +
    "font:11px/1.35 ui-monospace,Consolas,monospace;color:#9ef0ff;background:rgba(0,0,0,.78);border:1px solid rgba(158,240,255,.35);" +
    "border-radius:6px;white-space:pre-wrap;word-break:break-all";
  document.body.appendChild(el);

  const nativeRaf = window.requestAnimationFrame.bind(window);
  let rafCalls = 0;
  let rafBy: Record<string, number> = {};
  window.requestAnimationFrame = (cb: FrameRequestCallback): number => {
    rafCalls++;
    const k = callerOf(new Error().stack);
    rafBy[k] = (rafBy[k] ?? 0) + 1;
    return nativeRaf(cb);
  };

  let frames = 0;
  const countFrame = () => { frames++; nativeRaf(countFrame); };
  nativeRaf(countFrame);

  let longTasks = 0;
  let longMax = 0;
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) { longTasks++; longMax = Math.max(longMax, e.duration); }
    }).observe({ entryTypes: ["longtask"] });
  } catch { /* not supported (Safari) */ }

  const tick = () => {
    const anims = document.getAnimations().filter((a) => a.playState === "running");
    const names = new Map<string, number>();
    for (const a of anims) {
      const n = (a as CSSAnimation).animationName || (a as CSSTransition).transitionProperty || "?";
      names.set(n, (names.get(n) ?? 0) + 1);
    }
    const heap = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
    const s: PerfSample = {
      fps: frames,
      rafPerSec: rafCalls,
      rafBy,
      longTasks,
      longTaskMaxMs: Math.round(longMax),
      dom: document.getElementsByTagName("*").length,
      bubbles: document.querySelectorAll("#chat-history .chat-bubble").length,
      canvases: document.getElementsByTagName("canvas").length,
      animations: anims.length,
      animNames: [...names].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([n, c]) => (c > 1 ? `${n}×${c}` : n)),
      audio: audioCtx.state,
      gatePaused: animPaused(),
      heapMB: heap ? Math.round(heap.usedJSHeapSize / 1e6) : null,
    };
    (window as unknown as { __perf: PerfSample }).__perf = s;
    const by = Object.entries(s.rafBy).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, v]) => `${k} ${v}`).join("\n    ");
    el.textContent =
      `perf debug (?debug)\n` +
      `fps ${s.fps}  rAF/s ${s.rafPerSec}  longtask ${s.longTasks} (max ${s.longTaskMaxMs}ms)\n` +
      `rAF/s by caller:\n    ${by || "-"}\n` +
      `DOM ${s.dom}  bubbles ${s.bubbles}  canvases ${s.canvases}\n` +
      `CSS animations running ${s.animations}: ${s.animNames.join(", ") || "-"}\n` +
      `AudioContext ${s.audio}  gate ${s.gatePaused ? "PAUSED" : "active"}  heap ${s.heapMB ?? "?"}MB`;
    frames = 0; rafCalls = 0; rafBy = {}; longTasks = 0; longMax = 0;
  };
  window.setInterval(tick, 1000);
  tick();
}
