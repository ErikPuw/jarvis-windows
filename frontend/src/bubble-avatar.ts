// Bot avatar (bot-avatars, type "square") for assistant chat bubbles, drawn on a plain
// canvas with the library's own simulation — no React. Only the newest assistant bubble
// animates; older ones freeze on a sleeping frame so a long chat costs one draw loop.
// The bot follows the JARVIS state through the "jarvis:mascot" event: thinking/working →
// working, speaking → default (awake), anything else → sleeping.
import {
  BotAvatarSim, drawBotAvatarFrame, botAvatarShapes, botAvatarPresets, autoInk,
  BOT_AVATAR_OVERSCAN, botAvatarJumpDefaults, restPose, type BotAvatarState,
} from "bot-avatars";

const TYPE = "square" as const;
const BOX = 28; // css px of the avatar square
const dpr = Math.min(window.devicePixelRatio || 1, 2);
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

const preset = botAvatarPresets[TYPE];
const cfg = {
  path: new Path2D(botAvatarShapes[TYPE]),
  ...preset,
  ink: autoInk(preset.color),
  shading: "plastic" as const,
  typeKey: TYPE,
  theme: "dark" as const,
  dpr,
};

interface Avatar { host: HTMLElement; canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D; sim: BotAvatarSim; }

// Pointer play on the newest avatar, as on libraries.dev/bots: the head follows a pointer
// within a few head widths, close by it hops with joy every so often, a click hops twice, higher.
const FOLLOW_PX = BOX * 5;
const NEAR_PX = BOX * 1.7;
const HOP_EVERY_MS = 1500;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

let ptr: { x: number; y: number } | null = null;
let lastHop = 0;
let hops = 0;
let live: Avatar | null = null;
let cur: BotAvatarState = "sleeping";
let last = 0;
let raf = 0;

const STATE_OF: Record<string, BotAvatarState> = {
  thinking: "working", working: "working", restarting: "working", speaking: "default",
};

function paint(a: Avatar, pose = a.sim.pose, still = reduced): void {
  a.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  a.ctx.clearRect(0, 0, a.canvas.width, a.canvas.height);
  drawBotAvatarFrame(a.ctx, BOX, pose, { ...cfg, still });
}

function hop(a: Avatar): void {
  a.sim.poke(); // a hop and a full turn
  a.host.dataset.hops = String(++hops);
}

/** A sleeping bot has its eyes shut, so it wakes while the pointer is close and dozes off again after. */
function wakeFor(a: Avatar, close: boolean): void {
  const awake = close && cur === "sleeping";
  if (awake === (a.host.dataset.awake === "1")) return;
  a.host.dataset.awake = awake ? "1" : "0";
  a.sim.setState(awake ? "default" : cur);
}

/** Aims the live avatar's gaze at the pointer and hops when it is right next to it. */
function pointerPlay(a: Avatar, now: number): void {
  if (!ptr) { a.sim.setPointer(0, 0, 0); a.host.dataset.follow = "0"; wakeFor(a, false); return; }
  const r = a.host.getBoundingClientRect();
  const dx = ptr.x - (r.left + r.width / 2), dy = ptr.y - (r.top + r.height / 2);
  const d = Math.hypot(dx, dy);
  const follow = d <= FOLLOW_PX;
  a.sim.setPointer(clamp(dx / (BOX * 2), -1, 1), clamp(dy / (BOX * 2), -1, 1), follow ? 1 : 0);
  a.host.dataset.follow = follow ? "1" : "0";
  wakeFor(a, follow);
  if (d <= NEAR_PX && now - lastHop > HOP_EVERY_MS) { lastHop = now; hop(a); }
}

/** Click: two hops, higher and with two turns, then the stock jump numbers come back. */
function excite(a: Avatar): void {
  a.sim.setJump({ height: botAvatarJumpDefaults.height * 1.5, spin: 2 });
  hop(a);
  setTimeout(() => { if (live === a) hop(a); }, 420);
  setTimeout(() => a.sim.setJump({ height: botAvatarJumpDefaults.height, spin: botAvatarJumpDefaults.spin }), 1400);
}

function loop(now: number): void {
  raf = 0;
  if (!live) return;
  if (!document.hidden) { pointerPlay(live, now); live.sim.update(Math.min((now - last) / 1000, 0.05)); paint(live); }
  last = now;
  raf = requestAnimationFrame(loop);
}

function freeze(a: Avatar): void {
  a.host.dataset.live = "0";
  a.host.dataset.follow = "0";
  paint(a, restPose("sleeping"), true); // a still frame; no animation follows
}

function makeAvatar(): Avatar {
  const host = document.createElement("span");
  host.className = "bubble-avatar";
  const canvas = document.createElement("canvas");
  // the canvas draws bigger than its box so a hop is never clipped (bot-avatars convention)
  const px = Math.round(BOX * BOT_AVATAR_OVERSCAN * dpr);
  canvas.width = canvas.height = px;
  canvas.style.width = canvas.style.height = `${BOX * BOT_AVATAR_OVERSCAN}px`;
  host.appendChild(canvas);
  return { host, canvas, ctx: canvas.getContext("2d")!, sim: new BotAvatarSim(Math.random(), cur) };
}

/** Puts the avatar + name header at the top of an assistant bubble; the previous live avatar freezes. */
export function attachBubbleHead(bubble: HTMLElement): void {
  if (bubble.querySelector(":scope > .bubble-head")) return;
  if (live) freeze(live);
  const a = makeAvatar();
  a.host.dataset.live = "1";
  a.host.dataset.state = cur;
  if (!reduced) a.host.addEventListener("click", () => { if (live === a) excite(a); });
  const head = document.createElement("div");
  head.className = "bubble-head";
  const label = document.createElement("span");
  label.className = "bubble-name";
  head.append(a.host, label);
  bubble.prepend(head);
  bubble.classList.add("has-head");
  live = a;
  paint(a);
  if (!reduced && !raf) { last = performance.now(); raf = requestAnimationFrame(loop); }
}

export function setBubbleName(bubble: HTMLElement, name: string): void {
  const el = bubble.querySelector(":scope > .bubble-head > .bubble-name");
  if (el && el.textContent !== name) el.textContent = name;
}

/** Replaces a bubble's content but keeps its avatar/name header. */
export function setBubbleContent(bubble: HTMLElement, html: string): void {
  const head = bubble.querySelector(":scope > .bubble-head");
  bubble.innerHTML = html;
  if (head) bubble.prepend(head);
}

if (!reduced) {
  window.addEventListener("pointermove", (e) => { ptr = { x: e.clientX, y: e.clientY }; }, { passive: true });
  const release = () => { ptr = null; };
  window.addEventListener("blur", release);
  document.addEventListener("mouseleave", release);
}

window.addEventListener("jarvis:mascot", (e) => {
  cur = STATE_OF[String((e as CustomEvent).detail)] ?? "sleeping";
  if (!live) return;
  live.host.dataset.state = cur;
  live.host.dataset.awake = "0";
  live.sim.setState(cur);
  if (reduced) paint(live);
});
