/**
 * JARVIS — Main entry point.
 *
 * Wires together the orb visualization, WebSocket communication,
 * speech recognition, and audio playback into a single experience.
 */

import { createOrb, type OrbState } from "./orb";
import { createVoiceInput, createAudioPlayer, createInterruptDetector } from "./voice";
import { createSocket } from "./ws";
import { openSettings, checkFirstTimeSetup } from "./settings/index";
import "./style.css";
import { setStatusIcon, agentBadge } from "./icons";
import { mountMascot } from "./mascot";
import { mountClock } from "./clock";
import { mountStatusOrb } from "./status-orb";
import { mountStatusLabel } from "./status-label";
import { mountMetalRing } from "./metal-ring";
import { attachBubbleHead, setBubbleName, setBubbleContent } from "./bubble-avatar";
import { generateResourcesHTML, generateSystemsHTML } from "./dashboard-hud";

const DEFAULT_FETCH_TIMEOUT_MS = 15000;
const UPLOAD_FETCH_TIMEOUT_MS = 120000;

/** fetch() has no timeout of its own, so a stalled backend left spinners
 *  turning forever with no error path. */
async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_FETCH_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}
// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

type State = "idle" | "listening" | "thinking" | "working" | "speaking" | "restarting";
let currentState: State = "idle";
let isMuted = true;
let isTtsDisabled = localStorage.getItem("jarvis_tts_disabled") === "true";
let isBusy = false;
let lastWorkState: "thinking" | "working" = "thinking";
let isSpeaking = false;
let pendingQueriesQueue: { type: "voice" | "text", text: string, file?: File, bubbleElement?: HTMLElement }[] = [];

let activeAssistantBubble: HTMLElement | null = null;
let activeFlowBubble: HTMLElement | null = null;
let activeAssistantText = "";
let streamTextBuffer = "";
let streamTargetText = "";
let streamTypewriterTimer: any = null;
let lastStreamRenderAt = 0;
let wasStreamed = false;
let audioChunkBuffer: Uint8Array[] | null = null;

const chatHistory = document.getElementById("chat-history")!;
const statusEl = document.getElementById("status-text")!;
const errorEl = document.getElementById("error-text")!;
mountMascot(document.getElementById("command-bar-inner")!);
mountClock();
mountStatusOrb(document.getElementById("status-orb")!);
mountStatusLabel(document.getElementById("status-row")!, statusEl);
mountMetalRing(document.getElementById("cmd-send-wrap")!);
{
  // command-bar beam follows the JARVIS state (CSS keys on data-state)
  const bar = document.getElementById("command-bar-inner")!;
  window.addEventListener("jarvis:mascot", (e) => { bar.dataset.state = String((e as CustomEvent).detail); });
}
const commandInput = document.getElementById("command-input") as HTMLTextAreaElement;
const filePinnedContainer = document.getElementById("file-pinned-container")!;
const filePinnedName = document.getElementById("file-pinned-name")!;
const btnFileRemove = document.getElementById("btn-file-remove")!;
const btnHistory = document.getElementById("btn-history")!;
const historyPanel = document.getElementById("history-panel")!;
const historyList = document.getElementById("history-list")!;
const btnCloseHistory = document.getElementById("btn-close-history")!;
const btnMap = document.getElementById("btn-map")!;
const mapPanel = document.getElementById("map-panel")!;
const btnCloseMap = document.getElementById("btn-close-map")!;
let mapLibreMap: any = null;
let mapMarker: any = null;
let pinnedMarkers: any[] = [];
let cachedPins: any[] = [];
let isMap3D = false;
let isMapGlobe = false;
let isMapFullScreen = false;

let userHasScrolledUp = false;

function updateScrollFade() {
  if (!chatHistory) return;
  // Check if we are within 10px of the bottom
  const isAtBottom = Math.abs(chatHistory.scrollHeight - chatHistory.clientHeight - chatHistory.scrollTop) < 10;
  chatHistory.classList.toggle("at-bottom", isAtBottom);

  // If user scrolled near the bottom, reset the flag so auto-scroll can resume
  if (isAtBottom) {
    userHasScrolledUp = false;
  }
}

function scrollToBottomIfNeeded(force = false) {
  if (!chatHistory) return;
  if (force) {
    userHasScrolledUp = false;
  }

  if (force || !userHasScrolledUp) {
    chatHistory.scrollTop = chatHistory.scrollHeight;
    updateScrollFade();
  }
}

// Detect manual user scrolling
function handleManualScroll() {
  if (!chatHistory) return;
  const isAtBottom = Math.abs(chatHistory.scrollHeight - chatHistory.clientHeight - chatHistory.scrollTop) < 15;
  if (!isAtBottom) {
    userHasScrolledUp = true;
  }
}

chatHistory.addEventListener("scroll", updateScrollFade);
chatHistory.addEventListener("wheel", handleManualScroll, { passive: true });
chatHistory.addEventListener("touchmove", handleManualScroll, { passive: true });

function startStreamTypewriter() {
  stopStreamTypewriter();
  streamTextBuffer = "";
  streamTargetText = "";
  lastStreamRenderAt = 0;

  streamTypewriterTimer = setInterval(() => {
    if (!activeAssistantBubble) return;

    // Nếu text đích bắt đầu bằng prefix của Interactive Card, ta không hiển thị text thô qua typewriter
    if (streamTargetText.startsWith("[INTERACTIVE_CARD_JSON]:")) {
      return;
    }

    let textContainer = activeAssistantBubble.querySelector(".bubble-text") as HTMLElement;
    if (!textContainer) {
      textContainer = document.createElement("div");
      textContainer.className = "bubble-text";
      activeAssistantBubble.appendChild(textContainer);
    }

    const diff = streamTargetText.length - streamTextBuffer.length;
    if (diff <= 0) return;

    // Tự động điều chỉnh tốc độ hiển thị dựa trên lượng ký tự đang chờ (buffer lag)
    let charsToTake = 1;
    if (diff > 100) {
      charsToTake = 6;
    } else if (diff > 50) {
      charsToTake = 4;
    } else if (diff > 15) {
      charsToTake = 2;
    }

    streamTextBuffer += streamTargetText.slice(
      streamTextBuffer.length,
      streamTextBuffer.length + charsToTake
    );

    // formatMarkdown re-parses the whole accumulated string (~15 regexes plus a
    // table parser) and rewrites innerHTML, forcing a full re-layout. Doing
    // that every 16ms made the cost grow with the square of the reply length,
    // competing with audio decoding and the orb's render loop. The buffer still
    // advances every tick; only the repaint backs off as the text grows.
    const now = performance.now();
    const minRenderGap =
      streamTextBuffer.length > 2000 ? 100 :
      streamTextBuffer.length > 500 ? 50 : 16;
    if (now - lastStreamRenderAt >= minRenderGap || streamTextBuffer.length >= streamTargetText.length) {
      lastStreamRenderAt = now;
      textContainer.innerHTML = formatMarkdown(streamTextBuffer);
      scrollToBottomIfNeeded();
    }
  }, 16); // ~60fps smooth updates
}

function stopStreamTypewriter() {
  if (streamTypewriterTimer) {
    clearInterval(streamTypewriterTimer);
    streamTypewriterTimer = null;
  }
  // Flush whatever the typewriter had not caught up to yet. It only ever
  // cleared the timer, so anything still queued when the stream ended was
  // simply never shown — and throttling the repaint widens that window.
  if (
    activeAssistantBubble &&
    streamTargetText &&
    !streamTargetText.startsWith("[INTERACTIVE_CARD_JSON]:") &&
    streamTextBuffer.length < streamTargetText.length
  ) {
    const textContainer = activeAssistantBubble.querySelector(".bubble-text") as HTMLElement | null;
    if (textContainer) {
      streamTextBuffer = streamTargetText;
      textContainer.innerHTML = formatMarkdown(streamTextBuffer);
      scrollToBottomIfNeeded();
    }
  }
}

let pendingFile: File | null = null;

export function formatMarkdown(text: string): string {
  if (!text) return "";

  let html = text;

  // 1. Render Links: [title](url) nhưng loại trừ các trường hợp bắt đầu bằng dấu chấm than (!)
  // Sử dụng regex: (?:^|[^!])\[([^\]]+)\]\(([^)]+)\) để chỉ bắt các link thông thường
  // Đồng thời giữ nguyên tiêu đề $1 thay vì đè thành chữ 'Xem tại đây'
  html = html.replace(/(^|[^!])\[([^\]]+)\]\(([^)]+)\)/g, '$1<a href="$3" target="_blank" style="color:#0ea5e9; text-decoration:none; font-weight:600; border-bottom:1px dashed #0ea5e9; transition:all 0.2s;" onmouseover="this.style.color=\'#38bdf8\'; this.style.borderBottomColor=\'#38bdf8\'" onmouseout="this.style.color=\'#0ea5e9\'; this.style.borderBottomColor=\'#0ea5e9\'">$2</a>');

  // 2. Render Images: ![alt](url)
  html = html.replace(/!\[(.*?)\]\((.*?)\)/g, '<img src="$2" alt="$1" style="max-width:100%; max-height:300px; object-fit:contain; border-radius:8px; margin:6px 0; display:block; border:1px solid rgba(255,255,255,0.1); box-shadow:0 4px 12px rgba(0,0,0,0.25);" />');

  html = html
    .replace(/^### (.*$)/gm, '<h3 style="color:var(--accent-blue);margin:2px 0 1px 0;font-size:12px;letter-spacing:1px;text-transform:uppercase;opacity:0.8">$1</h3>')
    .replace(/^## (.*$)/gm, '<h2 style="color:var(--accent-blue);margin:4px 0 2px 0;font-size:13px;letter-spacing:0.5px">$1</h2>')
    .replace(/^# (.*$)/gm, '<h1 style="color:var(--accent-blue);margin:8px 0 4px 0;font-size:16px;letter-spacing:0.5px;font-weight:700;">$1</h1>')
    .replace(/\*\*(.*?)\*\*/g, '<strong style="color:#fff;font-weight:600">$1</strong>')
    .replace(/\*(.*?)\*/g, '<em style="opacity:0.9">$1</em>')
    .replace(/^[\s]*[\*\-] (.*)/gm, '<div style="display:flex;gap:4px;margin:2px 0"><span>•</span><span>$1</span></div>')
    .replace(/^[\s]*(\d+)\. (.*)/gm, '<div style="display:flex;gap:4px;margin:2px 0"><span>$1.</span><span>$2</span></div>')
    .replace(/`(.*?)`/g, '<code style="background:rgba(255,255,255,0.1);padding:1px 3px;border-radius:4px;font-family:monospace;font-size:0.9em;color:#00d4ff">$1</code>');

  // Hỗ trợ hiển thị bảng biểu đơn giản (Parse Table)
  if (html.includes('|')) {
    const lines = html.split('\n');
    let inTable = false;
    let tableHtml = '';
    const newLines: string[] = [];

    for (let line of lines) {
      if (line.trim().startsWith('|')) {
        // Bỏ qua dòng separator ví dụ: |---|---| hoặc | :--- | :--- |
        if (line.includes('---') || line.includes(':---')) {
          continue;
        }
        const cells = line.split('|').map(c => c.trim()).filter((c, i, a) => i > 0 && i < a.length - 1);
        if (!inTable) {
          inTable = true;
          tableHtml = '<div class="table-responsive-wrapper" style="width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; margin:8px 0; border-radius:6px; border:1px solid rgba(255,255,255,0.05);">';
          tableHtml += '<style>.table-responsive-wrapper table img { max-width:120px !important; max-height:190px !important; align-items: center; object-fit:contain; border-radius:6px; margin:4px auto; display:block; border:1px solid rgba(255,255,255,0.1); box-shadow:0 2px 6px rgba(0,0,0,0.25); }</style>';
          tableHtml += '<table style="width:100%; min-width:320px; border-collapse:collapse; font-size:12px; color:#e2e8f0; background:rgba(255,255,255,0.02);">';
          tableHtml += '<tr style="background:rgba(14,165,233,0.15); font-weight:600; color:#fff; border-bottom:1px solid rgba(255,255,255,0.1);">';
          // Kiểm tra xem đây có phải bảng hàng ngang (mỗi mục một cột) hay không
          // Bằng cách xem các tiêu đề cột có chứa Poster/Hình ảnh không
          const isHorizontalTable = !cells.some(c => {
            const lc = c.toLowerCase();
            return lc.includes('poster') || lc.includes('hình ảnh') || lc.includes('nội dung') || lc.includes('tập');
          });

          cells.forEach((cell, idx) => {
            let widthStyle = '';
            if (isHorizontalTable) {
              widthStyle = 'width:150px; min-width:140px; text-align:center;';
            } else {
              // Gán style độ rộng cân đối dựa vào tiêu đề cột (bảng dọc)
              const lowerCell = cell.toLowerCase();
              if (lowerCell.includes('poster') || lowerCell.includes('hình ảnh')) {
                widthStyle = 'width:90px; min-width:90px;';
              } else if (lowerCell.includes('tên bài') || lowerCell.includes('tên sản phẩm')) {
                widthStyle = 'width:130px; min-width:120px; text-align:left;';
              } else if (lowerCell.includes('nội dung') || lowerCell.includes('nghệ sĩ') || lowerCell.includes('giá')) {
                widthStyle = 'min-width:200px; text-align:left;';
              } else if (lowerCell.includes('tập') || lowerCell.includes('thời lượng') || lowerCell.includes('nguồn')) {
                widthStyle = 'width:80px; min-width:80px; white-space:nowrap;';
              }
            }
            tableHtml += `<th style="padding:6px 8px; text-align:center; border:1px solid rgba(255,255,255,0.05); ${widthStyle}">${cell}</th>`;
          });
          tableHtml += '</tr>';
        } else {
          // Kiểm tra lại dạng bảng ngang cho các hàng dữ liệu
          const isHorizontalTable = !cells.some((c, idx) => {
            // Xem xem hàng đầu tiên (th) có chứa Poster không
            const thElements = tableHtml.match(/<th[^>]*>(.*?)<\/th>/g);
            if (thElements && thElements[idx]) {
              const thText = thElements[idx].replace(/<[^>]*>/g, '').toLowerCase();
              return thText.includes('poster') || thText.includes('nội dung') || thText.includes('tập');
            }
            return false;
          });

          tableHtml += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05); transition:background 0.2s;" onmouseover="this.style.background=\'rgba(255,255,255,0.02)\'" onmouseout="this.style.background=\'none\'">';
          cells.forEach((cell, idx) => {
            let cellContent = cell;
            let isAlignCentered = false;
            let widthStyle = '';

            // Nếu ô chứa ảnh hoặc thẻ a/link, hoặc icon 🔗, thực hiện căn giữa
            if (cell.includes('<img ') || cell.includes('<a ') || cell.includes('🔗')) {
              isAlignCentered = true;
            }

            if (isHorizontalTable) {
              widthStyle = 'width:150px; min-width:140px; text-align:center;';
              isAlignCentered = true;
            } else {
              // Đồng bộ độ rộng td tương ứng với th ở trên để tránh trình duyệt bóp méo
              if (idx === 0) { // Thường là Poster
                widthStyle = 'width:90px; min-width:90px;';
              } else if (idx === 1) { // Thường là Phim/Tên bài
                widthStyle = 'width:130px; min-width:120px; text-align:left; white-space:normal;';
                isAlignCentered = false; // Luôn căn lề trái cho dễ đọc
              } else if (idx === 2) { // Thường là Thể loại hoặc Nội dung
                const lowerCell = cells[idx] ? cells[idx].toLowerCase() : '';
                if (lowerCell.includes('thể loại')) {
                  widthStyle = 'width:100px; min-width:100px; text-align:left;';
                } else {
                  widthStyle = 'min-width:200px; text-align:left; white-space:normal;';
                }
                isAlignCentered = false;
              } else if (idx === 3) { // Thường là Tập/Thời Lượng
                widthStyle = 'width:80px; min-width:80px; white-space:nowrap;';
                isAlignCentered = true;
              } else if (idx === 4) { // Thường là Chi tiết / Link xem
                widthStyle = 'width:90px; min-width:90px; white-space:nowrap;';
                isAlignCentered = true;
              }
            }

            const alignStyle = isAlignCentered ? 'text-align:center;' : 'text-align:left;';
            tableHtml += `<td style="padding:6px 8px; border:1px solid rgba(255,255,255,0.05); vertical-align:middle; ${alignStyle} ${widthStyle}">${cellContent}</td>`;
          });
          tableHtml += '</tr>';
        }
      } else {
        if (inTable) {
          tableHtml += '</table></div>';
          newLines.push(tableHtml);
          inTable = false;
          tableHtml = '';
        }
        newLines.push(line);
      }
    }
    if (inTable) {
      tableHtml += '</table></div>';
      newLines.push(tableHtml);
    }
    html = newLines.join('\n');
  }

  // Clean up double newlines caused by div/h interaction with pre-wrap
  html = html.replace(/<\/div>\r?\n/g, '</div>');
  html = html.replace(/<\/h3>\r?\n/g, '</h3>');
  html = html.replace(/<\/h2>\r?\n/g, '</h2>');
  html = html.replace(/<\/table>\r?\n/g, '</table>');

  // Chuyển newline thành <br> để hiển thị markdown đúng cách
  html = html.replace(/\n\n/g, '<br><br>').replace(/\n/g, '<br>');

  return html;
}


/** Bubble text without the avatar/name header. */
function bubblePlainText(el: HTMLElement): string {
  const head = el.querySelector(":scope > .bubble-head");
  return (el.textContent ?? "").slice(head?.textContent?.length ?? 0);
}

function addChatMessage(role: "user" | "assistant", text: string): HTMLElement | null {
  console.log(`[UI] Adding ${role} message: ${text}`);
  if (!chatHistory) {
    console.error("[UI] Chat history element not found!");
    return null;
  }

  // De-duplication: Don't add the exact same message twice in a row
  const lastBubble = chatHistory.lastElementChild as HTMLElement;
  if (lastBubble && lastBubble.classList.contains(role) && bubblePlainText(lastBubble) === text) {
    console.log("[UI] Duplicate message detected, skipping add.");
    return lastBubble;
  }

  // Mark existing messages as 'old'
  const oldBubbles = chatHistory.querySelectorAll(".chat-bubble");
  oldBubbles.forEach((m) => m.classList.add("old"));

  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  chatHistory.appendChild(bubble);

  // Helper check for interactive card pattern in text
  // Định dạng có cấu trúc dạng: [INTERACTIVE_CARD_JSON]: { ... }
  const prefix = "[INTERACTIVE_CARD_JSON]:";
  if (role === "assistant" && text.startsWith(prefix)) {
    try {
      const jsonStr = text.substring(prefix.length).trim();
      const cardData = JSON.parse(jsonStr);
      renderInteractiveCard(bubble, cardData);
      // Cuộn xuống dưới
      requestAnimationFrame(() => {
        scrollToBottomIfNeeded();
      });
      return bubble;
    } catch (e) {
      console.error("[UI] Parse interactive card failed:", e);
    }
  }

  if (role === "user") {
    bubble.innerHTML = formatMarkdown(text);
    // Append to history panel in real-time (no API call)
    if (!historyPanel.classList.contains("hidden")) {
      appendHistoryEntry("user", text, Date.now() / 1000);
    }
    // Scroll to bottom (force since user just sent a message)
    requestAnimationFrame(() => {
      scrollToBottomIfNeeded(true);
    });
  } else {
    attachBubbleHead(bubble);
    // Hiệu ứng stream gõ chữ cho assistant
    let currentText = "";
    // Sử dụng regex để tách từ nhưng giữ nguyên các dấu xuống dòng và khoảng trắng
    const tokens = text.split(/(\s+)/);
    let i = 0;

    const timer = setInterval(() => {
      if (i < tokens.length) {
        currentText += tokens[i];
        setBubbleContent(bubble, formatMarkdown(currentText));
        i++;

        // Tự động cuộn xuống dưới
        scrollToBottomIfNeeded();
      } else {
        clearInterval(timer);
      }
    }, 15); // Tốc độ tối ưu cho token
  }

  // Keep reasonable history
  while (chatHistory.children.length > 36) {
    chatHistory.removeChild(chatHistory.firstChild!);
  }

  return bubble;
}


function openImageLightbox(src: string) {
  let lightbox = document.getElementById("image-lightbox") as HTMLElement;
  if (!lightbox) {
    lightbox = document.createElement("div");
    lightbox.id = "image-lightbox";

    const img = document.createElement("img");
    img.id = "lightbox-img";
    lightbox.appendChild(img);

    const closeBtn = document.createElement("button");
    closeBtn.innerHTML = "✕";
    closeBtn.id = "lightbox-close";
    closeBtn.style.cssText = "position:fixed; top:20px; right:20px; font-size:20px; color:#fff; background:rgba(8,10,18,0.7); border:1px solid rgba(0,212,255,0.3); border-radius:50%; width:44px; height:44px; display:flex; align-items:center; justify-content:center; cursor:pointer; z-index:2010; backdrop-filter:blur(5px);-webkit-backdrop-filter:blur(5px);box-shadow:0 0 10px rgba(0,212,255,0.2);";
    lightbox.appendChild(closeBtn);

    document.body.appendChild(lightbox);

    // Zoom & Pan state
    let scale = 1;
    let translateX = 0;
    let translateY = 0;
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let initialDistance = 0;
    let initialScale = 1;
    let lastTap = 0;

    const resetTransform = () => {
      scale = 1;
      translateX = 0;
      translateY = 0;
      img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
    };

    (lightbox as any)._resetTransform = resetTransform;

    const closeLightbox = () => {
      lightbox.classList.remove("active");
      setTimeout(() => {
        lightbox.style.display = "none";
        resetTransform();
      }, 250);
    };

    closeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeLightbox();
    });

    // Close when clicking outside the image container
    lightbox.addEventListener("click", (e) => {
      if (e.target === lightbox) {
        closeLightbox();
      }
    });

    // Touch events for pinch to zoom & drag to pan
    img.addEventListener("touchstart", (e) => {
      if (e.touches.length === 2) {
        e.preventDefault();
        initialDistance = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
        initialScale = scale;
      } else if (e.touches.length === 1) {
        // Double tap detection
        const now = Date.now();
        if (now - lastTap <= 300) {
          e.preventDefault();
          if (scale > 1) {
            scale = 1;
            translateX = 0;
            translateY = 0;
          } else {
            scale = 2.5;
          }
          img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
        } else {
          if (scale > 1) {
            isDragging = true;
            startX = e.touches[0].clientX - translateX;
            startY = e.touches[0].clientY - translateY;
          }
        }
        lastTap = now;
      }
    });

    img.addEventListener("touchmove", (e) => {
      if (e.touches.length === 2) {
        e.preventDefault();
        const dist = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
        scale = Math.min(Math.max(initialScale * (dist / initialDistance), 1), 4);
        img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
      } else if (e.touches.length === 1 && isDragging) {
        e.preventDefault();
        translateX = e.touches[0].clientX - startX;
        translateY = e.touches[0].clientY - startY;
        img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
      }
    });

    img.addEventListener("touchend", () => {
      isDragging = false;
    });
  }

  const lightboxImg = lightbox.querySelector("#lightbox-img") as HTMLImageElement;
  if (lightboxImg) {
    lightboxImg.src = src;
  }

  // Reset scale and position whenever opening
  if ((lightbox as any)._resetTransform) {
    (lightbox as any)._resetTransform();
  }

  lightbox.style.display = "flex";
  lightbox.offsetHeight; // Force reflow
  lightbox.classList.add("active");
}

