// Edge-Aura: Ultra-thin 1.0px ambient continuous aura surrounding the Command Bar
// Palette: JARVIS Arc Reactor
// Speed: 2.5s per cycle
// Opacity: 30% (idle) / 70% (all active states: listening, thinking, working, speaking, error)

interface ColorStop {
  r: number;
  g: number;
  b: number;
}

const ARC_REACTOR_PALETTE: ColorStop[] = [
  { r: 0, g: 245, b: 212 },   // Mint Cyan (#00f5d4)
  { r: 14, g: 165, b: 233 },  // Arc Cyan (#0ea5e9)
  { r: 56, g: 189, b: 248 },  // Electric Blue (#38bdf8)
  { r: 29, g: 78, b: 216 },   // Deep Cobalt (#1d4ed8)
  { r: 0, g: 245, b: 212 },
];

const THICKNESS = 1.0;          // 1.0px hairline
const CYCLE_DURATION = 2.5;     // 2.5s per revolution
const PADDING = 4;              // Bleed padding for ambient halo

function drawContinuousRoundRect(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  c.beginPath();
  if (c.roundRect) {
    c.roundRect(x, y, w, h, r);
  } else {
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + r, y, r);
    c.closePath();
  }
}

import { gatedLoop } from "./anim-gate";

export function mountEdgeAura(host: HTMLElement) {
  const canvas = document.createElement("canvas");
  canvas.className = "cmd-aura-canvas";
  canvas.setAttribute("aria-hidden", "true");
  host.appendChild(canvas);

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  let width = 0;
  let height = 0;
  let radius = 10;

  const updateSize = () => {
    const rect = host.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = rect.width;
    height = rect.height;

    const computedStyle = getComputedStyle(host);
    const parsedRadius = parseFloat(computedStyle.borderRadius);
    if (!Number.isNaN(parsedRadius) && parsedRadius > 0) {
      radius = parsedRadius;
    }

    canvas.width = (width + PADDING * 2) * dpr;
    canvas.height = (height + PADDING * 2) * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  const ro = new ResizeObserver(updateSize);
  ro.observe(host);
  updateSize();

  // Opacity: idle = 0.30, all other states = 0.70
  let targetOpacity = 0.30;
  let currentOpacity = 0.30;
  let targetGlow = 1.5;
  let currentGlow = 1.5;

  const handleStateChange = (state: string) => {
    if (state === "idle") {
      targetOpacity = 0.30;
      targetGlow = 1.5;
    } else {
      targetOpacity = 0.70;
      targetGlow = 2.4;
    }
  };

  window.addEventListener("jarvis:mascot", (e) => {
    handleStateChange(String((e as CustomEvent).detail));
  });

  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  let time = 0;
  const touch = matchMedia("(pointer: coarse)").matches;

  const render = (_now: number, dtMs: number): boolean | void => {
    if (!document.contains(host)) { ro.disconnect(); return false; }
    const dt = dtMs * 0.001;

    // Smoothly interpolate brightness when state changes
    currentOpacity += (targetOpacity - currentOpacity) * 0.08;
    currentGlow += (targetGlow - currentGlow) * 0.08;

    if (!prefersReduced.matches) {
      const rotSpeed = 1 / CYCLE_DURATION; // 2.5s cycle
      time = (time + dt * rotSpeed * Math.PI * 2) % (Math.PI * 2);
    }

    ctx.clearRect(0, 0, width + PADDING * 2, height + PADDING * 2);

    const cx = PADDING + width / 2;
    const cy = PADDING + height / 2;

    // Continuous 360-degree conic gradient
    const grad = ctx.createConicGradient(time, cx, cy);
    const stops = ARC_REACTOR_PALETTE.length - 1;
    for (let i = 0; i <= stops; i++) {
      const col = ARC_REACTOR_PALETTE[i];
      grad.addColorStop(i / stops, `rgb(${col.r}, ${col.g}, ${col.b})`);
    }

    // Pass 1: Subtle Ambient Halo — a wider, fainter stroke instead of ctx.filter blur (a per-frame blur
    // pass; Safari does not even support it)
    ctx.save();
    drawContinuousRoundRect(ctx, PADDING, PADDING, width, height, radius);
    ctx.strokeStyle = grad;
    ctx.lineWidth = THICKNESS + currentGlow * 1.2;
    ctx.globalAlpha = currentOpacity * 0.22;
    ctx.stroke();
    ctx.restore();

    // Pass 2: Razor-thin 1.0px Seamless Line
    ctx.save();
    drawContinuousRoundRect(ctx, PADDING, PADDING, width, height, radius);
    ctx.strokeStyle = grad;
    ctx.lineWidth = THICKNESS;
    ctx.globalAlpha = currentOpacity;
    ctx.stroke();
    ctx.restore();
  };

  // 2.5s per turn of a 1px line reads the same at 30 fps; the blurred halo is the costly part on a phone.
  gatedLoop(render, touch ? 1000 / 30 : 1000 / 60);
}
