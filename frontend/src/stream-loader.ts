// The loader of an assistant bubble between `stream_start` and the first text chunk (design and styles in
// stream-loader.css). It is built here and thrown away the moment text arrives, so main.ts only calls these two
// functions. The goo filter sits inside the loader's own markup: no SVG in index.html, and when the loader is
// cleared the filter goes with it.
import "./stream-loader.css";

// blur + alpha threshold = the liquid effect of uiverse.io/david_7366/tall-turkey-48 (MIT: blur 5 and "22 -9" on a
// 100px loader); the blur is scaled down to these ~11-16px blobs. The wide filter region keeps the goo from being cut.
const MARKUP = `
  <svg class="sl-defs" width="0" height="0" aria-hidden="true"><filter id="sl-goo" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur in="SourceGraphic" stdDeviation="1.8"/><feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -9"/></filter></svg>
  <div class="stream-bubble-host">
    <div class="loader-layer-pin">
      <div class="loader-inner-c">
        <div class="blob-c bc-1"></div>
        <div class="blob-c bc-2"></div>
        <div class="blob-c bc-3"></div>
        <div class="blob-c bc-4"></div>
      </div>
    </div>
  </div>`;

export function showStreamLoader(bubble: HTMLElement): void {
  bubble.classList.add("typing-loader");
  bubble.innerHTML = MARKUP;
}

export function clearStreamLoader(bubble: HTMLElement): void {
  bubble.classList.remove("typing-loader");
  bubble.innerHTML = "";
}