function handleInteractiveCardData(cardData: any) {
  if (!cardData || !cardData.id) return;
  const existingBubble = document.querySelector(`.chat-bubble[data-card-id="${cardData.id}"]`) as HTMLElement;
  if (existingBubble) {
    renderInteractiveCard(existingBubble, cardData);
    return;
  }

  const cardBubble = document.createElement("div");
  cardBubble.className = "chat-bubble assistant";
  cardBubble.id = `card-${Date.now()}`;
  cardBubble.setAttribute("data-card-id", cardData.id);
  renderInteractiveCard(cardBubble, cardData);

  if (activeAssistantBubble && activeAssistantBubble.parentElement === chatHistory) {
    chatHistory.insertBefore(cardBubble, activeAssistantBubble);
  } else {
    chatHistory.appendChild(cardBubble);
  }

  requestAnimationFrame(() => {
    scrollToBottomIfNeeded();
  });
}


/** Agent step labels arrive as "Thực thi: <việc>"; the card already says it is running. */
const trackerLabel = (label?: string) => (label || "").replace(/^Thực thi:\s*/, "");

function renderInteractiveCard(container: HTMLElement, data: any) {
  const existingCard = container.querySelector(".interactive-card");
  // Tracker đổi trạng thái (active → completed/failed) là render lại cùng một card:
  // vá tại chỗ để icon trạng thái giữ nguyên phần tử và morph.
  const existingName = existingCard?.querySelector(".tracker-name");
  const existingIcon = existingCard?.querySelector(".tracker-icon-container");
  if (data.type === "tracker" && !data.image && existingIcon && !existingCard!.querySelector("img")
      && !!existingName === !!data.title) {
    existingCard!.className = `interactive-card tracker-card${data.status ? " " + data.status : ""}`;
    if (existingName) {
      existingName.textContent = agentBadge(data.title).name;
      if (activeAssistantBubble) setBubbleName(activeAssistantBubble, existingName.textContent);
    }
    existingCard!.querySelector(".tracker-label")!.textContent = trackerLabel(data.label);
    setStatusIcon(existingIcon, data.status, "tracker", 14);
    return;
  }
  if (existingCard) existingCard.remove();
  if (data.id) {
    container.setAttribute("data-card-id", data.id);
  }
  const card = document.createElement("div");
  card.className = "interactive-card";

  // tracker cards draw their own agent header (icon + name) below
  if (data.title && data.type !== "tracker") {
    const title = document.createElement("div");
    title.className = "interactive-card-title";
    title.textContent = data.title;
    card.appendChild(title);
  }

  if (data.type === "select") {
    const list = document.createElement("div");
    list.className = "interactive-select-list";

    const selectedValues = new Set<string>();

    data.options.forEach((opt: any) => {
      const optionEl = document.createElement("div");
      optionEl.className = "interactive-option";
      if (opt.selected) {
        optionEl.classList.add("selected");
        selectedValues.add(opt.value);
      }

      const dot = document.createElement("span");
      dot.className = "interactive-option-dot";
      optionEl.appendChild(dot);

      const label = document.createElement("span");
      label.textContent = opt.label;
      optionEl.appendChild(label);

      optionEl.addEventListener("click", () => {
        if (data.multiple) {
          if (selectedValues.has(opt.value)) {
            selectedValues.delete(opt.value);
            optionEl.classList.remove("selected");
          } else {
            selectedValues.add(opt.value);
            optionEl.classList.add("selected");
          }
        } else {
          list.querySelectorAll(".interactive-option").forEach(el => el.classList.remove("selected"));
          selectedValues.clear();
          selectedValues.add(opt.value);
          optionEl.classList.add("selected");
          submitBtn.disabled = false;
          submitBtn.textContent = data.submitLabel || "Xác nhận";
        }
      });

      list.appendChild(optionEl);
    });

    card.appendChild(list);

    const btnGroup = document.createElement("div");
    btnGroup.className = "interactive-btn-group";

    const submitBtn = document.createElement("button");
    submitBtn.className = "interactive-btn approve";
    submitBtn.textContent = data.submitLabel || "Xác nhận";
    submitBtn.addEventListener("click", () => {
      submitBtn.disabled = true;
      socket.send({
        type: "interactive_response",
        cardId: data.id,
        action: "submit",
        value: Array.from(selectedValues)
      });
      submitBtn.textContent = "Đã gửi";
    });

    btnGroup.appendChild(submitBtn);
    card.appendChild(btnGroup);

  } else if (data.type === "input") {
    if (data.description) {
      const desc = document.createElement("div");
      desc.className = "interactive-input-description";
      desc.textContent = data.description;
      card.appendChild(desc);
    }

    const input = document.createElement("textarea");
    input.className = "interactive-text-input";
    input.value = typeof data.value === "string" ? data.value : "";
    input.placeholder = data.placeholder || "Nhập nội dung...";
    input.rows = 4;
    input.setAttribute("aria-label", data.title || "Nhập nội dung");
    card.appendChild(input);

    const btnGroup = document.createElement("div");
    btnGroup.className = "interactive-btn-group";
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "interactive-btn reject";
    cancelBtn.textContent = data.cancelLabel || "Hủy";
    const submitBtn = document.createElement("button");
    submitBtn.className = "interactive-btn approve";
    submitBtn.textContent = data.submitLabel || "Xác nhận nội dung";

    const lock = () => {
      input.disabled = true;
      cancelBtn.disabled = true;
      submitBtn.disabled = true;
    };
    cancelBtn.addEventListener("click", () => {
      lock();
      socket.send({ type: "interactive_response", cardId: data.id, action: "cancel" });
      cancelBtn.textContent = "Đã hủy";
    });
    submitBtn.addEventListener("click", () => {
      lock();
      socket.send({
        type: "interactive_response", cardId: data.id, action: "submit", value: input.value
      });
      submitBtn.textContent = "Đã gửi";
    });
    btnGroup.appendChild(cancelBtn);
    btnGroup.appendChild(submitBtn);
    card.appendChild(btnGroup);

  } else if (data.type === "approve") {
    if (data.description) {
      const desc = document.createElement("div");
      desc.className = "interactive-card-desc";
      desc.textContent = data.description;
      card.appendChild(desc);
    }

    const btnGroup = document.createElement("div");
    btnGroup.className = "interactive-btn-group";

    const rejectBtn = document.createElement("button");
    rejectBtn.className = "interactive-btn reject";
    rejectBtn.textContent = data.rejectLabel || "Từ chối";

    const approveBtn = document.createElement("button");
    approveBtn.className = "interactive-btn approve";
    approveBtn.textContent = data.approveLabel || "Đồng ý";

    rejectBtn.addEventListener("click", () => {
      rejectBtn.disabled = true;
      approveBtn.disabled = true;
      socket.send({
        type: "interactive_response",
        cardId: data.id,
        action: "reject"
      });
      rejectBtn.textContent = "Đã từ chối";
    });

    approveBtn.addEventListener("click", () => {
      rejectBtn.disabled = true;
      approveBtn.disabled = true;
      socket.send({
        type: "interactive_response",
        cardId: data.id,
        action: "approve"
      });
      approveBtn.textContent = "Đã đồng ý";
    });

    btnGroup.appendChild(rejectBtn);
    btnGroup.appendChild(approveBtn);
    card.appendChild(btnGroup);

  } else if (data.type === "tracker") {
    card.classList.add("tracker-card");
    if (data.status) {
      card.classList.add(data.status);
    }
    const body = document.createElement("div");
    body.className = "tracker-body";

    const iconContainer = document.createElement("div");
    iconContainer.className = "tracker-icon-container";

    if (data.status) setStatusIcon(iconContainer, data.status, "tracker", 14);

    const label = document.createElement("div");
    label.className = "tracker-label";
    label.textContent = trackerLabel(data.label);

    if (data.image) {
      body.style.flexDirection = "column";
      body.style.alignItems = "flex-start";

      const headerRow = document.createElement("div");
      headerRow.style.display = "flex";
      headerRow.style.alignItems = "center";
      headerRow.style.gap = "12px";
      headerRow.appendChild(iconContainer);
      headerRow.appendChild(label);

      const img = document.createElement("img");
      img.src = `${data.image}?t=${Date.now()}`;
      img.alt = "Screenshot";
      img.style.maxWidth = "100%";
      img.style.maxHeight = "300px";
      img.style.objectFit = "contain";
      img.style.borderRadius = "6px";
      img.style.marginTop = "8px";
      img.style.display = "block";
      img.style.border = "1px solid rgba(255,255,255,0.1)";
      img.style.boxShadow = "0 4px 12px rgba(0,0,0,0.25)";
      img.style.cursor = "pointer";

      img.addEventListener("click", () => {
        openImageLightbox(img.src);
      });

      img.onload = () => {
        scrollToBottomIfNeeded();
      };

      body.appendChild(headerRow);
      body.appendChild(img);
    } else if (data.title) {
      const badge = agentBadge(data.title);
      if (activeAssistantBubble) setBubbleName(activeAssistantBubble, badge.name);
      const iconBox = document.createElement("span");
      iconBox.className = "tracker-agent-icon";
      iconBox.appendChild(badge.icon);
      const texts = document.createElement("div");
      texts.className = "tracker-texts";
      const name = document.createElement("div");
      name.className = "tracker-name";
      name.textContent = badge.name;
      texts.append(name, label);
      body.append(iconBox, texts, iconContainer);
    } else {
      body.appendChild(iconContainer);
      body.appendChild(label);
    }

    card.appendChild(body);
  }

  const textContainer = container.querySelector(".bubble-text");
  if (textContainer) {
    container.insertBefore(card, textContainer);
  } else {
    container.appendChild(card);
  }
}


