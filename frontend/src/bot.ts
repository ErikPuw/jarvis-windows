// The command bar's mascot: one bot (bot-avatars, drawn on a plain canvas with the library's own
// simulation — no React) perched above the send button. It replaces the old fox sprite and the bots that
// used to sit in every chat bubble, so the whole page has exactly one animated character.
// It has its own behaviour for each JARVIS state ("jarvis:mascot" event), see PROFILE:
//   idle      awake, looks around (left/right/up/down) for DOZE_MS, then sleeps
//   listening awake and attentive (looks down at the input) for DOZE_MS, then sleeps
//   thinking  awake, looks up as if pondering, calm (no hops), never sleeps
//   working   the library's busy state (hops)         speaking  awake, with a mouth
// idle <-> listening only swap the look script; the DOZE_MS clock keeps running. The clock measures time
// since the last activity (pointer near the bot, a tap/click or a key anywhere): activity wakes a sleeping
// bot back to idle (looks around) and restarts the 30 s, so it does not stay asleep for good.
import { gatedLoop } from "./anim-gate";
import {
  BotAvatarSim, drawBotAvatarFrame, botAvatarShapes, botAvatarPresets, autoInk,
  BOT_AVATAR_OVERSCAN, botAvatarJumpDefaults, type BotAvatarState, type BotAvatarFace,
} from "bot-avatars";

const TYPE = "square" as const; // any key of botAvatarShapes: clover flower triangle square blob ghost circle drop star droid mech alien hexagon cat cloud pill pebble puddle
const BOX = 32; // css px of the bot's square
const dpr = Math.min(window.devicePixelRatio || 1, 3); // up to 3 (iPhone): at 2 the edges of a 32px sprite look jagged
const touch = matchMedia("(pointer: coarse)").matches; // a 32px sprite at 30 fps reads the same and costs half
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

const SHADING = "plastic" as const; // "smooth" is the library's other option

const preset = botAvatarPresets[TYPE];
const cfg = {
  path: new Path2D(botAvatarShapes[TYPE]),
  ...preset,
  ink: autoInk(preset.color),
  shading: SHADING,
  typeKey: TYPE,
  theme: "dark" as const,
  dpr,
};

// Pointer play, as on libraries.dev/bots: the head follows a pointer within a few head widths, close by
// it hops with joy every so often, a click hops twice, higher.
const FOLLOW_PX = BOX * 5;
const NEAR_PX = BOX * 1.7;
const HOP_EVERY_MS = 1500;
const DOZE_MS = 30_000; // awake this long after going idle / listening, then it sleeps

// gaze targets in head-widths from the head's centre (-1..1); x right, y down
interface Look { name: string; x: number; y: number }
const LOOK_AROUND: Look[] = [
  { name: "left", x: -1, y: 0 }, { name: "right", x: 1, y: 0 }, { name: "up", x: 0, y: -1 }, { name: "down", x: 0, y: 1 },
  { name: "left", x: -1, y: -0.6 }, { name: "right", x: 1, y: 0.6 }, { name: "center", x: 0, y: 0 },
];
const ATTENTIVE: Look[] = [
  { name: "down", x: 0, y: 0.8 }, { name: "down-left", x: -0.5, y: 0.7 }, { name: "down", x: 0, y: 0.8 }, { name: "down-right", x: 0.5, y: 0.7 },
];
const PONDER: Look[] = [
  { name: "up-left", x: -0.7, y: -0.8 }, { name: "up", x: 0, y: -1 }, { name: "up-right", x: 0.7, y: -0.8 }, { name: "up", x: 0, y: -1 },
];

