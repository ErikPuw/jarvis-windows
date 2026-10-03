// Status label motion (row = #status-row, label = #status-text):
//  - a text change slides + fades: the old text slides out as a ghost, the new one slides in,
//    upward when JARVIS gets busier (idle → thinking → working), downward when it calms down;
//  - after 10 s of quiet in idle (JARVIS has answered and nothing is going on, mic off) the text rolls in
//    (collapses, the orb stays, dimmed); any state change, key press or click rolls it back out. The active
//    states (listening, thinking, working, speaking) never roll in: the user always sees what JARVIS is doing.
// The label's text/class are written by main.ts (updateStatus/transition); we only observe them.
const QUIET_MS = 10_000;
const SLIDE_PX = 8;
const SLIDE_MS = 280;
const EASE = "cubic-bezier(0.3, 0.7, 0.2, 1)";

// how "busy" each state is: sets the slide direction
const RANK: Record<string, number> = { idle: 0, listening: 1, thinking: 2, speaking: 2, working: 3, restarting: 3 };
const QUIET = new Set(["idle"]);

export function mountStatusLabel(row: HTMLElement, label: HTMLElement): void {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- slide on text change ----
  let dir = 1; // +1 = new text comes from below (busier), -1 = from above
  let lastText = label.textContent ?? "";
  let prevClass = label.className;

  const slide = (oldText: string, oldClass: string) => {
    row.querySelectorAll(".status-ghost").forEach((g) => g.remove());
    const ghost = label.cloneNode(false) as HTMLElement;
    ghost.removeAttribute("id");
    ghost.className = `status-ghost ${oldClass}`;
    ghost.textContent = oldText;
    ghost.setAttribute("aria-hidden", "true");
    ghost.style.left = `${label.offsetLeft}px`;
    ghost.style.top = `${label.offsetTop}px`;
    row.appendChild(ghost);
    // the ghost holds its last frame until removed; the label must NOT (fill would pin opacity: 1
    // and override the rolled-in state)
    ghost.animate([{ opacity: 1, transform: "translateY(0)" }, { opacity: 0, transform: `translateY(${-dir * SLIDE_PX}px)` }],
      { duration: SLIDE_MS, easing: EASE, fill: "forwards" }).onfinish = () => ghost.remove();
    label.animate([{ opacity: 0, transform: `translateY(${dir * SLIDE_PX}px)` }, { opacity: 1, transform: "translateY(0)" }],
      { duration: SLIDE_MS, easing: EASE });
  };

  new MutationObserver((records) => {
    let oldClass = prevClass;
    for (const r of records) if (r.type === "attributes" && r.attributeName === "class") { oldClass = r.oldValue ?? oldClass; break; }
    prevClass = label.className;
    const text = label.textContent ?? "";
    if (text === lastText) return;
    const oldText = lastText;
    lastText = text;
    if (!reduced && oldText && !row.classList.contains("quiet")) slide(oldText, oldClass);
  }).observe(label, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["class"], attributeOldValue: true });

  // ---- roll in after quiet ----
  let state = "idle";
  let timer = 0;
  const arm = () => {
    clearTimeout(timer);
    if (QUIET.has(state)) timer = window.setTimeout(() => row.classList.add("quiet"), QUIET_MS);
  };
  const wake = () => { row.classList.remove("quiet"); arm(); };

  window.addEventListener("jarvis:mascot", (e) => {
    const next = String((e as CustomEvent).detail);
    const wasQuietState = QUIET.has(state);
    dir = (RANK[next] ?? 0) >= (RANK[state] ?? 0) ? 1 : -1;
    state = next;
    if (!QUIET.has(next)) { clearTimeout(timer); row.classList.remove("quiet"); }
    else if (!wasQuietState) wake(); // calmed down: count 10 s from now
  });
  for (const type of ["keydown", "pointerdown"]) {
    window.addEventListener(type, () => { if (row.classList.contains("quiet")) wake(); else arm(); }, { passive: true });
  }
  arm();
}