function showError(msg: string) {

  errorEl.textContent = msg;
  errorEl.style.opacity = "1";
  window.dispatchEvent(new CustomEvent("jarvis:mascot", { detail: "error" }));
  setTimeout(() => {
    errorEl.style.opacity = "0";
  }, 5000);
}



// ---------------------------------------------------------------------------
// Status Dashboard Logic
// ---------------------------------------------------------------------------

const statusDashboard = document.getElementById("status-dashboard")!;

let hudContent: HTMLElement;
// System status state
let flowSteps: any[] = [];
let currentTurnId: string = Date.now().toString();



// Toggleable list states for Status Dashboard
let isMcpExpanded = false;
let isAgentsExpanded = false;

async function refreshDashboard() {
  try {
    const res = await fetchWithTimeout("/api/settings/status");
    const data = await res.json();
    const tokens = data.session_tokens || { input: 0, output: 0, total: 0 };

    const sys = data.system || {};
    const mcpServers = data.mcp_servers || {};
    const agents = data.agents || [];
    const mcpOnline = (s: string) => s === "connected" ? "active" : s === "reconnecting" ? "warn" : "error";
    const badgeCls = data.mcp_total > 0 && data.mcp_connected === data.mcp_total ? "active" : data.mcp_connected > 0 ? "warn" : "error";

    // Initialize HUD on first call
    const isFirstLoad = !hudContent;
    if (isFirstLoad) {
      hudContent = statusDashboard.querySelector(".hud-content") as HTMLElement;

      // Event delegation for toggleable panels and reset button
      hudContent.addEventListener("click", async (e) => {
        const target = e.target as HTMLElement;

        // Handle reset button click
        if (target.classList.contains("hud-btn-reset") || target.closest(".hud-btn-reset")) {
          e.stopPropagation();
          const btn = target.classList.contains("hud-btn-reset") ? target : target.closest(".hud-btn-reset") as HTMLElement;
          btn.style.opacity = "0.5";
          btn.style.pointerEvents = "none";
          try {
            const resetRes = await fetchWithTimeout("/api/settings/reset-tokens", { method: "POST" });
            if (resetRes.ok) {
              console.log("[Dashboard] Tokens reset successfully");
              flowSteps = [];
              // Trigger update immediately
              await refreshDashboard();
            }
          } catch (err) {
            console.error("[Dashboard] Failed to reset tokens:", err);
          } finally {
            btn.style.opacity = "";
            btn.style.pointerEvents = "";
          }
          return;
        }

        const header = target.closest(".hud-toggleable-header");
        if (header) {
          const type = header.getAttribute("data-toggle");
          const contentId = header.getAttribute("aria-controls");
          if (contentId) {
            const contentEl = hudContent.querySelector(`#${contentId}`) as HTMLElement;
            if (contentEl) {
              const isOpen = contentEl.classList.toggle("open");
              header.classList.toggle("open", isOpen);
              if (type === "mcp") {
                isMcpExpanded = isOpen;
              } else if (type === "agents") {
                isAgentsExpanded = isOpen;
              }
            }
          }
        }
      });
    }

    const ramPct = sys.ram_percent ?? 0;
    const cpuPct = sys.cpu_percent ?? 0;



    let gpuHtml = "";
    const gpus = sys.gpus || [];
    const npus = sys.npus || [];

    for (const gpu of gpus) {
      const vramTotal = gpu.mem_total_mb || gpu.vram_total_mb || 0;
      const vramUsed = gpu.mem_used_mb || 0;
      const memLabel = vramUsed && vramTotal ? `${vramUsed}/${vramTotal}MB` : vramTotal ? `${vramTotal}MB` : "";

      const shortName = gpu.name?.replace(/^(GeForce|Laptop)\s*/i, "").split(" ").slice(0, 4).join(" ") || "GPU";
      gpuHtml += `
        <div class="hud-row" style="margin-top: 4px;">
          <span title="${gpu.name}">${shortName}</span>
          <span class="hud-val">${memLabel}</span>
        </div>`;
    }

    for (const npu of npus) {
      const shortNpu = npu.replace(/\(R\)|\(TM\)/g, "").split(" ").slice(0, 4).join(" ");
      gpuHtml += `<div class="hud-row"><span title="${npu}" style="opacity:0.7">NPU</span><span class="hud-val" style="opacity:0.5">${shortNpu}</span></div>`;
    }

    if (!hudContent.querySelector("#hud-resources")) {
      hudContent.innerHTML = `
        <div class="hud-group compact">
          ${generateSystemsHTML(data.intelligence_core_ok, data.server_engine_ok, data.llm_server_ok, data.tts_server_ok)}
          
          <div class="hud-label hud-toggleable-header ${isMcpExpanded ? 'open' : ''}" style="margin-top:4px" data-toggle="mcp" aria-controls="mcp-list-content">
            <span>MCP Connect · <span class="hud-badge ${badgeCls}" id="hud-mcp-badge">${data.mcp_connected ?? 0}/${data.mcp_total ?? 0}</span></span>
            <span class="hud-arrow-icon">&#9654;</span>
          </div>
          <div class="hud-scroll hud-toggleable-content ${isMcpExpanded ? 'open' : ''}" id="mcp-list-content">${Object.entries(mcpServers).map(([name, status]) => {
        const cls = mcpOnline(status as string);
        return `<div class="hud-row"><span>${name}</span><div class="hud-dot ${cls}"></div></div>`;
      }).join("")}</div>

          <div class="hud-label hud-toggleable-header ${isAgentsExpanded ? 'open' : ''}" style="margin-top:4px" data-toggle="agents" aria-controls="agents-list-content">
            <span>Cognitive Agents · <span class="hud-badge active" id="hud-agents-badge">${agents.length}</span></span>
            <span class="hud-arrow-icon">&#9654;</span>
          </div>
          <div class="hud-scroll hud-toggleable-content ${isAgentsExpanded ? 'open' : ''}" id="agents-list-content">${agents.map((a: any) => `
            <div class="hud-row" style="display: flex; justify-content: space-between; align-items: center;">
              <span>${a.name.startsWith('Agent') ? a.name : `Agent ${a.name}`}</span>
              ${a.name === "Goose" || a.name === "Agent Goose" ? `
                <button class="hud-btn-launch-goose" onclick="fetch('/api/agents/goose/launch', {method: 'POST'})" style="background: rgba(14, 165, 233, 0.15); border: 1px solid rgba(14, 165, 233, 0.3); color: #0ea5e9; border-radius: 4px; padding: 2px 6px; font-size: 10px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.background='rgba(14, 165, 233, 0.3)'; this.style.color='#38bdf8';" onmouseout="this.style.background='rgba(14, 165, 233, 0.15)'; this.style.color='#0ea5e9';">Mở App</button>
              ` : `
                <span class="hud-val" style="opacity: 0.6; font-size: 10px;">${a.file}</span>
              `}
            </div>
          `).join("")}</div>
        </div>

        <div class="hud-group compact" id="hud-resources">
          ${generateResourcesHTML(cpuPct, ramPct, sys.ram_used_gb ?? "?", sys.ram_total_gb ?? "?", gpuHtml)}
        </div>

        <div class="hud-group compact">
          <div class="hud-label">Cognition</div>
          <div class="hud-row">
            <span>Sessions · Memory · Tasks</span>
            <span class="hud-val" id="hud-cognition-memories">${data.session_active ? '●' : '○'} ${data.memory_count} · ${data.task_count}</span>
          </div>
          <div class="hud-row">
            <span>Semantic · Conversations</span>
            <span class="hud-val" id="hud-cognition-semantic">${data.semantic_memory_count ?? 0} · ${data.conversation_turn_count ?? 0}</span>
          </div>
        </div>

        <div class="hud-group compact">
          <div class="hud-label" style="display:flex; justify-content:space-between; align-items:center;">
            <span>Cognitive Tokens</span>
            <button class="hud-btn-reset" title="Reset Token Usage" style="background:transparent; border:none; color:#0ea5e9; cursor:pointer; padding:4px; display:inline-flex; align-items:center; justify-content:center; border-radius:4px; border:1px solid rgba(14, 165, 233, 0.15); transition:all 0.2s;" onmouseover="this.style.borderColor='rgba(14, 165, 233, 0.4)'; this.style.color='#38bdf8';" onmouseout="this.style.borderColor='rgba(14, 165, 233, 0.15)'; this.style.color='#0ea5e9';">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
              </svg>
            </button>
          </div>
          <div class="hud-row"><span>Input Tokens</span><span class="hud-val" id="hud-tokens-input">${tokens.input.toLocaleString()}</span></div>
          <div class="hud-row"><span>Output Tokens</span><span class="hud-val" id="hud-tokens-output">${tokens.output.toLocaleString()}</span></div>
          <div class="hud-row"><span class="highlight">Total Tokens</span><span class="hud-val highlight" id="hud-tokens-total">${tokens.total.toLocaleString()}</span></div>
        </div>

        <div class="hud-group compact">
          <div class="hud-label">Modules · ${data.skill_count ?? 0} skills · ${data.command_count ?? 0} commands</div>
          <div class="hud-row">
            <span>Hooks · Plugins</span>
            <span class="hud-val highlight">${data.hooks_loaded ?? 0} · ${data.plugins_loaded ?? 0}</span>
          </div>
          <div class="hud-row"><span>Uptime</span><span class="hud-val" id="hud-uptime">${formatUptime(data.uptime_seconds)}</span></div>
        </div>
      `;
      if (isFirstLoad) statusDashboard.classList.add("loaded");
    } else {
      const resourcesEl = hudContent.querySelector("#hud-resources");
      if (resourcesEl) {
        resourcesEl.innerHTML = generateResourcesHTML(cpuPct, ramPct, sys.ram_used_gb ?? "?", sys.ram_total_gb ?? "?", gpuHtml);
      }
      const tokensInput = document.getElementById("hud-tokens-input");
      const tokensOutput = document.getElementById("hud-tokens-output");
      const tokensTotal = document.getElementById("hud-tokens-total");
      if (tokensInput) tokensInput.textContent = tokens.input.toLocaleString();
      if (tokensOutput) tokensOutput.textContent = tokens.output.toLocaleString();
      if (tokensTotal) tokensTotal.textContent = tokens.total.toLocaleString();

      // Cập nhật động phần Cognition, Uptime và MCP
      const cogMemories = document.getElementById("hud-cognition-memories");
      const cogSemantic = document.getElementById("hud-cognition-semantic");
      if (cogMemories) {
        cogMemories.textContent = `${data.session_active ? '●' : '○'} ${data.memory_count} · ${data.task_count}`;
      }
      if (cogSemantic) {
        cogSemantic.textContent = `${data.semantic_memory_count ?? 0} · ${data.conversation_turn_count ?? 0}`;
      }

      const hudUptime = document.getElementById("hud-uptime");
      if (hudUptime) {
        hudUptime.textContent = formatUptime(data.uptime_seconds);
      }

      const mcpBadge = document.getElementById("hud-mcp-badge");
      if (mcpBadge) {
        mcpBadge.className = `hud-badge ${badgeCls}`;
        mcpBadge.textContent = `${data.mcp_connected ?? 0}/${data.mcp_total ?? 0}`;
      }

      const mcpListContent = document.getElementById("mcp-list-content");
      if (mcpListContent) {
        mcpListContent.innerHTML = Object.entries(mcpServers).map(([name, status]) => {
          const cls = mcpOnline(status as string);
          return `<div class="hud-row"><span>${name}</span><div class="hud-dot ${cls}"></div></div>`;
        }).join("");
      }

      const agentsBadge = document.getElementById("hud-agents-badge");
      if (agentsBadge) {
        agentsBadge.textContent = agents.length.toString();
      }
      const agentsListContent = document.getElementById("agents-list-content");
      if (agentsListContent) {
        agentsListContent.innerHTML = agents.map((a: any) => `
          <div class="hud-row" style="display: flex; justify-content: space-between; align-items: center;">
            <span>${a.name.startsWith('Agent') ? a.name : `Agent ${a.name}`}</span>
            ${a.name === "Goose" || a.name === "Agent Goose" ? `
              <button class="hud-btn-launch-goose" onclick="fetch('/api/agents/goose/launch', {method: 'POST'})" style="background: rgba(14, 165, 233, 0.15); border: 1px solid rgba(14, 165, 233, 0.3); color: #0ea5e9; border-radius: 4px; padding: 2px 6px; font-size: 10px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.background='rgba(14, 165, 233, 0.3)'; this.style.color='#38bdf8';" onmouseout="this.style.background='rgba(14, 165, 233, 0.15)'; this.style.color='#0ea5e9';">Mở App</button>
            ` : `
              <span class="hud-val" style="opacity: 0.6; font-size: 10px;">${a.file}</span>
            `}
          </div>
        `).join("");
      }
    }

  } catch (e) {
    console.error("[Dashboard] Refresh failed:", e);
  }
}

/** "Định tuyến → general" → ["Định tuyến", "general"]; drops trailing "..." / "…". */
function splitStepLabel(label: string): [string, string] {
  const clean = (label || "").replace(/(\.{3}|…)\s*$/, "").trim();
  const i = clean.indexOf("→");
  return i < 0 ? [clean, ""] : [clean.slice(0, i).trim(), clean.slice(i + 1).trim()];
}