interface Profile { state: BotAvatarState; face?: BotAvatarFace; looks?: Look[]; everyMs?: number; doze?: boolean }
const PROFILE: Record<string, Profile> = {
  idle: { state: "default", looks: LOOK_AROUND, everyMs: 1300, doze: true },
  listening: { state: "default", looks: ATTENTIVE, everyMs: 2000, doze: true },
  thinking: { state: "default", looks: PONDER, everyMs: 1800 },
  working: { state: "working" },
  restarting: { state: "working" },
  speaking: { state: "default", face: "mouth" },
};
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function mountBot(parent: HTMLElement): void {
  const host = document.createElement("div");
  host.id = "jarvis-bot";
  host.setAttribute("aria-hidden", "true");
  host.dataset.shape = TYPE;
  host.dataset.shading = SHADING;
  const canvas = document.createElement("canvas");
  // the canvas draws bigger than its box so a hop is never clipped (bot-avatars convention)
  canvas.width = canvas.height = Math.round(BOX * BOT_AVATAR_OVERSCAN * dpr);
  canvas.style.width = canvas.style.height = `${BOX * BOT_AVATAR_OVERSCAN}px`;
  host.appendChild(canvas);
  parent.appendChild(host);
  const ctx = canvas.getContext("2d")!;
  const sim = new BotAvatarSim(Math.random(), "default");

  let ptr: { x: number; y: number } | null = null;
  let gaze: Look | null = null; // current look-around target
  let face: BotAvatarFace = preset.face;
  let cur: BotAvatarState = "default"; // the state the behaviour wants (the pointer can wake a sleeping bot)
  let lastHop = 0;
  let hops = 0;
  let doze = 0; // pending "go to sleep" timer; 0 = not winding down
  let lastActive = performance.now();
  let sys = "idle"; // the last JARVIS state seen, so a waking bot behaves like that state
  let look = 0; // the look script's interval
  let lookIdx = 0;
  let looks: Look[] = [];

  function paint(): void {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawBotAvatarFrame(ctx, BOX, sim.pose, { ...cfg, face, still: reduced });
  }

  function hop(): void {
    sim.poke(); // a hop and a full turn
    host.dataset.hops = String(++hops);
  }

  /** Aims the gaze at the pointer and hops when it is right next to it. */
  function pointerPlay(now: number): void {
    let following = false;
    if (ptr) {
      const r = host.getBoundingClientRect();
      const dx = ptr.x - (r.left + r.width / 2), dy = ptr.y - (r.top + r.height / 2);
      const d = Math.hypot(dx, dy);
      following = d <= FOLLOW_PX;
      if (following) sim.setPointer(clamp(dx / (BOX * 2), -1, 1), clamp(dy / (BOX * 2), -1, 1), 1);
      host.dataset.follow = following ? "1" : "0";
      if (following) activity();
      if (d <= NEAR_PX && now - lastHop > HOP_EVERY_MS) { lastHop = now; hop(); }
    } else {
      host.dataset.follow = "0";
    }
    // no pointer to follow: the look-around (if any) steers the head, else it is left free
    if (!following) { if (gaze) sim.setPointer(gaze.x, gaze.y, 1); else sim.setPointer(0, 0, 0); }
  }

  /** Click: two hops, higher and with two turns, then the stock jump numbers come back. */
  function excite(): void {
    sim.setJump({ height: botAvatarJumpDefaults.height * 1.5, spin: 2 });
    hop();
    setTimeout(hop, 420);
    setTimeout(() => sim.setJump({ height: botAvatarJumpDefaults.height, spin: botAvatarJumpDefaults.spin }), 1400);
  }

  function apply(state: BotAvatarState, f: BotAvatarFace = preset.face): void {
    cur = state;
    face = f;
    host.dataset.state = state;
    host.dataset.face = f;
    host.dataset.awake = "0";
    sim.setState(state);
    if (reduced) paint();
  }

  function lookAt(i: number): void {
    gaze = looks[i % looks.length];
    host.dataset.look = gaze.name;
  }

  /** The library flips/jumps at random while awake; during a look script that would break the calm. */
  function idleJumps(on: boolean): void {
    sim.setJump({ every: on ? botAvatarJumpDefaults.every : 0 });
    host.dataset.idlejumps = on ? "on" : "off";
  }

  function setLooks(list: Look[], everyMs: number): void {
    clearInterval(look);
    looks = list;
    lookIdx = 0;
    lookAt(0);
    idleJumps(false);
    look = window.setInterval(() => lookAt(++lookIdx), everyMs);
  }

  function stopBehavior(): void {
    clearTimeout(doze);
    clearInterval(look);
    doze = look = 0;
    gaze = null;
    delete host.dataset.grace;
    delete host.dataset.look;
    idleJumps(true);
  }

  function startDoze(): void {
    clearTimeout(doze);
    lastActive = performance.now();
    const arm = (ms: number) => {
      doze = window.setTimeout(() => {
        const left = DOZE_MS - (performance.now() - lastActive);
        if (left > 50) { arm(left); return; } // there was activity meanwhile: wait out the rest
        stopBehavior();
        apply("sleeping");
      }, ms);
    };
    arm(DOZE_MS);
    host.dataset.grace = "1";
  }

  /** Something happened near the bot: a sleeping one wakes to idle (or listening), an awake one stays up another DOZE_MS. */
  function activity(): void {
    lastActive = performance.now();
    if (cur !== "sleeping") return;
    const p = PROFILE[sys];
    if (!p?.doze) return;
    startDoze();
    apply("default", p.face);
    setLooks(p.looks!, p.everyMs!);
  }

  window.addEventListener("jarvis:mascot", (e) => {
    const name = String((e as CustomEvent).detail);
    const p = PROFILE[name];
    if (!p) return;
    sys = name;
    if (reduced) { stopBehavior(); apply(p.doze ? "sleeping" : p.state, p.face); return; }
    if (p.doze) {
      if (cur === "sleeping" && !doze) return; // asleep: quiet states do not wake it
      if (!doze) startDoze(); // calming down from busy: DOZE_MS starts now (idle <-> listening keeps the clock)
      apply("default", p.face);
      setLooks(p.looks!, p.everyMs!);
      return;
    }
    stopBehavior();
    apply(p.state, p.face);
    if (p.looks) setLooks(p.looks, p.everyMs!);
  });

  if (!reduced) {
    window.addEventListener("pointermove", (e) => { ptr = { x: e.clientX, y: e.clientY }; }, { passive: true });
    for (const ev of ["pointerdown", "keydown", "touchstart"]) window.addEventListener(ev, activity, { passive: true });
    const release = () => { ptr = null; };
    window.addEventListener("blur", release);
    document.addEventListener("mouseleave", release);
    host.addEventListener("click", excite);
  }

  // start awake as if it had just gone idle: looks around, then dozes off after DOZE_MS
  apply(reduced ? "sleeping" : "default");
  if (!reduced) { startDoze(); setLooks(LOOK_AROUND, PROFILE.idle.everyMs!); }
  paint();
  if (!reduced) gatedLoop((now, dt) => { pointerPlay(now); sim.update(Math.min(dt / 1000, 0.05)); paint(); }, touch ? 1000 / 30 : 1000 / 60);
}