function updateFlowMonitor() {
  if (!activeFlowBubble || flowSteps.length === 0) return;

  // Tìm bước đang active để hiển thị ở dòng tóm tắt accordion
  const activeStep = flowSteps.find(s => s.status === 'active');
  const lastCompleted = [...flowSteps].reverse().find(s => s.status === 'completed');
  const summaryStep = activeStep || lastCompleted;
  const hasFailure = flowSteps.some(s => s.status === 'failed');

  const completedCount = flowSteps.filter(s => s.status === 'completed').length;
  const totalCount = flowSteps.length;

  const summaryStatus = activeStep ? "active" : hasFailure ? "failed" : "completed";
  const summaryLabel = summaryStep ? summaryStep.label : 'Đang xử lý...';

  // Dựng khung một lần cho mỗi bubble; các lần sau chỉ vá nội dung để icon
  // trạng thái giữ nguyên phần tử và morph (vòng xoay → ✓) thay vì bị thay mới.
  let summary = activeFlowBubble.querySelector<HTMLElement>(".flow-accordion-summary");
  if (!summary) {
    activeFlowBubble.innerHTML = `
      <div class="flow-accordion-header" onclick="this.closest('.system-flow').classList.toggle('flow-expanded')">
        <div class="flow-accordion-summary">
          <span class="flow-summary-icon" style="display:contents"></span>
          <span class="flow-summary-label"></span>
          <span class="flow-step-count"></span>
        </div>
        <svg class="flow-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:10px;height:10px;flex-shrink:0;transition:transform 0.25s ease;">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </div>
      <div class="flow-progress"><i></i></div>
      <div class="flow-accordion-body">
        <div class="flow-content-inline"></div>
      </div>
    `;
    summary = activeFlowBubble.querySelector<HTMLElement>(".flow-accordion-summary")!;
  }
  setStatusIcon(summary.querySelector(".flow-summary-icon")!, summaryStatus, "flow", 12);
  summary.querySelector(".flow-summary-label")!.textContent = splitStepLabel(summaryLabel)[0];
  summary.querySelector(".flow-step-count")!.textContent = `${completedCount}/${totalCount}`;
  const bar = activeFlowBubble.querySelector<HTMLElement>(".flow-progress > i");
  if (bar) bar.style.width = `${totalCount ? (completedCount / totalCount) * 100 : 0}%`;
  activeFlowBubble.dataset.status = summaryStatus;

  // Chi tiết tất cả các bước (hiển thị khi expand), khớp theo step.id
  const list = activeFlowBubble.querySelector(".flow-content-inline")!;
  for (const step of flowSteps) {
    let row = list.querySelector<HTMLElement>(`:scope > [data-step-id="${CSS.escape(String(step.id))}"]`);
    if (!row) {
      row = document.createElement("div");
      row.className = "flow-step-row";
      row.dataset.stepId = String(step.id);
      row.innerHTML = `<span class="flow-step-label"><span class="flow-step-text"></span><span class="flow-step-detail"></span></span>`;
      list.appendChild(row);
    }
    // timeline dot is CSS, keyed on data-status
    const [main, detail] = splitStepLabel(step.label);
    row.dataset.status = step.status;
    row.querySelector(".flow-step-text")!.textContent = main;
    row.querySelector(".flow-step-detail")!.textContent = detail;
  }

  activeFlowBubble.style.display = "block";
  // Tự động mở rộng khi có các bước đang chạy để người dùng theo dõi
  if (isBusy || currentState === "thinking" || currentState === "working" || activeStep) {
    activeFlowBubble.classList.add("flow-expanded");
  }

  // Tự động cuộn xuống dưới
  requestAnimationFrame(() => {
    scrollToBottomIfNeeded();
  });
}

function collapseFlowTrackers() {
  const expandedFlows = chatHistory.querySelectorAll<HTMLElement>(".chat-bubble.system-flow.flow-expanded");
  expandedFlows.forEach((flow) => {
    flow.classList.remove("flow-expanded");
  });
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

// Nạp snapshot HUD một lần khi WebUI khởi động.
// Các chỉ số động được làm mới theo sự kiện hoàn tất phiên chat.
void refreshDashboard();

// ---------------------------------------------------------------------------
// Webcam HUD Logic
// ---------------------------------------------------------------------------

const webcamHud = document.getElementById("webcam-hud")!;
const webcamVideo = document.getElementById("webcam-video") as HTMLVideoElement;
const webcamCanvas = document.getElementById("webcam-canvas") as HTMLCanvasElement;
const webcamOverlay = document.getElementById("webcam-overlay") as HTMLImageElement;
const webcamSelect = document.getElementById("webcam-device-select") as HTMLSelectElement;
const btnWebcamFullscreen = document.getElementById("btn-webcam-fullscreen");
let webcamStream: MediaStream | null = null;
let selectedCameraId: string | null = null;

let handLandmarker: any = null;
let handDetectionActive = false;
let isInitializingHandLandmarker = false;

async function initHandLandmarker() {
  if (handLandmarker) return handLandmarker;
  if (isInitializingHandLandmarker) return null;
  isInitializingHandLandmarker = true;
  try {
    console.log("[MediaPipe] Initializing Hand Landmarker...");
    const { FilesetResolver, HandLandmarker } =
      await import("@mediapipe/tasks-vision");
    const vision = await FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.8/wasm"
    );
    handLandmarker = await HandLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
        delegate: "GPU"
      },
      runningMode: "VIDEO",
      numHands: 2
    });
    console.log("[MediaPipe] Hand Landmarker initialized successfully!");
    isInitializingHandLandmarker = false;
    return handLandmarker;
  } catch (err) {
    console.error("[MediaPipe] Failed to initialize Hand Landmarker:", err);
    isInitializingHandLandmarker = false;
    return null;
  }
}

// Releases the GPU-backed WASM model so its VRAM isn't held while the webcam is off.
function disposeHandLandmarker() {
  if (handLandmarker) {
    try {
      handLandmarker.close();
    } catch (err) {
      console.error("[MediaPipe] Failed to close Hand Landmarker:", err);
    }
    handLandmarker = null;
  }
}

function predictWebcamHands() {
  if (!handDetectionActive || !webcamStream || !webcamVideo || !handLandmarker || !webcamCanvas) {
    return;
  }

  const ctx = webcamCanvas.getContext("2d");
  if (!ctx) return;

  // Cập nhật kích thước canvas khớp với video thực tế
  webcamCanvas.width = webcamVideo.videoWidth || 640;
  webcamCanvas.height = webcamVideo.videoHeight || 480;

  ctx.clearRect(0, 0, webcamCanvas.width, webcamCanvas.height);

  if (webcamVideo.readyState >= 2 && webcamVideo.currentTime !== -1) {
    const startTimeMs = performance.now();
    try {
      const results = handLandmarker.detectForVideo(webcamVideo, startTimeMs);
      if (results && results.landmarks && results.landmarks.length > 0) {
        for (const landmarks of results.landmarks) {
          const tips = [4, 8, 12, 16, 20];
          for (const tipIdx of tips) {
            const lm = landmarks[tipIdx];
            if (lm) {
              const cx = lm.x * webcamCanvas.width;
              const cy = lm.y * webcamCanvas.height;

              // Vòng phát sáng neon mờ xung quanh (glow)
              ctx.beginPath();
              ctx.arc(cx, cy, tipIdx === 8 ? 10 : 7, 0, 2 * Math.PI);
              ctx.fillStyle = "rgba(0, 212, 255, 0.35)";
              ctx.fill();

              // Điểm nhân màu trắng rực rỡ
              ctx.beginPath();
              ctx.arc(cx, cy, tipIdx === 8 ? 4 : 3, 0, 2 * Math.PI);
              ctx.fillStyle = "#ffffff";
              ctx.fill();

              // Viền ngoài sắc nét
              ctx.beginPath();
              ctx.arc(cx, cy, tipIdx === 8 ? 13 : 9, 0, 2 * Math.PI);
              ctx.strokeStyle = "rgba(0, 212, 255, 0.8)";
              ctx.lineWidth = 1.5;
              ctx.stroke();
            }
          }
        }
      }
    } catch (err) {
      console.error("[MediaPipe] Detection error:", err);
    }
  }

  if (handDetectionActive) {
    requestAnimationFrame(predictWebcamHands);
  }
}

if (btnWebcamFullscreen) {
  btnWebcamFullscreen.addEventListener("click", () => {
    webcamHud.classList.toggle("full-view");
    btnWebcamFullscreen.classList.toggle("active");
  });
}

// Giao diện lắng nghe sự thay đổi camera thiết bị từ select dropdown
if (webcamSelect) {
  webcamSelect.addEventListener("change", async () => {
    selectedCameraId = webcamSelect.value;
    if (webcamStream) {
      // Tắt stream cũ đi trước khi mở stream mới
      webcamStream.getTracks().forEach(track => track.stop());
      webcamStream = null;
    }
    await startWebcamStream();
  });
}

// Chức năng bật webcam thực tế
async function startWebcamStream() {
  try {
    console.log("[Webcam] Starting webcam stream with deviceId:", selectedCameraId);
    const constraints: MediaStreamConstraints = {
      video: selectedCameraId
        ? {
          deviceId: { ideal: selectedCameraId },
          width: { ideal: 640 },
          height: { ideal: 480 },
          frameRate: { ideal: 15 }
        }
        : {
          width: { ideal: 640 },
          height: { ideal: 480 },
          frameRate: { ideal: 15 }
        }
    };
    webcamStream = await navigator.mediaDevices.getUserMedia(constraints);
    webcamVideo.srcObject = webcamStream;

    webcamVideo.onloadedmetadata = () => {
      const labelEl = document.querySelector(".hud-label-cam");
      if (labelEl) {
        labelEl.textContent = `CAM-01 ACTIVE (${webcamVideo.videoWidth}x${webcamVideo.videoHeight})`;
      }
      console.log(`[Webcam] Current Active Resolution: ${webcamVideo.videoWidth}x${webcamVideo.videoHeight}`);
      if (webcamStream) {
        const track = webcamStream.getVideoTracks()[0];
        if (track && typeof track.getCapabilities === "function") {
          console.log("[Webcam] Hardware Capabilities (Supported Range):", track.getCapabilities());
        }
      }
    };

    // Đảm bảo video được phát ngay lập tức
    await webcamVideo.play().catch(err => console.warn("[Webcam] Autoplay prevented, waiting for interaction:", err));

    // Cập nhật lại dropdown danh sách thiết bị
    await populateCameraDevices();

    // Khởi chạy nhận diện bàn tay thời gian thực
    handDetectionActive = true;
    initHandLandmarker().then((landmarker) => {
      if (landmarker && handDetectionActive) {
        requestAnimationFrame(predictWebcamHands);
      }
    });
  } catch (err) {
    console.error("[Webcam] Error starting webcam:", err);
    showError("Không thể truy cập Webcam, thưa Ngài.");
  }
}

// Lấy danh sách các camera của máy hoặc điện thoại gắn vào
async function populateCameraDevices() {
  if (!webcamSelect) return;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const videoDevices = devices.filter(d => d.kind === "videoinput");

    // Lưu lại giá trị đang chọn
    const currentVal = webcamSelect.value || selectedCameraId;
    webcamSelect.innerHTML = "";

    videoDevices.forEach((device, idx) => {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.label || `Camera ${idx + 1}`;
      if (device.deviceId === currentVal) {
        option.selected = true;
      }
      webcamSelect.appendChild(option);
    });

    // Nếu chưa cấu hình camera mặc định, chọn thiết bị đầu tiên làm mặc định
    if (!selectedCameraId && videoDevices.length > 0) {
      selectedCameraId = videoDevices[0].deviceId;
    }
  } catch (err) {
    console.error("[Webcam] Error enumerating video devices:", err);
  }
}

async function toggleWebcam(show: boolean) {
  const btnWebcam = document.getElementById("btn-webcam-toggle");
  if (show) {
    try {
      console.log("[Webcam] Requesting access...");
      await startWebcamStream();
      webcamHud.classList.remove("hidden");
      // Small delay to ensure display:flex is applied before animation
      requestAnimationFrame(() => {
        webcamHud.classList.add("visible");
        if (btnWebcam) btnWebcam.classList.add("active");
      });
    } catch (e) {
      console.error("[Webcam] Access denied or error:", e);
      showError("Không thể truy cập Webcam, thưa Ngài.");
    }
  } else {
    handDetectionActive = false;
    if (webcamCanvas) {
      const ctx = webcamCanvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, webcamCanvas.width, webcamCanvas.height);
    }
    webcamHud.classList.remove("visible");
    webcamHud.classList.remove("full-view");
    if (btnWebcam) btnWebcam.classList.remove("active");
    if (btnWebcamFullscreen) btnWebcamFullscreen.classList.remove("active");
    if (webcamOverlay) webcamOverlay.style.display = "none";
    setTimeout(() => {
      webcamHud.classList.add("hidden");
      if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
        webcamVideo.srcObject = null;
      }
      disposeHandLandmarker();
    }, 800); // Match CSS transition
  }
}

// Chụp ảnh hiện tại trên thẻ video và gửi trả về server
function captureAndSendWebcamFrame() {
  if (webcamOverlay) webcamOverlay.style.display = "none";
  if (!webcamVideo || !webcamStream) {
    socket.send({ type: "webcam_capture_response", image: "ERROR:NO_STREAM" });
    return;
  }

  try {
    const canvas = document.createElement("canvas");
    canvas.width = webcamVideo.videoWidth || 640;
    canvas.height = webcamVideo.videoHeight || 480;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.drawImage(webcamVideo, 0, 0, canvas.width, canvas.height);
      // Chuyển sang dạng JPEG chất lượng cao
      const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
      const base64Data = dataUrl.split(",")[1];
      socket.send({ type: "webcam_capture_response", image: base64Data });
      console.log("[Webcam] Frame captured and sent successfully via WebSocket.");
    } else {
      socket.send({ type: "webcam_capture_response", image: "ERROR:CANVAS_CONTEXT_FAIL" });
    }
  } catch (err) {
    console.error("[Webcam] Error capturing frame:", err);
    socket.send({ type: "webcam_capture_response", image: `ERROR:${err}` });
  }
}

// ---------------------------------------------------------------------------
// Init components
// ---------------------------------------------------------------------------

const canvas = document.getElementById("orb-canvas") as HTMLCanvasElement;
const orb = createOrb(canvas);

const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
const WS_URL = `${wsProto}//${window.location.host}/ws/voice`;
const socket = createSocket(WS_URL);

function showSupersededBanner(reason: string, onReconnect: () => void) {
  let banner = document.getElementById("superseded-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "superseded-banner";
    banner.style.cssText = `
      position: fixed;
      top: 16px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(24, 24, 27, 0.95);
      border: 1px solid rgba(239, 68, 68, 0.4);
      color: #f87171;
      padding: 10px 18px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 500;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
      z-index: 9999;
      display: flex;
      align-items: center;
      gap: 12px;
      backdrop-filter: blur(8px);
    `;
    document.body.appendChild(banner);
  }

  const otherDevice = socket.getDeviceType() === "mobile" ? "Desktop" : "Mobile";
  banner.innerHTML = `
    <span>⚠️ Phiên kết nối đã chuyển sang thiết bị khác (${otherDevice}). Tự động ngắt để tránh xung đột.</span>
    <button id="reconnect-btn" style="
      background: #ef4444;
      color: white;
      border: none;
      padding: 5px 12px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
    ">Kết nối lại tại đây</button>
  `;

  const btn = banner.querySelector("#reconnect-btn");
  if (btn) {
    btn.addEventListener("click", () => {
      if (banner) banner.remove();
      onReconnect();
    });
  }
}

socket.onSuperseded((reason) => {
  console.warn(`[ws] Superseded: ${reason}`);
  showSupersededBanner(reason, () => {
    socket.reconnectManual();
  });
});

const audioPlayer = createAudioPlayer();
orb.setAnalyser(audioPlayer.getAnalyser());

function updateStatus(state: State, message?: string) {
  // Determine if we should show "listening"
  const isCurrentlyListening = voiceInput.isListening();
  const canListen = isCurrentlyListening && document.activeElement !== commandInput;

  console.log(`[UI] updateStatus: state=${state}, message=${message}, canListen=${canListen}, isBusy=${isBusy}`);

  // Track the type of work for the "speaking" state fallback
  if (state === "thinking" || state === "working") {
    lastWorkState = state;
  }

  const labels: Record<State, string> = {
    idle: canListen ? "Đang nghe…" : "Sẵn sàng",
    listening: "Đang nghe…",
    thinking: "Đang nghĩ…",
    working: "Đang làm việc…",
    speaking: "Đang trả lời…",
    restarting: "Đang khởi động lại…",
  };

  const newText = message || labels[state];
  if (statusEl.textContent !== newText) {
    statusEl.textContent = newText;
  }
}



function updateInputControls(state: State) {
  const inner = document.getElementById("command-bar-inner");
  if (!inner) return;
  const busy = state === "thinking" || state === "working" || state === "speaking" || audioPlayer.isPlaying();
  if (busy) {
    inner.classList.add("busy");
  } else {
    inner.classList.remove("busy");
  }
}

function transition(newState: State, message?: string) {
  if (newState === "idle") {
    collapseFlowTrackers();
  }

  let effectiveState = newState;
  if (newState === "idle" && !isMuted && !audioPlayer.isPlaying()) {
    effectiveState = "listening";
  }

  if (effectiveState === currentState && !message) return;
  currentState = effectiveState;
  orb.setState(effectiveState as OrbState);
  window.dispatchEvent(new CustomEvent("jarvis:mascot", { detail: effectiveState }));

  // Update class for CSS styling (e.g., color changes)
  statusEl.className = `status-${effectiveState}`;

  updateStatus(effectiveState, message);
  updateInputControls(effectiveState);

  switch (effectiveState) {
    case "listening":
      if (!isMuted && document.activeElement !== commandInput) {
        voiceInput.resume();
      }
      break;
    case "idle":
      voiceInput.pause();
      break;
    case "thinking":
    case "working":
    case "speaking":
      voiceInput.pause();
      break;
  }
}

// ---------------------------------------------------------------------------
// Voice input
// ---------------------------------------------------------------------------

const voiceInput = createVoiceInput(
  (text: string) => {
    const cleanedTranscript = text.trim().toLowerCase();
    const currentSpeakingLower = (activeAssistantText || "").toLowerCase();

    // Text Matching Filter: Avoid self-interruption if transcript matches Jarvis's own TTS output
    const isSelfEcho = currentSpeakingLower.length > 5 && (
      currentSpeakingLower.includes(cleanedTranscript) ||
      cleanedTranscript.includes(currentSpeakingLower)
    );

    if ((isSpeaking || audioPlayer.isPlaying()) && !isSelfEcho) {
      console.log("[voice] Natural Interruption: User spoke during playback ->", text);
      audioPlayer.stop();
      isSpeaking = false;
      isBusy = false;

      // Notify backend to cancel current response stream
      socket.send({ type: "cancel" });

      // Immediately process user's new spoken query
      addChatMessage("user", text);
      addToCommandHistory(text);
      if (deliverTranscript(text)) transition("thinking");
    } else if (isSpeaking || audioPlayer.isPlaying() || isBusy || currentState === "thinking" || currentState === "working") {
      const bubble = addChatMessage("user", text);
      if (bubble) bubble.classList.add("pending");
      pendingQueriesQueue.push({ type: "voice", text, bubbleElement: bubble || undefined });
      console.log("[voice] Jarvis is busy/speaking. Enqueued query:", text);
    } else {
      // Cancel any current JARVIS response before sending new input
      audioPlayer.stop();
      // User spoke — send transcript
      addChatMessage("user", text);
      addToCommandHistory(text); // Sync voice to command bar history
      if (deliverTranscript(text)) transition("thinking");
    }
  },
  (msg: string) => {
    showError(msg);
  }
);

// Wire up microphone status change to UI update
voiceInput.onStatusChange(() => {
  console.log("[voice] microphone state changed:", voiceInput.isListening());
  updateStatus(currentState);
});

// ---------------------------------------------------------------------------
// Audio playback finished
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Barge-in detector — ngắt JARVIS ngay khi phát hiện người dùng bắt đầu nói,
// không chờ STT (Web Speech API / Whisper) trả về transcript cuối cùng. STT
// vẫn chạy song song như cũ để biết NÓI GÌ; detector này chỉ lo việc NGẮT LỜI
// càng sớm càng tốt bằng cách theo dõi năng lượng mic độc lập.
// ---------------------------------------------------------------------------

const interruptDetector = createInterruptDetector(() => {
  if (!(isSpeaking || audioPlayer.isPlaying())) return; // an toàn, tránh kích hoạt thừa
  console.log("[voice] Barge-in detected — stopping playback and cancelling response");
  audioPlayer.stop();
  isSpeaking = false;
  isBusy = false;
  socket.send({ type: "cancel" });
  transition("listening");
});

audioPlayer.onStarted(() => {
  isSpeaking = true;
  if (currentState !== "speaking") {
    transition("speaking");
  }
  if (!isMuted) {
    interruptDetector.start();
  }
});

audioPlayer.onFinished(() => {
  isSpeaking = false;
  interruptDetector.stop();

  if (pendingQueriesQueue.length > 0) {
    const nextQuery = pendingQueriesQueue.shift()!;
    console.log("[queue] Processing next enqueued query:", nextQuery.text);
    if (nextQuery.bubbleElement) {
      nextQuery.bubbleElement.classList.remove("pending");
    }
    if (nextQuery.type === "text" && nextQuery.file) {
      uploadAndSend(nextQuery.text, nextQuery.file);
    } else {
      socket.send({ type: "transcript", text: nextQuery.text, isFinal: true });
      addToCommandHistory(nextQuery.text);
      transition("thinking");
    }
  } else if (isTtsDisabled) {
    isBusy = false;
    transition("idle");
  } else {
    if (isBusy) {
      transition(lastWorkState);
    } else {
      transition("idle");
    }
  }
});

// ---------------------------------------------------------------------------
// WebSocket messages
// ---------------------------------------------------------------------------

socket.onMessage((msg) => {
  const type = msg.type as string;

  if (type === "audio") {
    const audioData = msg.data as string;
    console.log("[audio] received", audioData ? `${audioData.length} chars` : "EMPTY", "state:", currentState);
    if (isTtsDisabled) return;
    if (audioData) {
      // isSpeaking/transition("speaking") is driven by audioPlayer.onStarted()
      // instead of here — it only fires once real playback begins, so stale
      // audio for an already-cancelled turn can't force the UI into a
      // "speaking" state that never actually plays anything.
      audioPlayer.enqueue(audioData);
    } else {
      // TTS failed — no audio but still need to return to idle
      console.warn("[audio] no data received, returning to idle");
      isSpeaking = false;
      transition("idle");
    }
    // Log text for debugging and show in UI if provided
    if (msg.text) {
      console.log("[JARVIS]", msg.text);
      if (!wasStreamed) {
        addChatMessage("assistant", msg.text as string);
      }
    }
  } else if (type === "stream_start") {
    wasStreamed = false;
    activeAssistantText = "";
    flowSteps = [];
    currentTurnId = Date.now().toString();
    refreshDashboard();

    // Mark existing messages as 'old'
    const oldBubbles = chatHistory.querySelectorAll(".chat-bubble");
    oldBubbles.forEach((m) => m.classList.add("old"));

    activeFlowBubble = document.createElement("div");
    activeFlowBubble.className = "chat-bubble system-flow";
    activeFlowBubble.style.display = "none"; // Ẩn mặc định cho đến khi có step thực tế gửi từ backend
    activeFlowBubble.innerHTML = `<div class="flow-title"><span>Hoạt động hệ thống</span><span class="flow-monitor-pulse" style="width:5px;height:5px;border-radius:50%;background:#0ea5e9;box-shadow:0 0 6px #0ea5e9;display:inline-block;"></span></div><div class="flow-content-inline" style="opacity:0.6;">Đang khởi tạo tiến trình...</div>`;
    chatHistory.appendChild(activeFlowBubble);

    // 2. Tạo bong bóng chat cho phản hồi của Assistant (LLM)
    activeAssistantBubble = document.createElement("div");
    // Thêm class typing-loader với hiệu ứng Gemini Live Fluid Aurora 3 giọt hòa sắc (Mẫu 29)
    activeAssistantBubble.className = "chat-bubble assistant typing-loader";
    activeAssistantBubble.innerHTML = `
      <div class="gemini-mesh-container">
        <div class="gemini-blob gemini-blob-1"></div>
        <div class="gemini-blob gemini-blob-2"></div>
        <div class="gemini-blob gemini-blob-3"></div>
      </div>
    `;
    attachBubbleHead(activeAssistantBubble);
    chatHistory.appendChild(activeAssistantBubble);

    requestAnimationFrame(() => {
      scrollToBottomIfNeeded(true); // Force scroll when new stream starts
      startStreamTypewriter();
    });
  } else if (type === "text_chunk") {
    const chunkText = msg.text as string;
    if (chunkText && activeAssistantBubble) {
      if (activeAssistantBubble.classList.contains("typing-loader")) {
        activeAssistantBubble.classList.remove("typing-loader");
        setBubbleContent(activeAssistantBubble, "");
      }
      activeAssistantText += chunkText;
      streamTargetText = activeAssistantText; // Feed typewriter target buffer
    }
  } else if (type === "audio_chunk") {
    const chunkBase64 = msg.data as string;
    if (!chunkBase64) return;
    if (isTtsDisabled) return;
    // isSpeaking/transition("speaking") driven by audioPlayer.onStarted() —
    // this only buffers raw bytes; real playback starts at audio_chunk_end.
    const binary = atob(chunkBase64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    if (!audioChunkBuffer) {
      audioChunkBuffer = [];
    }
    audioChunkBuffer.push(bytes);
  } else if (type === "pcm_chunk") {
    // VieNeu: phát ngay từng đoạn PCM, tách khỏi nhánh edge (audio_chunk) ở trên.
    const pcmBase64 = msg.data as string;
    if (!pcmBase64 || isTtsDisabled) return;
    audioPlayer.enqueuePcm(pcmBase64, (msg.sample_rate as number) || 48000, (msg.gap_ms as number) || 0);
  } else if (type === "audio_chunk_end") {
    if (!isTtsDisabled && audioChunkBuffer && audioChunkBuffer.length > 0) {
      const totalLen = audioChunkBuffer.reduce((sum, b) => sum + b.length, 0);
      const combined = new Uint8Array(totalLen);
      let offset = 0;
      for (const b of audioChunkBuffer) {
        combined.set(b, offset);
        offset += b.length;
      }
      audioChunkBuffer = null;
      audioPlayer.enqueueRaw(combined.buffer);
    } else {
      audioChunkBuffer = null;
    }
  } else if (type === "stream_end") {
    wasStreamed = true;
    stopStreamTypewriter();

    // Đảm bảo xả toàn bộ chữ còn lại ra màn hình
    if (activeAssistantBubble) {
      if (activeAssistantBubble.classList.contains("typing-loader")) {
        activeAssistantBubble.classList.remove("typing-loader");
        setBubbleContent(activeAssistantBubble, "");
      }
      let textContainer = activeAssistantBubble.querySelector(".bubble-text") as HTMLElement;
      if (!textContainer) {
        textContainer = document.createElement("div");
        textContainer.className = "bubble-text";
        activeAssistantBubble.appendChild(textContainer);
      }
      textContainer.innerHTML = formatMarkdown(activeAssistantText);
      scrollToBottomIfNeeded();
    }
    activeAssistantBubble = null;
    // Giữ flow bubble để nhận các flow_step completed gửi sau stream_end.
    // Auto-refresh history panel after response completes
    if (!historyPanel.classList.contains("hidden")) {
      appendHistoryEntry("assistant", activeAssistantText, Date.now() / 1000);
    }
  } else if (type === "status") {
    const state = msg.state as string;
    const message = msg.message as string;
    if (msg.source === "tts" && isTtsDisabled) return;
    if (state === "thinking" || state === "working") {
      isBusy = true;
      if (currentState !== state) {
        transition(state as State, message);
      } else {
        updateStatus(state as State, message);
      }
    } else if (state === "idle") {
      isBusy = false;
      // Don't transition to idle while audio is still playing —
      // let audioPlayer.onFinished() handle the transition instead
      if (!audioPlayer.isPlaying() && !isSpeaking) {
        transition("idle");
      }
      void refreshDashboard();
    } else if (state === "speaking") {
      if (currentState !== "speaking") {
        transition("speaking", message);
      } else {
        updateStatus("speaking", message);
      }
    }
  } else if (type === "text") {
    // Text fallback when TTS fails
    console.log("[JARVIS]", msg.text);
    if (!wasStreamed || (msg.text as string).startsWith("💡")) {
      addChatMessage("assistant", msg.text as string);
    }
  } else if (type === "media_open") {
    const query = msg.query as string;
    const embedUrl = msg.embed_url as string;
    const title = msg.title as string;
    if (embedUrl) {
      const sep = embedUrl.includes('?') ? '&' : '?';
      const html = `<iframe src="${embedUrl}${sep}autoplay=1" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen scrolling="no"></iframe>`;
      openMediaPlayer(title || query, html);
    }
  } else if (type === "webcam_capture_request") {
    captureAndSendWebcamFrame();
  } else if (type === "webcam_processed") {
    const imgB64 = msg.image as string;
    if (imgB64 && webcamOverlay) {
      webcamOverlay.src = "data:image/jpeg;base64," + imgB64;
      webcamOverlay.style.display = "block";
      setTimeout(() => {
        if (webcamOverlay.style.display === "block") {
          webcamOverlay.style.display = "none";
        }
      }, 4000);
    }
  } else if (type === "screenshot_processed") {
    const url = msg.url as string;
    if (url) {
      const activeId = (window as any)._activeScreenshotTrackerId || `screenshot_tracker_${currentTurnId}_${Date.now()}`;
      handleInteractiveCardData({
        id: activeId,
        type: "tracker",
        title: "📷 CHỤP MÀN HÌNH",
        status: "completed",
        label: "Đã chụp màn hình thành công.",
        image: url
      });
      // Reset ID
      delete (window as any)._activeScreenshotTrackerId;
    }
  } else if (type === "history") {

    const history = msg.history as any[];
    console.log(`[UI] Synchronizing HUD Chat History with ${history?.length} records.`);
    if (history && history.length > 0) {
      // Direct update to HUD, not chat bubbles
      renderHistory(history);
    }
  } else if (type === "interactive") {
    const cardData = (msg as any).card;
    handleInteractiveCardData(cardData);
  } else if (type === "flow_step") {
    const step = msg.step as any;
    if (step && step.id) {
      const idx = flowSteps.findIndex(s => s.id === step.id);
      if (idx >= 0) {
        flowSteps[idx] = step;
      } else {
        flowSteps.push(step);
      }
      // Flow steps only drive the chat bubble. This used to go through
      // refreshDashboard(), so every step of every turn fired a heavy
      // /api/settings/status round-trip (psutil + GPU + MCP listing) at exactly
      // the moment latency matters most.
      updateFlowMonitor();
    }

  } else if (type === "pins") {
    const pins = msg.pins as any[];
    cachedPins = pins || [];
    if (mapLibreMap) {
      // Clear old markers
      pinnedMarkers.forEach(m => m.remove());
      pinnedMarkers = [];
      // Add new markers
      cachedPins.forEach(pin => addPinToMap(pin));
    }
  } else if (type === "memory_updated") {
    refreshDashboard();
  }
});

// ---------------------------------------------------------------------------
// Kick off
// ---------------------------------------------------------------------------

// Ngăn ngừa các lỗi tự động zoom/pinch-to-zoom gây lệch tọa độ canvas/Orb trên mobile
(() => {
  let lastTouchEnd = 0;
  document.addEventListener("touchend", (e) => {
    const now = Date.now();
    if (now - lastTouchEnd <= 300) {
      e.preventDefault();
    }
    lastTouchEnd = now;
  }, { passive: false });

  document.addEventListener("gesturestart", (e) => {
    e.preventDefault();
  });
})();

// Start listening after a brief delay for the orb to render
setTimeout(() => {
  // Initialize mute state visually
  btnMute.classList.toggle("muted", isMuted);
  btnTtsToggle.classList.toggle("muted", isTtsDisabled);

  if (!isMuted) {
    voiceInput.start();
    transition("listening");
  } else {
    voiceInput.pause();
    transition("idle");
  }

  // Hide HUD by default on mobile, but keep Command Bar visible
  const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || window.innerWidth <= 768;

  if (isMobile) {
    statusDashboard.classList.add("hidden");
    btnHud.classList.remove("active");
  } else {
    // Show by default on PC
    statusDashboard.classList.remove("hidden");
    btnHud.classList.add("active");
  }

  toggleCommandBar(true); // Always show command bar by default
  updateScrollFade(); // Initial check
  // Load dashboard data after dashboard is revealed (loading skeleton visible first)
  refreshDashboard();
}, 1000);



// Resume AudioContext on ANY user interaction (browser autoplay policy)
function ensureAudioContext() {
  const ctx = audioPlayer.getAnalyser().context as AudioContext;
  if (ctx.state === "suspended") {
    ctx.resume().then(() => console.log("[audio] context resumed"));
  }
}
document.addEventListener("click", ensureAudioContext);
document.addEventListener("touchstart", ensureAudioContext);
document.addEventListener("keydown", ensureAudioContext, { once: true });

// Try to resume audio context on load
ensureAudioContext();

// ---------------------------------------------------------------------------
// UI Controls
// ---------------------------------------------------------------------------

const btnMute = document.getElementById("btn-mute")!;
const btnTtsToggle = document.getElementById("btn-tts-toggle")!;
const btnMenu = document.getElementById("btn-menu")!;
const menuDropdown = document.getElementById("menu-dropdown")!;
const btnRestart = document.getElementById("btn-restart")!;

btnMute.addEventListener("click", (e) => {
  e.stopPropagation();
  isMuted = !isMuted;
  btnMute.classList.toggle("muted", isMuted);
  btnMute.classList.toggle("active", !isMuted);
  if (isMuted) {
    voiceInput.pause();
    interruptDetector.stop();
    if (currentState === "listening" || currentState === "idle") {
      transition("idle");
    }
  } else {
    voiceInput.start();
    if (isSpeaking || audioPlayer.isPlaying()) {
      interruptDetector.start();
    }
    if (currentState === "idle") {
      transition("listening");
    }
  }
  updateStatus(currentState);
});

btnTtsToggle.addEventListener("click", (e) => {
  e.stopPropagation();
  isTtsDisabled = !isTtsDisabled;
  localStorage.setItem("jarvis_tts_disabled", isTtsDisabled ? "true" : "false");
  btnTtsToggle.classList.toggle("muted", isTtsDisabled);
  socket.send({ type: "toggle_tts", enabled: !isTtsDisabled });
  if (isTtsDisabled) {
    isBusy = false;
    isSpeaking = false;
    audioPlayer.stop();
    audioChunkBuffer = null;
    transition("idle");
  }
  console.log("[TTS] Toggled TTS. Disabled:", isTtsDisabled);
});

const btnHud = document.getElementById("btn-hud")!;
btnHud.addEventListener("click", (e) => {
  e.stopPropagation();
  statusDashboard.classList.toggle("hidden");
  btnHud.classList.toggle("active", !statusDashboard.classList.contains("hidden"));
});

btnMenu.addEventListener("click", (e) => {
  e.stopPropagation();
  menuDropdown.style.display = menuDropdown.style.display === "none" ? "block" : "none";
});

document.addEventListener("click", () => {
  menuDropdown.style.display = "none";
});

// Top-left controls
const btnWebcamToggle = document.getElementById("btn-webcam-toggle")!;
btnWebcamToggle.addEventListener("click", (e) => {
  e.stopPropagation();
  const isVisible = webcamHud.classList.contains("visible");
  toggleWebcam(!isVisible);
});

// Restart status tracking — the WebSocket reconnecting to the new worker is
// the "restart succeeded" signal (mirrors the Telegram restart-notice flow),
// so "restarting..." is cleared the moment the new server accepts the socket.
let restartPending = false;
const RESTART_RETURN_TIMEOUT_MS = 30000;

btnRestart.addEventListener("click", async (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  restartPending = true;
  // Đẩy state machine về "restarting" để transition("idle") sau này không bị
  // early-return (statusEl đã được ghi trực tiếp, không qua updateStatus()).
  currentState = "restarting";
  statusEl.textContent = "Đang khởi động lại…";
  statusEl.className = "status-restarting";
  try {
    await fetchWithTimeout("/api/restart", { method: "POST" });
  } catch {
    restartPending = false;
    transition("idle");
    statusEl.textContent = "Khởi động lại thất bại";
    return;
  }
  // Nếu server không quay lại trong 30s, đừng để UI kẹt mãi ở "restarting...".
  setTimeout(() => {
    if (restartPending) {
      restartPending = false;
      transition("idle");
      statusEl.textContent = "Khởi động lại thất bại (server không phản hồi)";
    }
  }, RESTART_RETURN_TIMEOUT_MS);
});

socket.onReconnect(() => {
  if (restartPending) {
    restartPending = false;
    // Worker mới đã lên → xóa "restarting...".
    transition("idle");
  }
});

// Settings button
const btnSettings = document.getElementById("btn-settings")!;
btnSettings.addEventListener("click", (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  openSettings();
});

// Logs Modal UI -----------------------------------------------------------
const btnLogs = document.getElementById("btn-logs");
if (btnLogs) {
  btnLogs.addEventListener("click", (e) => {
    e.stopPropagation();
    menuDropdown.style.display = "none";
    openLogViewer();
  });
}

function openLogViewer() {
  const overlay = document.createElement("div");
  overlay.className = "log-viewer-overlay";

  const panel = document.createElement("div");
  panel.className = "log-viewer-panel";

  panel.innerHTML = `
    <div class="log-header">
      <h3>SYSTEM DIAGNOSTICS (JARVIS.LOG)</h3>
      <button class="log-close">CLOSE</button>
    </div>
    <div class="log-content"><div class="log-loading">Loading logs...</div></div>
  `;

  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  requestAnimationFrame(() => overlay.classList.add("open"));

  const closeBtn = panel.querySelector(".log-close")!;
  const contentEl = panel.querySelector(".log-content")!;

  closeBtn.addEventListener("click", () => {
    overlay.classList.remove("open");
    setTimeout(() => {
      overlay.remove();
    }, 350);
  });

  loadLogs(contentEl);
}

async function loadLogs(container: Element) {
  try {
    const res = await fetchWithTimeout("/api/logs?lines=300");
    const data = await res.json();
    if (data.success) {
      const lines = data.logs.split("\n");
      container.innerHTML = lines.map((line: string) => {
        let cls = "";
        if (line.includes("ERROR")) cls = "error";
        else if (line.includes("WARNING")) cls = "warning";
        else if (line.includes("INFO")) cls = "info";
        return `<div class="log-line ${cls}">${line}</div>`;
      }).join("");
      // Scroll to bottom
      container.scrollTop = container.scrollHeight;
    } else {
      container.textContent = "Không thể tải log: " + data.error;
    }
  } catch (e) {
    container.textContent = "Lỗi kết nối khi tải log.";
  }
}


// First-time setup detection — check after a short delay for server readiness
setTimeout(() => {
  checkFirstTimeSetup();
}, 2000);

// ---------------------------------------------------------------------------
// Command Bar
// ---------------------------------------------------------------------------

// Command Bar controls
const cmdSend = document.getElementById("cmd-send") as HTMLButtonElement;
const btnCmdBar = document.getElementById("btn-cmd-bar")!;
const btnUpload = document.getElementById("btn-upload") as HTMLButtonElement;
const fileUploadInput = document.getElementById("file-upload") as HTMLInputElement;

let cmdBarVisible = false;
let cmdHistory: string[] = [];
let cmdHistoryIdx = -1;

function addToCommandHistory(text: string) {
  if (!text) return;
  // Remove duplicate if it exists to bring it to top
  cmdHistory = cmdHistory.filter(h => h !== text);
  cmdHistory.unshift(text);
  if (cmdHistory.length > 30) cmdHistory.pop();
  cmdHistoryIdx = -1;
}

function toggleCommandBar(forceShow?: boolean) {
  cmdBarVisible = forceShow !== undefined ? forceShow : !cmdBarVisible;
  const commandContainer = document.getElementById("command-container")!;

  commandContainer.classList.toggle("visible", cmdBarVisible);
  btnCmdBar.classList.toggle("active", cmdBarVisible);
  if (cmdBarVisible) {
    setTimeout(() => commandInput.focus(), 50);
  } else {
    commandInput.blur();
  }
}

async function uploadAndSend(text: string, file: File) {
  if (currentState === "idle" || currentState === "listening") {
    transition("thinking", `Đang tải ${file.name}…`);
  }
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetchWithTimeout("/api/upload", { method: "POST", body: formData }, UPLOAD_FETCH_TIMEOUT_MS);
    const data = await res.json();

    if (data.success) {
      socket.send({
        type: "transcript",
        text,
        attachmentId: data.attachment_id,
        isFinal: true
      });
    } else {
      showError(`Upload failed: ${data.error}`);
      if (currentState === "thinking") {
        transition("idle");
      }
    }
  } catch (e) {
    showError("Upload failed due to a network error.");
    if (currentState === "thinking") {
      transition("idle");
    }
  }
}

function deliverTranscript(text: string): boolean {
  if (socket.send({ type: "transcript", text, isFinal: true })) return true;
  // The socket used to swallow this silently while the caller went on to
  // transition("thinking"), leaving the UI spinning forever on a message the
  // server never received.
  addChatMessage("assistant", "⚠️ Mất kết nối tới máy chủ — tin nhắn chưa gửi được, đang thử kết nối lại.");
  transition("idle");
  return false;
}

function dismissKeyboardOnMobile() {
  commandInput.blur();
  const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || window.innerWidth <= 768;
  if (isMobile) {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    document.body.scrollTop = 0;
    document.documentElement.scrollTop = 0;
  }
}

async function sendCommand() {
  dismissKeyboardOnMobile();
  const text = commandInput.value.trim();
  if (!text && !pendingFile) return;

  // Clear input immediately for responsiveness
  commandInput.value = "";
  commandInput.style.height = "24px"; // Reset height

  // Trigger hiệu ứng morphicons: máy bay giấy -> Check (đã gửi) -> quay lại máy bay giấy
  cmdSend.classList.add("sent");
  setTimeout(() => {
    cmdSend.classList.remove("sent");
  }, 1000);

  if (isSpeaking || audioPlayer.isPlaying() || isBusy || currentState === "thinking" || currentState === "working") {
    const bubble = addChatMessage("user", pendingFile ? `📎 [${pendingFile.name}] ${text}` : text);
    if (bubble) bubble.classList.add("pending");
    pendingQueriesQueue.push({ type: "text", text, file: pendingFile || undefined, bubbleElement: bubble || undefined });
    clearPendingFile();
    console.log("[command] Jarvis is busy/speaking. Enqueued query:", text);
    return;
  }

  if (pendingFile) {
    const file = pendingFile;
    clearPendingFile(); // Hide chip

    // Show as user message with file icon
    addChatMessage("user", `📎 [${file.name}] ${text}`);
    uploadAndSend(text, file);
  } else {
    // Standard text message
    addChatMessage("user", text);
    if (deliverTranscript(text) && (currentState === "idle" || currentState === "listening")) {
      transition("thinking");
    }
  }

  // Save to history
  addToCommandHistory(text);
}

function clearPendingFile() {
  pendingFile = null;
  fileUploadInput.value = "";
  filePinnedContainer.style.display = "none";
}

// Shortcut: Ctrl+K
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "k") {
    e.preventDefault();
    toggleCommandBar();
  }
});

// Toggle button
btnCmdBar.addEventListener("click", (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  toggleCommandBar();
});

btnUpload.addEventListener("click", (e) => {
  e.stopPropagation();
  fileUploadInput.click();
});

fileUploadInput.addEventListener("change", () => {
  if (fileUploadInput.files && fileUploadInput.files.length > 0) {
    pendingFile = fileUploadInput.files[0];
    filePinnedName.textContent = pendingFile.name;
    filePinnedContainer.style.display = "flex";
    commandInput.focus();
  }
});

btnFileRemove.addEventListener("click", (e) => {
  e.stopPropagation();
  clearPendingFile();
});

// Function to automatically adjust the height of the command input textarea
function adjustInputHeight() {
  commandInput.style.height = "24px"; // Reset to baseline
  const scrollHeight = commandInput.scrollHeight;
  // Use scrollHeight if it exceeds baseline, but clamp to max-height (140px)
  if (scrollHeight > 24) {
    commandInput.style.height = `${Math.min(scrollHeight, 140)}px`;
  }
}

// ---------------------------------------------------------------------------
// Suggestions Autocomplete Logic
// ---------------------------------------------------------------------------
let suggestCommands: any[] = [];
let suggestAgents: string[] = ["agent_desktop", "router_agent"];
let suggestFiles: string[] = [];
let suggestActiveIndex = -1;
let suggestFilteredList: any[] = [];
let suggestType: "/" | "@" | null = null;
let suggestActiveTab = "all";
const commandSuggestEl = document.getElementById("command-suggest")!;

// Prevent the command input from blurring (and hiding the panel via the blur
// handler) when the user clicks inside the suggestion panel, e.g. switching tabs.
commandSuggestEl.addEventListener("mousedown", (e) => {
  e.preventDefault();
});

async function fetchSuggestionsData() {
  try {
    const resSkills = await fetchWithTimeout("/api/command-bar/skills");
    const dataSkills = await resSkills.json();
    if (dataSkills.success) {
      suggestCommands = dataSkills.commands || [];
    }
    const resCtx = await fetchWithTimeout("/api/command-bar/context");
    const dataCtx = await resCtx.json();
    if (dataCtx.success) {
      suggestAgents = dataCtx.agents || ["agent_desktop", "router_agent"];
      suggestFiles = dataCtx.files || [];
    }
  } catch (e) {
    console.error("[Suggestions] Failed to fetch suggestions data:", e);
  }
}

function getActiveToken(input: HTMLTextAreaElement) {
  const value = input.value;
  const selStart = input.selectionStart || 0;

  // Find start of current token (separated by whitespace)
  let start = selStart - 1;
  while (start >= 0 && !/\s/.test(value[start])) {
    start--;
  }
  start++;

  const token = value.slice(start, selStart);
  return { token, start, end: selStart };
}

function renderSuggestions(type: "/" | "@", filterText: string) {
  commandSuggestEl.innerHTML = "";
  suggestFilteredList = [];
  const q = filterText.toLowerCase();

  // Render Tabs Header
  const tabsContainer = document.createElement("div");
  tabsContainer.className = "suggest-tabs";

  // "/" only lists commands/*.md — the only thing engine/server/slash_commands.py runs.
  const tabs = type === "/"
    ? [{ id: "all", label: "Lệnh" }]
    : [
      { id: "all", label: "Tất cả" },
      { id: "agent", label: "Tác nhân" },
      { id: "file", label: "Tệp tin" }
    ];

  tabs.forEach(t => {
    const tabEl = document.createElement("span");
    tabEl.className = "suggest-tab" + (suggestActiveTab === t.id ? " active" : "");
    tabEl.textContent = t.label;
    tabEl.addEventListener("click", (e) => {
      e.stopPropagation();
      suggestActiveTab = t.id;
      suggestActiveIndex = 0;
      renderSuggestions(type, filterText);
    });
    tabsContainer.appendChild(tabEl);
  });
  commandSuggestEl.appendChild(tabsContainer);

  if (type === "/") {
    const filteredCmds = suggestCommands
      .filter(c => c.name.toLowerCase().includes(q) || (c.description || "").toLowerCase().includes(q))
      .map(c => ({ name: "/" + c.name, desc: c.description || "", tabType: "command", icon: "⚡" }));
    const combined = filteredCmds;

    // De-duplicate by name
    const seen = new Set<string>();
    for (const item of combined) {
      if (!seen.has(item.name)) {
        seen.add(item.name);
        if (suggestActiveTab === "all" || item.tabType === suggestActiveTab) {
          suggestFilteredList.push({ ...item, type: "command" });
        }
      }
    }
  } else if (type === "@") {
    // 1. Filter agents
    const filteredAgents = suggestAgents
      .filter(a => a.toLowerCase().includes(q))
      .map(a => ({ name: "@" + a, desc: "Tác nhân Agent", tabType: "agent", type: "agent", icon: "🤖" }));

    // 2. Filter files
    const filteredFiles = suggestFiles
      .filter(f => f.toLowerCase().includes(q))
      .map(f => ({ name: "@" + f, desc: f, tabType: "file", type: "file", icon: "📄" }));

    const combined = [...filteredAgents, ...filteredFiles];
    for (const item of combined) {
      if (suggestActiveTab === "all" || item.tabType === suggestActiveTab) {
        suggestFilteredList.push(item);
      }
    }
  }

  if (suggestFilteredList.length === 0) {
    // If no filtered items, we still show the tabs header but show an empty state
    const emptyEl = document.createElement("div");
    emptyEl.className = "suggest-empty";
    emptyEl.textContent = "Không tìm thấy kết quả phù hợp.";
    commandSuggestEl.appendChild(emptyEl);
    commandSuggestEl.classList.remove("hidden");
    return;
  }

  // Ensure index is within range
  if (suggestActiveIndex >= suggestFilteredList.length) {
    suggestActiveIndex = suggestFilteredList.length - 1;
  }
  if (suggestActiveIndex < 0 && suggestFilteredList.length > 0) {
    suggestActiveIndex = 0;
  }

  // Render items
  suggestFilteredList.forEach((item, index) => {
    const el = document.createElement("div");
    el.className = "suggest-item" + (index === suggestActiveIndex ? " active" : "");
    el.innerHTML = `
      <div class="suggest-item-left">
        <span class="suggest-item-icon">${item.icon}</span>
        <span class="suggest-item-name">${item.name}</span>
      </div>
      <span class="suggest-item-desc" title="${item.desc}">${item.desc}</span>
    `;

    el.addEventListener("click", () => {
      selectSuggestion(item.name);
    });

    commandSuggestEl.appendChild(el);
  });

  commandSuggestEl.classList.remove("hidden");
}

function selectSuggestion(selectedValue: string) {
  const { start, end } = getActiveToken(commandInput);
  const val = commandInput.value;

  // Replace the token with selected value
  commandInput.value = val.slice(0, start) + selectedValue + " " + val.slice(end);
  const newCursorPos = start + selectedValue.length + 1;
  commandInput.setSelectionRange(newCursorPos, newCursorPos);

  hideSuggestions();
  commandInput.focus();
  adjustInputHeight();
}

function hideSuggestions() {
  commandSuggestEl.classList.add("hidden");
  suggestType = null;
  suggestActiveIndex = -1;
  suggestFilteredList = [];
}

// Adjust height as user types and update suggestions
commandInput.addEventListener("input", () => {
  adjustInputHeight();

  const { token } = getActiveToken(commandInput);
  if (token.startsWith("/") || token.startsWith("@")) {
    const newType = token[0] as "/" | "@";
    if (newType !== suggestType) {
      suggestActiveTab = "all";
      suggestActiveIndex = 0;
    }
    suggestType = newType;
    const filterText = token.slice(1);
    renderSuggestions(suggestType, filterText);
  } else {
    hideSuggestions();
  }
});

// Send on Enter, history on Up/Down, navigation in suggestions
commandInput.addEventListener("keydown", (e) => {
  // Navigation in suggestions dropdown if open
  if (!commandSuggestEl.classList.contains("hidden") && suggestFilteredList.length > 0) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      suggestActiveIndex = (suggestActiveIndex + 1) % suggestFilteredList.length;
      renderSuggestions(suggestType!, getActiveToken(commandInput).token.slice(1));
      return;
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      suggestActiveIndex = (suggestActiveIndex - 1 + suggestFilteredList.length) % suggestFilteredList.length;
      renderSuggestions(suggestType!, getActiveToken(commandInput).token.slice(1));
      return;
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (suggestActiveIndex >= 0 && suggestActiveIndex < suggestFilteredList.length) {
        selectSuggestion(suggestFilteredList[suggestActiveIndex].name);
      }
      return;
    } else if (e.key === "Escape") {
      e.preventDefault();
      hideSuggestions();
      return;
    }
  }

  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    dismissKeyboardOnMobile();
    sendCommand();
  } else if (e.key === "Escape") {
    toggleCommandBar(false);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (cmdHistory.length > 0) {
      cmdHistoryIdx = Math.min(cmdHistoryIdx + 1, cmdHistory.length - 1);
      commandInput.value = cmdHistory[cmdHistoryIdx];
      commandInput.setSelectionRange(commandInput.value.length, commandInput.value.length);
      adjustInputHeight();
    }
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    cmdHistoryIdx = Math.max(cmdHistoryIdx - 1, -1);
    commandInput.value = cmdHistoryIdx >= 0 ? cmdHistory[cmdHistoryIdx] : "";
    adjustInputHeight();
  }
});

// Send button click
cmdSend.addEventListener("click", () => {
  dismissKeyboardOnMobile();
  sendCommand();
});

// Auto-mute when input is focused or clicked and prefetch suggestions
commandInput.addEventListener("focus", () => {
  voiceInput.pause();
  fetchSuggestionsData(); // prefetch skills and files list
});

commandInput.addEventListener("mousedown", (e) => {
  e.stopPropagation();
  voiceInput.pause();
});

commandInput.addEventListener("blur", () => {
  // Hide suggestions with delay to allow clicks
  setTimeout(() => {
    hideSuggestions();
  }, 200);

  // Resume if not muted and not busy
  if (!isMuted && !isBusy) {
    voiceInput.resume();
    if (currentState === "idle") {
      transition("listening");
    }
  }
});

// Ctrl+K global shortcut to focus command bar
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "k") {
    e.preventDefault();
    toggleCommandBar(true);
  }
});

async function toggleHistory(forceShow?: boolean) {
  const isOpening = forceShow !== undefined ? forceShow : historyPanel.classList.contains("hidden");
  historyPanel.classList.toggle("hidden", !isOpening);
  btnHistory.classList.toggle("active", isOpening);
  if (isOpening) {
    loadHistory();
  }
}

async function loadHistory() {
  historyList.innerHTML = '<div class="history-loading"><span></span><span></span><span></span></div>';
  try {
    const res = await fetchWithTimeout("/api/history?limit=100");
    const data = await res.json();
    if (data.success && data.history) {
      renderHistory(data.history);
    } else {
      historyList.innerHTML = '<div class="history-empty">Không có lịch sử hội thoại.</div>';
    }
  } catch (e) {
    historyList.innerHTML = '<div class="history-empty">Lỗi khi tải lịch sử.</div>';
  }
}

function appendHistoryEntry(role: string, content: string, created_at: number) {
  if (historyList.classList.contains("history-empty") || historyList.querySelector(".history-empty, .history-loading")) {
    historyList.innerHTML = "";
  }
  const date = new Date(created_at * 1000);
  const dateKey = date.toLocaleDateString();
  const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  // Date separator
  const lastSep = historyList.querySelector(".history-date-sep:last-child");
  const today = new Date();
  const isToday = dateKey === today.toLocaleDateString();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const label = isToday ? "Hôm nay" : dateKey === yesterday.toLocaleDateString() ? "Hôm qua" : dateKey;
  if (!lastSep || lastSep.textContent !== label) {
    const sep = document.createElement("div");
    sep.className = "history-date-sep";
    sep.textContent = label;
    historyList.appendChild(sep);
  }
  const item = document.createElement("div");
  item.className = `history-item ${role}`;
  const text = formatMarkdown(content.trim());
  item.innerHTML = `
    <div class="history-content">${text}</div>
    <span class="history-time">${timeStr}</span>
  `;
  historyList.appendChild(item);
  historyList.scrollTop = historyList.scrollHeight;
}

function renderHistory(history: any[]) {
  historyList.innerHTML = "";
  if (history.length === 0) {
    historyList.innerHTML = '<div class="history-empty">Không có dữ liệu hội thoại</div>';
    return;
  }

  let lastDate = "";

  history.forEach((msg, idx) => {
    const date = new Date(msg.created_at * 1000);
    const dateKey = date.toLocaleDateString();
    const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (dateKey !== lastDate) {
      lastDate = dateKey;
      const sep = document.createElement("div");
      sep.className = "history-date-sep";
      const today = new Date();
      const isToday = dateKey === today.toLocaleDateString();
      const yesterday = new Date(today);
      yesterday.setDate(yesterday.getDate() - 1);
      const label = isToday ? "Hôm nay" : dateKey === yesterday.toLocaleDateString() ? "Hôm qua" : dateKey;
      sep.textContent = label;
      historyList.appendChild(sep);
    }

    const item = document.createElement("div");
    item.className = `history-item ${msg.role}`;
    item.style.animationDelay = `${idx * 15}ms`;

    const content = msg.content.trim();
    const text = formatMarkdown(content);

    item.innerHTML = `
      <div class="history-content">${text}</div>
      <span class="history-time">${timeStr}</span>
    `;
    historyList.appendChild(item);
  });

  requestAnimationFrame(() => {
    historyList.scrollTop = historyList.scrollHeight;
  });
}

btnHistory.addEventListener("click", () => {
  menuDropdown.style.display = "none";
  toggleHistory();
});

btnCloseHistory.addEventListener("click", () => {
  toggleHistory();
});

// ---------------------------------------------------------------------------
// Map Panel
// ---------------------------------------------------------------------------

function toggleMap(forceShow?: boolean) {
  const isOpening = forceShow !== undefined ? forceShow : mapPanel.classList.contains("hidden");
  mapPanel.classList.toggle("hidden", !isOpening);
  btnMap.classList.toggle("active", isOpening);

  if (isOpening) {
    initMap();

    // On mobile, always open in full screen. On desktop, default to mini mode.
    const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || window.innerWidth <= 768;

    if (isMobile) {
      mapPanel.classList.remove("mini-mode");
      mapPanel.classList.add("full-screen");
      isMapFullScreen = true;
      orb.pause(); // Pause only in full screen
    } else {
      mapPanel.classList.add("mini-mode");
      mapPanel.classList.remove("full-screen");
      isMapFullScreen = false;
      orb.resume(); // Keep orb running in mini mode
    }
  } else {
    orb.resume();
  }
}

function toggleMapFullScreen() {
  isMapFullScreen = !isMapFullScreen;
  mapPanel.classList.toggle("mini-mode", !isMapFullScreen);
  mapPanel.classList.toggle("full-screen", isMapFullScreen);
  document.getElementById("btn-map-full")?.classList.toggle("active", isMapFullScreen);

  // Orb control: pause if full screen, resume if mini
  if (isMapFullScreen) {
    orb.pause();
  } else {
    orb.resume();
  }

  // Trigger map resize after animation
  setTimeout(() => mapLibreMap?.resize(), 600);
}

let poiMarkers: any[] = [];

async function addRouteToMap(from: [number, number], to: [number, number]) {
  if (!mapLibreMap) return;
  try {
    const url = `https://router.project-osrm.org/route/v1/driving/${from[0]},${from[1]};${to[0]},${to[1]}?overview=full&geometries=geojson`;
    const res = await fetchWithTimeout(url);
    const data = await res.json();
    if (data.routes && data.routes.length > 0) {
      const route = data.routes[0].geometry;

      if (mapLibreMap.getLayer("route")) mapLibreMap.removeLayer("route");
      if (mapLibreMap.getSource("route")) mapLibreMap.removeSource("route");

      mapLibreMap.addSource("route", {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: route
        }
      });

      mapLibreMap.addLayer({
        id: "route",
        type: "line",
        source: "route",
        layout: {
          "line-join": "round",
          "line-cap": "round"
        },
        paint: {
          "line-color": "#00d4ff",
          "line-width": 5,
          "line-opacity": 0.85
        }
      });

      const coordinates = route.coordinates;
      const bounds = coordinates.reduce((acc: any, coord: any) => {
        return acc.extend(coord);
      }, new (window as any).maplibregl.LngLatBounds(coordinates[0], coordinates[0]));

      mapLibreMap.fitBounds(bounds, { padding: 50, duration: 1500 });
    }
  } catch (e) {
    console.error("OSRM Route drawing failed:", e);
  }
}

function addPOIMarkers(pois: any[]) {
  if (!mapLibreMap) return;
  const maplibregl = (window as any).maplibregl;

  poiMarkers.forEach(m => m.remove());
  poiMarkers = [];

  pois.forEach(poi => {
    const el = document.createElement("div");
    el.className = "poi-marker";
    el.style.width = "20px";
    el.style.height = "20px";
    el.style.backgroundColor = "#00d4ff";
    el.style.border = "2px solid #fff";
    el.style.borderRadius = "50%";
    el.style.boxShadow = "0 0 10px rgba(0, 212, 255, 0.5)";
    el.style.cursor = "pointer";

    const popup = new maplibregl.Popup({ offset: 25 })
      .setHTML(`<div style="color:#000;padding:5px;font-size:12px;font-weight:bold;">${poi.name}</div>`);

    const marker = new maplibregl.Marker(el)
      .setLngLat([poi.lng, poi.lat])
      .setPopup(popup)
      .addTo(mapLibreMap);

    poiMarkers.push(marker);
  });

  if (pois.length > 0) {
    const bounds = new maplibregl.LngLatBounds();
    pois.forEach(poi => bounds.extend([poi.lng, poi.lat]));
    mapLibreMap.fitBounds(bounds, { padding: 80, duration: 1500 });
  }
}

function addAdminBoundaryToMap(geojson: any, bounds: number[] | null) {
  if (!mapLibreMap || !geojson) return;

  if (mapLibreMap.getLayer("admin-boundary-fill")) mapLibreMap.removeLayer("admin-boundary-fill");
  if (mapLibreMap.getLayer("admin-boundary-line")) mapLibreMap.removeLayer("admin-boundary-line");
  if (mapLibreMap.getSource("admin-boundary")) mapLibreMap.removeSource("admin-boundary");

  mapLibreMap.addSource("admin-boundary", { type: "geojson", data: geojson });
  mapLibreMap.addLayer({
    id: "admin-boundary-fill",
    type: "fill",
    source: "admin-boundary",
    paint: { "fill-color": "#00d4ff", "fill-opacity": 0.15 },
  });
  mapLibreMap.addLayer({
    id: "admin-boundary-line",
    type: "line",
    source: "admin-boundary",
    paint: { "line-color": "#00d4ff", "line-width": 2.5, "line-opacity": 0.9 },
  });

  if (bounds && bounds.length === 4) {
    mapLibreMap.fitBounds(
      [[bounds[0], bounds[1]], [bounds[2], bounds[3]]],
      { padding: 50, duration: 1500 }
    );
  }
}

const addPinToMap = (loc: { label: string, lat: number, lng: number }) => {
  if (!mapLibreMap) return;
  const maplibregl = (window as any).maplibregl;
  const popupContent = document.createElement("div");
  popupContent.style.color = "#fff";
  popupContent.style.padding = "5px";
  popupContent.innerHTML = `
    <div style="font-weight:bold;margin-bottom:5px;color:#fff">${loc.label}</div>
    <div style="font-size:10px;color:rgba(255,255,255,0.5)">${loc.lat.toFixed(4)}, ${loc.lng.toFixed(4)}</div>
    <div style="display:flex;gap:5px;margin-top:8px">
      <button class="btn-rename-pin" style="background:#00d4ff;color:#fff;border:none;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:10px">SỬA TÊN</button>
      <button class="btn-delete-pin" style="background:#ef4444;color:#fff;border:none;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:10px">XÓA</button>
    </div>
  `;

  const marker = new maplibregl.Marker({ color: "#ff4400" })
    .setLngLat([loc.lng, loc.lat])
    .setPopup(new maplibregl.Popup({ offset: 25 }).setDOMContent(popupContent))
    .addTo(mapLibreMap);

  // Fly to pin when marker element is clicked
  marker.getElement().addEventListener("click", () => {
    mapLibreMap.flyTo({ center: [loc.lng, loc.lat], zoom: 16, duration: 1500 });
  });

  popupContent.querySelector(".btn-rename-pin")?.addEventListener("click", () => {
    // Open custom dialog to rename existing pin
    // We can fetch these values and trigger the custom prompt
    const openCustomPromptFn = (window as any).openCustomMapPrompt;
    if (openCustomPromptFn) {
      openCustomPromptFn(loc.lat, loc.lng, loc.label, true, marker);
    }
  });

  popupContent.querySelector(".btn-delete-pin")?.addEventListener("click", () => {
    marker.remove();
    if (socket) {
      socket.send({ type: "delete_pin", lat: loc.lat, lng: loc.lng });
    }
  });

  pinnedMarkers.push(marker);
};

async function loadMapLibreScripts(): Promise<void> {
  if ((window as any).maplibregl) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css";
    document.head.appendChild(link);

    const script = document.createElement("script");
    script.src = "https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load MapLibre GL script"));
    document.head.appendChild(script);
  });
}

async function initMap() {
  if (!mapLibreMap) {
    try {
      await loadMapLibreScripts();
    } catch (err) {
      console.error(err);
      showError("Không thể tải bản đồ MapLibre.");
      return;
    }

    const maplibregl = (window as any).maplibregl;
    if (!maplibregl) {
      console.error("MapLibre not loaded");
      return;
    }

    mapLibreMap = new maplibregl.Map({
      container: 'map-container',
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: [105.8542, 21.0285], // Hanoi [lng, lat]
      zoom: 13,
      pitch: 60, // Default 3D tilt
      antialias: true,
      attributionControl: false, // Tắt ô trắng attribution/logo mặc định của MapLibre
    });

    isMap3D = true;
    document.getElementById("btn-map-3d")?.classList.add("active");

    mapLibreMap.on('load', () => {
      // Add 3D buildings layer
      const style = mapLibreMap.getStyle();
      const layers = style.layers;
      let labelLayerId;
      if (layers) {
        for (let i = 0; i < layers.length; i++) {
          if (layers[i].type === 'symbol' && layers[i].layout['text-field']) {
            labelLayerId = layers[i].id;
            break;
          }
        }
      }

      const sourceName = style.sources.openmaptiles ? 'openmaptiles' :
        style.sources.carto ? 'carto' :
          Object.keys(style.sources)[0];

      mapLibreMap.addLayer(
        {
          'id': '3d-buildings',
          'source': sourceName,
          'source-layer': 'building',
          'type': 'fill-extrusion',
          'minzoom': 15,
          'paint': {
            'fill-extrusion-color': '#00d4ff',
            'fill-extrusion-height': ['get', 'render_height'],
            'fill-extrusion-base': ['get', 'render_min_height'],
            'fill-extrusion-opacity': 0.6
          }
        },
        labelLayerId
      );

      // Load existing pins from server and render cached pins if any
      if (socket) {
        socket.send({ type: "get_pins" });
      }
      if (cachedPins && cachedPins.length > 0) {
        // Clear default mock/old pins to avoid duplication
        pinnedMarkers.forEach(m => m.remove());
        pinnedMarkers = [];
        cachedPins.forEach(pin => addPinToMap(pin));
      }

      // Temp variables for custom prompt coordinate storage
      let pendingPinLat = 0;
      let pendingPinLng = 0;
      let isRenameMode = false;
      let renameMarkerRef: any = null;

      const promptModal = document.getElementById("map-prompt-modal")!;
      const promptInput = document.getElementById("map-prompt-input") as HTMLInputElement;
      const promptCancel = document.getElementById("btn-map-prompt-cancel")!;
      const promptSave = document.getElementById("btn-map-prompt-save")!;

      const openCustomPrompt = (lat: number, lng: number, defaultText: string, renameMode = false, marker: any = null) => {
        pendingPinLat = lat;
        pendingPinLng = lng;
        isRenameMode = renameMode;
        renameMarkerRef = marker;

        promptInput.value = defaultText;
        promptModal.classList.remove("hidden");
        // Focus to input field with delay to ensure virtual keyboard pops up smoothly
        setTimeout(() => promptInput.focus(), 150);
      };

      // Export functions so other button triggers can call them
      (window as any).openCustomMapPrompt = openCustomPrompt;

      const closeCustomPrompt = () => {
        promptModal.classList.add("hidden");
        promptInput.value = "";
        promptInput.blur();
      };

      promptCancel.addEventListener("click", (e) => {
        e.stopPropagation();
        closeCustomPrompt();
      });

      promptSave.addEventListener("click", (e) => {
        e.stopPropagation();
        const text = promptInput.value.trim();
        if (!text) return;

        if (isRenameMode && renameMarkerRef) {
          // Send rename to server
          if (socket) {
            socket.send({ type: "save_pin", label: text, lat: pendingPinLat, lng: pendingPinLng });
          }
        } else {
          const loc = { label: text, lat: pendingPinLat, lng: pendingPinLng };
          addPinToMap(loc);
          if (socket) {
            socket.send({ type: "save_pin", label: text, lat: pendingPinLat, lng: pendingPinLng });
          }
        }
        closeCustomPrompt();
      });

      // Allow clicking on map to add a pin
      mapLibreMap.on('click', (e: any) => {
        // Prevent click trigger if clicking a marker
        if (e.originalEvent && e.originalEvent.target && e.originalEvent.target.closest('.maplibregl-marker')) {
          return;
        }
        const defaultName = `Vị trí tại ${e.lngLat.lat.toFixed(4)}, ${e.lngLat.lng.toFixed(4)}`;
        openCustomPrompt(e.lngLat.lat, e.lngLat.lng, defaultName, false);
      });
    });

    mapLibreMap.on('move', () => {
      const center = mapLibreMap.getCenter();
      const latEl = document.getElementById("map-lat");
      const lngEl = document.getElementById("map-lng");
      if (latEl) latEl.textContent = center.lat.toFixed(4);
      if (lngEl) lngEl.textContent = center.lng.toFixed(4);
    });

    // Controls
    document.getElementById("btn-map-3d")?.addEventListener("click", () => {
      isMap3D = !isMap3D;
      document.getElementById("btn-map-3d")?.classList.toggle("active", isMap3D);
      mapLibreMap.easeTo({
        pitch: isMap3D ? 60 : 0,
        duration: 1000
      });
    });

    document.getElementById("btn-map-globe")?.addEventListener("click", () => {
      isMapGlobe = !isMapGlobe;
      console.log("[Map] Toggling globe mode:", isMapGlobe);
      const btn = document.getElementById("btn-map-globe");
      if (btn) btn.classList.toggle("active", isMapGlobe);

      if (mapLibreMap) {
        try {
          mapLibreMap.setProjection({
            type: isMapGlobe ? 'globe' : 'mercator'
          });
        } catch (err) {
          console.error("[Map] setProjection error:", err);
        }

        if (isMapGlobe) {
          // Khi bật globe, reset độ nghiêng để nhìn thấy toàn cảnh quả cầu và zoom out
          mapLibreMap.easeTo({ pitch: 0, zoom: 1.5, duration: 1500 });
        } else {
          // Khi tắt, phục hồi pitch theo trạng thái 3D và zoom lại gần
          mapLibreMap.easeTo({ pitch: isMap3D ? 60 : 0, zoom: 13, duration: 1500 });
        }
      }
    });

    // Search Logic
    const searchInput = document.getElementById("map-search-input") as HTMLInputElement;
    const searchBtn = document.getElementById("btn-map-search-go");

    const performSearch = async () => {
      const query = searchInput.value.trim();
      if (!query) return;

      try {
        const res = await fetchWithTimeout(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=1`);
        const data = await res.json();
        if (data && data.length > 0) {
          const { lat, lon, display_name } = data[0];
          const latitude = parseFloat(lat);
          const longitude = parseFloat(lon);

          mapLibreMap.flyTo({
            center: [longitude, latitude],
            zoom: 15,
            essential: true
          });

          if (mapMarker) mapMarker.remove();
          const maplibregl = (window as any).maplibregl;
          mapMarker = new maplibregl.Marker({ color: "#ffaa00" })
            .setLngLat([longitude, latitude])
            .addTo(mapLibreMap);

          new maplibregl.Popup({ offset: 25 })
            .setLngLat([longitude, latitude])
            .setHTML(`<div style="color:#000;padding:5px;font-size:12px">${display_name}</div>`)
            .addTo(mapLibreMap);
        } else {
          showError("Không tìm thấy địa điểm này, thưa Ngài.");
        }
      } catch (e) {
        console.error("Search failed:", e);
        showError("Lỗi khi tìm kiếm địa điểm.");
      }
    };

    searchBtn?.addEventListener("click", performSearch);
    searchInput?.addEventListener("keypress", (e) => {
      if (e.key === "Enter") performSearch();
    });

    document.getElementById("btn-map-full")?.addEventListener("click", () => {
      toggleMapFullScreen();
    });

    // Locate Me
    document.getElementById("btn-map-locate")?.addEventListener("click", () => {
      if (!mapLibreMap) return;
      if ("geolocation" in navigator) {
        navigator.geolocation.getCurrentPosition((position) => {
          const { latitude, longitude } = position.coords;
          mapLibreMap.flyTo({ center: [longitude, latitude], zoom: 16, duration: 2000 });
        });
      }
    });

    // Saved Locations Cycling
    let currentSavedIndex = 0;
    document.getElementById("btn-map-saved")?.addEventListener("click", () => {
      if (!mapLibreMap || pinnedMarkers.length === 0) return;

      const marker = pinnedMarkers[currentSavedIndex];
      const lngLat = marker.getLngLat();

      mapLibreMap.flyTo({ center: [lngLat.lng, lngLat.lat], zoom: 16, duration: 1500 });
      if (!marker.getPopup().isOpen()) {
        marker.togglePopup();
      }

      currentSavedIndex = (currentSavedIndex + 1) % pinnedMarkers.length;
    });


    document.getElementById("btn-map-pin")?.addEventListener("click", () => {
      if (!mapLibreMap) return;
      const center = mapLibreMap.getCenter();

      const openCustomPromptFn = (window as any).openCustomMapPrompt;
      if (openCustomPromptFn) {
        openCustomPromptFn(center.lat, center.lng, `Vị trí ${new Date().toLocaleTimeString()}`, false);
      }
    });

    // Migration: If there are pins in localStorage, sync them to server
    const legacyPins = JSON.parse(localStorage.getItem("jarvis_pinned_locations") || "[]");
    if (legacyPins.length > 0 && socket) {
      console.log(`[Map] Migrating ${legacyPins.length} pins from localStorage to server...`);
      legacyPins.forEach((lp: any) => {
        socket.send({ type: "save_pin", label: lp.label, lat: lp.lat, lng: lp.lng });
      });
      localStorage.removeItem("jarvis_pinned_locations");
    }

    // Request current pins from server
    if (socket) {
      socket.send({ type: "get_pins" });
    }

    // Initial pins are loaded via WebSocket 'pins' message or from cache
    if (cachedPins.length > 0) {
      cachedPins.forEach((loc: any) => addPinToMap(loc));
    }

    // Get location
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition((position) => {
        const { latitude, longitude } = position.coords;
        mapLibreMap.flyTo({ center: [longitude, latitude], zoom: 15 });

        if (mapMarker) mapMarker.remove();
        mapMarker = new maplibregl.Marker({ color: "#00d4ff" })
          .setLngLat([longitude, latitude])
          .addTo(mapLibreMap);

        socket.send({ type: "geolocation", lat: latitude, lng: longitude });
      });
    }
  } else {
    setTimeout(() => mapLibreMap.resize(), 100);
  }
}

btnMap.addEventListener("click", () => {
  menuDropdown.style.display = "none";
  toggleMap();
});

btnCloseMap.addEventListener("click", () => {
  toggleMap(false);
});

// Listen for map update commands from WebSocket
socket.onMessage((msg: any) => {
  if (msg.type === "map_route") {
    toggleMap(true);
    setTimeout(() => {
      addRouteToMap([msg.from_lng, msg.from_lat], [msg.to_lng, msg.to_lat]);
    }, 500);
  } else if (msg.type === "map_pois") {
    toggleMap(true);
    setTimeout(() => {
      addPOIMarkers(msg.pois);
    }, 500);
  } else if (msg.type === "map_admin_boundary") {
    toggleMap(true);
    setTimeout(() => {
      addAdminBoundaryToMap(msg.geojson, msg.bounds);
    }, 500);
  } else if (msg.type === "pins") {
    console.log("[Map] Received pins from server:", msg.pins);
    cachedPins = Array.isArray(msg.pins) ? msg.pins : [];

    if (mapLibreMap) {
      // Clear existing pinned markers
      pinnedMarkers.forEach(m => m.remove());
      pinnedMarkers = [];
      // Add new pins
      cachedPins.forEach((loc: any) => addPinToMap(loc));

      // Automatically fly to the most recent pin on initial load if we just opened
      if (cachedPins.length > 0 && !pinnedMarkers.length) {
        const mostRecent = cachedPins[0];
        mapLibreMap.flyTo({
          center: [mostRecent.lng, mostRecent.lat],
          zoom: 15,
          duration: 2000
        });
      }
    }
  }
});

// ---------------------------------------------------------------------------
// Media Player
// ---------------------------------------------------------------------------

const mediaPlayer = document.getElementById("media-player")!;
const mediaPlayerInner = document.getElementById("media-player-inner")!;

let closeMediaPlayer = function () {
  mediaPlayer.classList.add("hidden");
  mediaPlayerInner.innerHTML = "";
  orb.resume();
  socket.send({ type: "media_state", active: false });
  // Khôi phục trạng thái nếu không còn phát audio
  if (!audioPlayer.isPlaying()) {
    transition("idle");
  }
}

// Settings phủ toàn màn hình: tạm dừng orb như map full-screen. Khi đóng chỉ chạy
// lại nếu không còn lớp toàn màn hình nào khác (map full-screen, trình phát media).
window.addEventListener("jarvis:overlay", (event) => {
  const { open } = (event as CustomEvent<{ open: boolean }>).detail;
  if (open) {
    orb.pause();
    return;
  }
  const mapFullScreen = isMapFullScreen && !mapPanel.classList.contains("hidden");
  const mediaOpen = !mediaPlayer.classList.contains("hidden");
  if (!mapFullScreen && !mediaOpen) orb.resume();
});

function openMediaPlayer(title: string, embedHtml: string) {
  orb.pause();
  socket.send({ type: "media_state", active: true });
  // Server chỉ chặn TTS mới; audio đã xếp lịch trong trình duyệt phải dừng ngay, không đọc chồng lên media.
  audioPlayer.stop();
  audioChunkBuffer = null;

  // Phát hiện luồng phát .m3u8 (IPTV)
  const isM3u8 = embedHtml.includes(".m3u8") || embedHtml.startsWith("http") && !embedHtml.includes("<iframe") && !embedHtml.includes("<video");

  if (isM3u8) {
    mediaPlayerInner.innerHTML = `
      <div style="position:absolute;top:10px;left:12px;font-size:9px;letter-spacing:2px;color:rgba(0,212,255,0.5);z-index:5;text-transform:uppercase">${title || "NOW PLAYING IPTV"}</div>
      <div class="media-player-close" id="btn-close-media-player">&#10005;</div>
      <video id="iptv-video" controls autoplay playsinline style="width:100%;height:100%;background:#000;display:block;object-fit:contain;"></video>
    `;

    const video = document.getElementById("iptv-video") as HTMLVideoElement;
    const Hls = (window as any).Hls;

    if (Hls && Hls.isSupported()) {
      const hls = new Hls();
      hls.loadSource(embedHtml);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(e => console.log("Auto play blocked:", e));
      });

      // Hủy stream khi đóng player
      const originalClose = closeMediaPlayer;
      closeMediaPlayer = () => {
        try {
          hls.destroy();
        } catch (e) { }
        closeMediaPlayer = originalClose;
        closeMediaPlayer();
      };
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      // Hỗ trợ HLS native trên Safari/iOS
      video.src = embedHtml;
      video.addEventListener("loadedmetadata", () => {
        video.play().catch(e => console.log("Auto play blocked:", e));
      });
    } else {
      showError("Trình duyệt của ngài không hỗ trợ phát luồng HLS.");
    }
  } else {
    // Luồng Youtube/Phim thông thường dạng Iframe/HTML5 video cũ
    mediaPlayerInner.innerHTML = `
      <div style="position:absolute;top:10px;left:12px;font-size:9px;letter-spacing:2px;color:rgba(0,212,255,0.5);z-index:5;text-transform:uppercase">${title || "NOW PLAYING"}</div>
      <div class="media-player-close" id="btn-close-media-player">&#10005;</div>
      ${embedHtml}
    `;
  }

  mediaPlayer.classList.remove("hidden");
  document.getElementById("btn-close-media-player")?.addEventListener("click", closeMediaPlayer);
}

// Đóng trình phát khi bấm nút Escape
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!mediaPlayer.classList.contains("hidden")) {
      closeMediaPlayer();
    }
  }
});

