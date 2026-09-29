# JARVIS

[Tiếng Việt](README.md) | **English**

**Just A Rather Very Intelligent System** — a Vietnamese-speaking voice AI assistant that runs locally on Windows.
**Version:** see the [`VERSION`](VERSION) file (single source of truth).

> *"Thưa ngài, tôi có thể giúp gì cho ngài?"* — *"How may I help you, sir?"*

JARVIS is a personal AI assistant that runs entirely on a Windows machine, inspired by JARVIS from Iron Man. It can:
- hold real-time spoken conversations in Vietnamese;
- control applications on the machine;
- look up data on the web;
- answer questions over documents (RAG);
- learn from conversations;
- show a 3D HUD that reacts to audio.

> **Note:** JARVIS is built for Vietnamese. Prompts, voice recognition (`vi-VN`), TTS voices and most command keywords are Vietnamese. Example commands below keep the original Vietnamese with an English gloss.

---

## 📑 Table of Contents

1. [Key features](#-key-features)
2. [How a conversation turn works](#-how-a-conversation-turn-works)
3. [Prompts in one place](#-prompts-in-one-place)
4. [Offers, "yes" and anti-fabrication](#-offers-yes-and-anti-fabrication)
5. [18 task agents](#-18-task-agents)
6. [Self-learning, evolution, Dream, self-healing](#-self-learning-evolution-dream-self-healing)
7. [Memory, Memory Center and Obsidian wiki](#️-memory-memory-center-and-obsidian-wiki)
8. [Frontend](#-frontend)
9. [Extending: commands, skills, hooks, MCP, Telegram](#-extending-commands-skills-hooks-mcp-telegram)
10. [System architecture](#️-system-architecture)
11. [Installation and configuration](#-installation-and-configuration)
12. [API](#-api)
13. [Directory structure](#-directory-structure)
14. [Testing and measurement](#-testing-and-measurement)
15. [Changelog](#-changelog)

---

## 🌟 Key Features

| Feature | Description |
|---------|-------------|
| **Local LLM** | Gemma 4 E4B-it QAT (current profile) or Qwen3.5-9B, served by llama.cpp at `http://localhost:8080/v1`; handles both text and images |
| **Local embeddings** | `nomic-embed-text-v1.5-q8_0` at `http://localhost:8081/v1`, used for RAG and semantic memory |
| **Vietnamese voice** | Speech recognition via the Web Speech API (`vi-VN`) with recognition-error correction. Speech output via Edge-TTS (`vi-VN-NamMinhNeural`) or VieNeu streaming (port 8082); only one may be enabled |
| **Two-tier routing** | The gate only decides **chat or work**, without knowing which agents exist. The orchestrator picks agents via native tool calling and can chain several agents |
| **Controlled offers** | While you are just chatting, Jarvis offers actions it can take using `<ask_user>`/`<action_run>` tags. When you reply "yes" (`ừ`), code runs exactly the offered tool — the LLM does not guess again |
| **Centralised prompts** | All prompt text lives in `prompt/*.md`; the code that assembles prompts lives in `engine/prompts/` |
| **Anti-fabrication** | Every chat turn carries a `<tool_status>` directive stating that no tool ran this turn, so chat cannot claim it "checked" something or report system state |
| **Self-reflective learning** | Each learning pass has a proposal step and a critique step, then code enforces hard checks. The latest lesson can be undone precisely (`retract`). Successful workflows are replayed when a command matches verbatim |
| **HyperRAG** | Dense vectors + BM25 + Reciprocal Rank Fusion for local document retrieval. Watches the `data/documents/` folder |
| **Memory & Obsidian** | SQLite + FTS5 (`data/jarvis.db`) is the source of truth. The Obsidian vault (`data/wiki/`) is a one-way mirror. The Memory Center in the WebUI is the only place to edit |
| **Dream Cycle** | Runs during idle night hours to summarise and clean up conversations, agent results and old wiki pages. Always backs up before merging |
| **Self-Healing** | Scans logs every 60 seconds, classifies errors and writes them to `Errors.md`. Only asks Goose to fix code after you approve |
| **Security** | Prompt-injection guardrails, IP firewall + Origin check (against CSRF / WebSocket hijacking) for REST and WebSocket, connection monitoring |

---

## 🔀 How a Conversation Turn Works

`engine/router/decide.py` checks the steps below in order and stops at the first match:

| # | Step | When | Result |
|---|------|------|--------|
| 0 | `@plans` | Message starts with `@plans <goal>`, e.g. `@plans hôm nay không biết ăn gì` ("no idea what to eat today") | Goal mode ([engine/plans](engine/plans)): plan lookups → call read-only agents (search/web/history) → re-plan if needed → one conclusion. Chat **never** offers this mode on its own |
| 0b | `@rag` | Message starts with `@rag` | Long-term document store ([engine/rag](engine/rag)), see "Document store (`@rag`)". Runs before `@mention`, so `@rag` no longer falls into the file-only RAG agent |
| 1 | `@mention` | Message starts with `@desktop`, `@mail`… (directory in `prompt/tools.md`) | Calls that agent directly |
| 2 | Reply to an offer | Jarvis asked with `<ask_user>` last turn, and you now answer "ừ" (yes), "đồng ý" (agree), "không" (no)… | Code runs exactly the tool in `<action_run>`, bypassing the LLM |
| 3 | Voice control | Volume, shutdown commands… | `win_control` agent |
| 4 | Routing complaint | "sai rồi, tôi chỉ hỏi thôi" ("wrong, I was only asking") | Removes the workflow that just ran by mistake and records a `routing_correction` |
| 5 | Workflow replay | Message **matches verbatim** a command that previously succeeded | Runs the stored tool chain directly |
| 6 | Gate (LLM, `temperature 0`) | Everything else | `general`, `general_knowledge`, `orchestrator`, or `attachment_clarify` when a file is attached |

- **orchestrator**: the classifier picks agents. For commands embedded in chat, the classifier may shorten the sentence (e.g. "…bạn mở giúp tôi được không?" → "mở Notepad", i.e. "…could you open it for me?" → "open Notepad"), but only if the shortened sentence **only removes words** and adds none. After an agent finishes, `next_tasks` decides whether to call another agent. Multiple results are merged into one answer by the `synthesizer`.
- **plan** (`@plans`): at most 3 rounds × 3 steps (5 in total), 60 seconds per step; the model only chooses targets and writes lookup queries (schema-validated JSON) and never holds tools; a round with no successful step stops the run. Web lookups go through the `web_research` tool (Google News RSS, then reads 3 articles), and each page is checked for injected instructions. Preferences in `Preferences.md` are only visible to the conclusion step and are never sent out in lookup queries.
- **general / general_knowledge**: the chat branch assembles 5 message blocks (see next section). If an agent declines, the turn also falls back to chat with a "could not be done" directive.
- **Attachments**: the picker only offers agents that can read the format (`attachment_agents_for`, built from `rag_tool` + `image_engine` + Office extensions): pdf/txt/md/csv/json/html → RAG; docx/xlsx/pptx → RAG or OfficeCLI; jpg/png/webp/bmp → Upscayl. Other formats: Jarvis says it "can't handle this yet". If a file is attached but the classifier chose an agent that doesn't use files → it asks again with the picker (except for `@mention`).
- **Archives** (`.zip .rar .7z .tar .gz .tgz .bz2 .xz .zst`, [engine/router/archive.py](engine/router/archive.py)): handled **before the gate** with Windows' built-in `bsdtar` (no extra libraries). **Exactly 1** usable file inside → extract only that file and treat it as if sent directly; **several files** → stop, list the names and ask for them one at a time; **none** → say so clearly. Blocked: > 200 entries, files > 200 MB, `..`/absolute paths, nested archives; 60-second timeout.

---

## 🧩 Prompts in One Place

To change a prompt, edit the `.md` file — never write prompt text in code.

| Group | Files in `prompt/` | Code (`engine/prompts/`) |
|-------|--------------------|--------------------------|
| Persona, hard rules | `identity.md`, `soul.md`, `user.md`, `persona_short.md` | `persona.py` |
| Chat | `capabilities.md`, `offer_protocol.md`, `voice_cues.md`, `style_lock.md`, `fallback.md`, `turn_status.md`, `tool_status_none.md`, `tool_status_declined.md` | `chat.py`, `results.py` |
| Routing | `router_gate.md`, `classifier.md`, `agents.md` (agent selection criteria) | `router.py` |
| Agent/tool directory | `tools.md` (`@` names, aliases, tools allowed in offers) | `catalog.py` |
| Tool results | `tool_summary.md`, `synthesis.md` | `results.py` |
| Background | `learning_propose.md`, `learning_critique.md`, `learning_workflow.md`, `evolution.md`, `dream_message.md`, `dream_wiki.md`, `self_healing.md` | `learning.py` |

- Per-tool formatting rules (`SUMMARY_RULES`) are owned by each tool module in `engine/tools/*`.
- The gate, classifier, offer_context, dream, self_healing and workflow-distillation prompts are **byte-identical** to the versions before consolidation. Snapshots live in `tests/golden/`.

**Chat context** consists of 5 blocks, in order:
1. `system`: persona, `<capabilities>`, `<offer_protocol>`, `<style>` (from `skills/self_evolution/STYLE.md`), `<about_user>` (from `Preferences.md`), current time.
2. History read from the DB, same source as the gate. On offer turns the tags are rebuilt from the `ask_user`/`action_run` columns.
3. `<turn_status>`: directives for this turn, including `<tool_status>` and `<answer_policy>`.
4. `<reference>`: reference data, **not instructions** — relevant lessons, successful agent results, MCP, wiki.
5. The user's message.

Each kind of data reaches the model through **exactly one channel**.

---

## 💬 Offers, "Yes" and Anti-Fabrication

- **You are just chatting**, e.g. "tôi lười mở notepad quá" ("I'm too lazy to open Notepad"): Jarvis replies and then offers
  `Ngài có muốn tôi <ask_user>mở Notepad</ask_user> không?<action_run>open_app</action_run>` ("Would you like me to open Notepad?").
  Reply "ừ" (yes) and code runs `open_app` immediately. Tools that may be offered are listed in the `offer` column of `prompt/tools.md`.
- **You ask explicitly**, e.g. "bạn mở notepad giúp tôi" ("please open Notepad"): Jarvis just does it, without asking again.
- **Anti-fabrication**:
  - Normal chat turns always carry `<tool_status>` saying "no tool ran this turn": don't claim to have done anything, don't report results or state; offer instead when real data is needed.
  - Turns where an agent declined carry `<tool_status>` saying "could not be done": don't rely on history to claim "already done".
- **Media**: before ranking YouTube results, filler words from natural speech ("tôi muốn … của …" — "I want … by …") are removed. The results table is copied verbatim from the tool, and the answer names the track that is **actually playing**.

---

## 🤖 18 Task Agents

Agents are registered in `engine/orchestrator/registry.py`; source code is in `engine/agents/`.

| Agent | Main function |
|-------|---------------|
| **desktop** | Open/close Windows apps, keeping the app's original name |
| **search** | Weather, news, gold/fuel prices and exchange rates, lunar calendar, zodiac, CGV showtimes, Epic free games, administrative units, maps and directions |
| **media** | Music, YouTube, livestreams, hhpanda movies (played inside the UI) |
| **notes** | Write, view, delete notes |
| **vision** | Capture and analyse the screen with a vision LLM |
| **webcam** | Capture and analyse a webcam frame |
| **office** | Create/edit attached Word, Excel, PowerPoint files (`officecli` skill) |
| **rag** | Read, summarise and answer questions over attached files or indexed documents |
| **legal** | Look up Vietnamese legal documents |
| **vietlott** | Mega 6/45 and Power 6/55 results, probabilities, backtests (no predictions) |
| **security** | Check network security, ports, firewall |
| **email** | Last 10 emails and the next 7 days of appointments in Outlook |
| **history** | Review conversation history |
| **image** | Upscale images with Upscayl |
| **project** | Inspect a code project, scan for syntax errors |
| **goose** | Open the Goose UI for you to drive yourself |
| **win_control** | Control background Windows apps via cua-driver (open apps, click, type), change window state |
| **dream** | Run a Dream cycle immediately |

### ➕ Adding a new agent

Chat, the WebUI (`@` suggestions), Telegram `/agents` and the classifier all **read** the agent list from the files below — no prompt or chat code changes needed. Just complete every step:

| # | File | What to do |
|---|------|------------|
| 1 | `engine/agents/agent_<name>.py` | Write the agent: a `run_<name>_agent` function |
| 2 | `engine/orchestrator/registry.py` | Add `"<name>": {"module": ..., "runner": ...}` to `AGENT_REGISTRY` |
| 3 | `prompt/tools.md` | Add a `## @<name>` section: an `alias:` line, a one-line description, then one line per tool `- tool | label | offer` (or `-` if chat may not offer that tool). Chat will automatically see **"Agent <Name>"** |
| 4 | `prompt/agents.md` | Add `- <name>: <when to pick this agent>`. This is the tool description the classifier sees |
| 5 | `commands/<tool>.md` | Each of the agent's tools needs a command file |
| 6 | Tests | Update `EXPECTED_AGENT_CRITERIA` in `tests/test_prompts_catalog.py` (and the `offer` tool list if you added any), then re-snapshot the classifier golden with the command below |
| 7 | Re-run | `rtk python -m pytest tests -q --ignore=tests/live`, then **restart JARVIS** (`tools.md` is read once and cached in memory) |

```bash
rtk python -c "import json; from engine.orchestrator.classifier import _build_tools; open('tests/golden/classifier_tools.json','w',encoding='utf-8').write(json.dumps(_build_tools(), ensure_ascii=False, indent=1))"
```

If a step is missing, `tests/test_prompts_catalog.py` fails. It requires the agent sets in `tools.md`, `agents.md` and `AGENT_REGISTRY` to be identical, and every tool to have a command file owned by the right agent — so an agent can never run without chat and the classifier knowing about it.

---

## 🧬 Self-Learning, Evolution, Dream, Self-Healing

All of these run in the background when the system is idle and never slow down a conversation turn. If you keep chatting, the running background task yields and retries later.

### 📖 Self-reflective learning ([learning.py](engine/core/learning.py))

1. **Propose** (`learning_propose.md`): the model reads the last 3–5 turns from the DB and successful agent results, then proposes at most 2 items. Each item has a `kind`: `user_fact`, `preference`, `behaviour_lesson` or `routing_note`.
2. **Critique** (`learning_critique.md`): the model compares each proposal with the closest existing item and decides `skip`, `merge`, `replace` or `new`.
3. **Code gatekeeping**:
   - Evidence must match the conversation verbatim; for `user_fact`/`preference` it must come from your own words.
   - Transient states ("lazy", "tired") are not learned.
   - Behaviour rules may not talk about asking, permissions, tools, agents or tags.
   - `merge`/`replace` may only touch the exact existing item shown to the model.
4. **Retracting a lesson**: if you deny exactly what was just learned, the next learning pass proposes `retract`. Code can only undo items written by the previous pass: new items are deleted, merged items are restored to their old content.
5. **Workflows**: successful tool chains are stored in `validated_workflows` and replayed when a command matches verbatim (case-insensitive). By design there is no fuzzy matching and no diacritic stripping, since stripping diacritics collides words such as `bật`/`bắt` (turn on / catch) and `tắt`/`tát` (turn off / slap).
6. `routing_note` is only written as a **proposal** to `data/wiki/System/Evolution.md` for human review. It is never applied automatically.

### 🧬 Evolution ([evolution.py](engine/core/evolution.py))
- Only writes **tone** rules (forms of address, emoji, length, humour) to `skills/self_evolution/STYLE.md`. New rules may not touch the persona, `<soul_rules>` or `<offer_protocol>`.
- Every update bumps the version and appends a short changelog entry to `Evolution.md`.

### 💤 Dream Cycle ([dream.py](engine/core/dream.py))
- **When**: within the quiet window (default 02:00–05:00), every 24 hours, when the system is idle. Can be triggered manually with `@dream`, natural language, or `POST /api/dream/run`.
- **What**: summarises old conversations (older than 14 days), prunes `agent_outcomes`, merges monthly journals, compacts `topics/*.md`, rotates `Errors.md` and `Evolution.md`.
- **Safety**: always backs up to `data/dream_archive/` or `data/wiki/.trash/dream/` before merging. If the LLM fails to respond, Dream leaves the original data untouched and retries next cycle.

### 🛡️ Self-Healing ([self_healing.py](engine/core/self_healing.py))
- Scans logs every 60 seconds when idle. The LLM classifies errors (`CODE_BUG`, `TRANSIENT`, `CONFIG`, `DEPENDENCY`, `OTHER`) and writes an entry to `data/wiki/System/Errors.md`.
- For code bugs, Jarvis **asks for your approval** in the WebUI session before asking Goose CLI to fix exactly one file. No session to approve in → no fix.

---

## 🗂️ Memory, Memory Center and Obsidian Wiki

- **Source of truth**: `data/jarvis.db` (SQLite + FTS5), with tables `messages` (including `ask_user`/`action_run` columns), `memories`, `learnings`, `agent_outcomes`, `validated_workflows`.
- **Memory Center** (WebUI, `/api/memory-control/*`, `/api/learnings/*`…) is the **only place to edit**. Every write path, including automatic learning and cleanup scripts, goes through the same Memory Center functions.
- **Obsidian vault** `data/wiki/` is a **one-way** mirror of the DB:
  - `System/Preferences.md`, `System/Learning.md`, `System/Workflows/*.md`;
  - `System/Evolution.md`, `System/Errors.md`, `System/Dream.md`;
  - daily journals `daily/MM-YYYY/YYYY-MM-DD.md`.

  Jarvis never reads data back from Obsidian.
- **Dual lookup**: `history_engine.py` and `wiki_retrieval.py` search SQLite FTS5 and the Markdown files in parallel.
- **Notes** (`note_engine.py`): Markdown with YAML frontmatter, openable and editable in Obsidian.

---

## 🎨 Frontend

Built with **Vite + TypeScript + Three.js**, Dark-Tech Glassmorphism style. Source in `frontend/src/`:

| File | Role |
|------|------|
| `main.ts` | State machine, Command Bar (Ctrl+K; `/` suggests commands from `commands/`, `@` suggests agents), interactive cards, media player, MapLibre map |
| `orb.ts` | Audio-reactive Three.js particle orb |
| `voice.ts` | Web Speech API, microphone, audio playback, instant TTS interruption |
| `ws.ts` | WebSocket client with auto-reconnect |
| `dashboard-hud.ts` | Telemetry: RAM, CPU, GPU VRAM, NPU, running agents, tokens |
| `icons.ts` | Morphing icons (morphicons + lucide) for buttons, flow steps, tracker; `runAction` for buttons with spinner → ✓/✗ |
| `settings/` | Full-screen settings dashboard (see below) |
| `style.css` | HUD styling |

**Settings dashboard** (`frontend/src/settings/`): opens full-screen and pauses the orb; 15-page sidebar that becomes a drawer on mobile.

| File | Role |
|------|------|
| `index.ts` | Shell: open/close, sidebar, page switching, first-run setup, data loading, save/test buttons |
| `pages.ts` | Page HTML: Overview, Connections & API, Voice, User, System, Memory, Agents, Hooks, Skills, Prompts (editable and savable), Commands, Plugins, MCP Connect, Graphfy, About (README) |
| `memory.ts` | Memory Center: view, edit, delete with relationship checks, multi-select delete |
| `graphfy.ts` | Structure map **generated from code** via `GET /api/graphfy` (`engine/UIUX/graphfy.py` scans imports with `ast`): one block per `engine/` package, with `core/` and `server/` split per file; purple edges = LLM call sites; the LLM block is drawn as a **circuit brain** (half brain · half circuit with running pulses, 90% width), with edges from below plugging into its signal pins. Lanes: Input · Turn processing · LLM (centre axis) · Response / Memory · Document ingestion · Background · Support (dimmed) · Other. New modules appear in "Other" until assigned in `LANES`. Light pulses animate flow on every edge; hover filters a block's edges and shows its files; drag and drop, layout saved as `jarvis.graphfy.positions.v4` |
| `api.ts`, `types.ts`, `styles.css` | API calls (20s timeout, shows the backend's actual error), types, styling |

Heavy lists (agents, hooks, skills, prompts, commands, plugins) come from `/api/settings/catalog` when the relevant page opens, not from `/api/settings/status` (which is polled every 5 seconds).

---

## 🔌 Extending: Commands, Skills, Hooks, MCP, Telegram

- **33 Markdown commands** in `commands/` (`open_app`, `check_mail`, `search_media`, `rag_tool`, `win_control`, `dream`…), hot-reloaded.
- **3 skills** in `skills/`: `legal`, `officecli`, `self_evolution`.
- **Hooks & plugins**: events `on_startup`, `on_shutdown`, `ON_MESSAGE_RECEIVE`, `ON_RESPONSE_GENERATE`; dynamic loading of `.py`/`.ts` plugins.
- **Self-installing extensions** (`install_extension`): hot-load new plugins/skills/hooks from a URL or code, no restart needed.
- **MCP** (`config/mcp_config.json`): `wikipedia-mcp`, `gitnexus`, `context7`, `headroom`, `ScraplingServer`, `codebase-memory-mcp`.
- **Command Bar**: `/command_name <args>` runs a command from `commands/` (type `/command_name` with no args and JARVIS asks for each argument); `@agent message` calls an agent directly (router step 1). The Commands and Agents pages in Settings document this exact syntax.
- **Telegram bot**: remote control with Chat ID authentication. The `/agents` command reads the directory from `prompt/tools.md`.

---

## 🏗️ System Architecture

```
                     Chrome / Web Client (https://localhost:8340)
┌──────────────────────────────────────────────────────────────────────────┐
│ voice.ts (STT/TTS) · orb.ts (Three.js) · main.ts (Cards, Media, Map)       │
│ dashboard-hud.ts (Telemetry) · settings/ (Dashboard, Memory Center)      │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ WebSocket /ws/voice
                                ▼
┌──────────────────────── server.py (FastAPI) ─────────────────────────────┐
│ WebSocket · UIEngine REST · Security Firewall · Self-Healing watcher     │
└───────────────────────────────┬──────────────────────────────────────────┘
                                ▼
┌──────────── engine/router ────────────┐   ┌──── engine/prompts ──────────┐
│ decide: @mention → "yes" → voice →    │◄──│ prompt/*.md → persona, chat, │
│ complaint → replay → gate             │   │ router, results, learning,   │
└──────┬─────────────────────┬──────────┘   │ catalog                      │
       │ orchestrator        │ general      └──────────────────────────────┘
       ▼                     ▼
┌──── engine/orchestrator ───┐  ┌── chat (5 blocks) ┐
│ classifier → agents →      │  │ system · history  │
│ next_tasks → synthesizer   │  │ turn_status ·     │
└──────┬─────────────────────┘  │ reference · user  │
       ▼                        └───────────────────┘
┌── engine/agents (18) ──┐  ┌── engine/tools ───────────────┐  ┌── engine/core ─────────────┐
│ desktop, search, media │─►│ desktop automation, scrapling,│  │ memory, learning, evolution│
│ office, rag, ...       │  │ media, office, weather, ...   │  │ dream, self_healing, RAG   │
└────────────────────────┘  └───────────────────────────────┘  └────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ llama.cpp :8080 (Gemma 4 / Qwen3.5) · llama.cpp :8081 (embeddings)       │
│ Stream TTS :8082 (VieNeu) · Edge-TTS · Redis :6379                       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Installation and Configuration

### Requirements
- Windows 10/11 64-bit, Python 3.11+, Node.js 18+, Google Chrome.
- llama.cpp server: LLM on `:8080`, embeddings on `:8081`.
- Redis on port 6379 (native Windows or WSL).
- `yt-dlp` on PATH (for YouTube search).

### Steps

```bash
git clone https://github.com/erikpuw/jarvis-windows.git
cd jarvis-windows
pip install -r requirements.txt
cd frontend && npm install && cd ..

# SSL certificate for HTTPS/WSS
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'

# Create .env from the template and fill it in (see the table below). If you forget, the server copies the template on startup.
cp .env.example .env           # PowerShell: Copy-Item .env.example .env
# Start llama.cpp (8080, 8081) and Redis (6379)

python server.py               # backend; also starts Stream TTS :8082 when using VieNeu
cd frontend && npm run dev     # frontend, in a separate terminal
# Open Chrome: https://localhost:8340
```

### `.env` configuration

The full list with comments is in [`.env.example`](.env.example). The most important variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_URL` | `http://localhost:8080/v1` | llama.cpp LLM endpoint |
| `LOCAL_API_KEY` | `sk-no-key-required` | API key for the local LLM |
| `LOCAL_MODEL` / `VISION_MODEL` | name of the running model | Text / vision model |
| `LOCAL_EMBED_URL` | `http://localhost:8081/v1` | Embeddings endpoint |
| `LOCAL_EMBED_MODEL` | `nomic-embed-text-v1.5-q8_0` | Embeddings model |
| `EDGE_TTS_ENABLED` / `VIENEU_TTS_ENABLED` | `true` / `false` | Pick the TTS engine; both may not be enabled |
| `TTS_LOCAL_MODEL` | `vi-VN-NamMinhNeural` | Edge-TTS voice |
| `USER_NAME` / `HONORIFIC` | `erikpuw` / `thưa ngài` | Personalisation (name / form of address, "sir") |
| `REDIS_URL` | `redis://localhost:6379` | Redis |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_CHAT_IDS` | optional | Telegram bot |
| `JARVIS_CORS_ORIGINS` | `localhost:5173`, `localhost:8340` | Comma-separated browser origins allowed to call the API/WebSocket. `*` is ignored. Pages served from the same host as the server (`https://<ip>:8340`) are always allowed |
| `RAG_WATCH_FOLDER` | `data/documents` | Folder watched by RAG |
| `DREAM_ENABLED` | `true` | Enable/disable Dream |
| `DREAM_RETENTION_DAYS` | `14` | Days data is kept as-is before Dream merges it |
| `DREAM_OUTCOME_RETENTION_DAYS` | `= DREAM_RETENTION_DAYS` | Days successful `agent_outcomes` are kept (failures are kept twice as long) |
| `DREAM_QUIET_HOUR_START` / `_END` | `2` / `5` | Window in which Dream may run automatically |
| `DREAM_INTERVAL_HOURS` | `24` | Minimum gap between two Dream runs |

**Chat-branch sampling** (Gemma, `engine/server/llm_server.py`): `temperature 0.4 / top_p 0.8 / top_k 40`, measured and kept as-is. The gate and classifier always use `temperature 0`.

### 📱 Remote access via Tailscale
1. Install Tailscale on the JARVIS machine and on your phone, signed in to **the same account**.
2. On the host: run `npm run dev -- --host` in `frontend/`, and set `JARVIS_CORS_ORIGINS=http://<PC-Tailscale-IP>:5173` in `.env` (don't use `*`: it is ignored, and the WebSocket rejects origins not on the list).
3. On the phone: open Safari or Chrome and go to `http://<PC-Tailscale-IP>:5173`.

No router port forwarding needed, and your IP is not exposed.

---

## 🌐 API

**WebSocket**: `/ws/voice` carries voice, streamed text and audio, interactive cards, `media_open`, map pins.

| Group | Endpoints |
|-------|-----------|
| Health | `GET /api/health`, `/api/health/detailed`, `/api/usage`, `/api/logs` |
| Settings | `/api/settings/status`, `/api/settings/catalog`, `/api/settings/keys` (accepts only `LOCAL_API_KEY`, `TTS_LOCAL_KEY`, `LOCAL_URL`, `TTS_LOCAL_MODEL`, `USER_NAME`, `HONORIFIC`), `/api/settings/preferences`, `/api/settings/test-llm`, `/api/settings/test-tts`, `/api/settings/reset-tokens`, `POST /api/prompts/save`, `/api/system/readme`, `POST /api/restart` |
| TTS/STT | `/api/tts/voices`, `/api/tts/voice`, `/api/tts/voices/clone`, `/api/tts-test`, `/api/stt` |
| Memory Center | `/api/memory-control/{summary,dependencies,update,delete}`, `/api/learnings/*`, `/api/memories/*`, `/api/notes/*`, `/api/workflows/*`, `/api/outcomes/list`, `/api/memory-registry/list` |
| Conversations | `/api/history`, `/api/conversations`, `/api/conversations/sessions`, `/api/conversations/session/{id}`, `/api/conversations/update`, `/api/conversations/delete` |
| Media | `/api/media/search`, `/api/media/resolve`, `/api/media/episodes`, `/api/media/local/{path}` |
| RAG & files | `/api/rag/status`, `DELETE /api/rag/document`, `/api/upload` |
| MCP | `/api/mcp/servers` (live status from the hub; secret values in `args` are redacted) |
| Other | `/api/command-bar/skills`, `/api/command-bar/context`, `/api/feedback`, `/api/feedback/stats`, `POST /api/dream/run`, `/api/agents/goose/launch` |

---

## 📂 Directory Structure

```
jarvis/
├── server.py              # FastAPI + WebSocket
├── prompt/                # TEXT of every prompt (*.md) + tools.md, agents.md directories
├── commands/              # 33 hot-reloaded Markdown commands
├── skills/                # legal, officecli, self_evolution (STYLE.md)
├── config/                # mcp_config.json
├── scripts/               # cleanup_learning_2026_09.py (dry-run by default, --apply to clean)
├── data/                  # jarvis.db, wiki/ (Obsidian), documents/, backups/, dream_archive/
├── docs/superpowers/      # specs/, plans/, reports/ (internal, not in the repo)
├── engine/
│   ├── router/            # decide, gate, replay, ask_user, fast_paths, dispatch, chat
│   ├── orchestrator/      # classifier, dispatcher, synthesizer, registry
│   ├── prompts/           # prompt assembly: persona, chat, router, results, learning, catalog
│   ├── agents/            # 18 agents
│   ├── tools/             # executable tools (media_search, desktop_automation, ...)
│   ├── core/              # memory, learning, evolution, dream, self_healing, RAG, guardrails
│   ├── server/            # llm_server, tts_manager, stream_tts, telegram_bot
│   ├── context/           # context management, token budget
│   ├── security/          # firewall, connection monitor
│   ├── UIUX/              # REST router, interactive cards
│   ├── main/              # FlowTracker, FlowAgents, user confirmation
│   └── chunking/          # AST chunker (Tree-sitter)
├── frontend/src/          # main.ts, orb.ts, voice.ts, ws.ts, icons.ts, dashboard-hud.ts, style.css
│   └── settings/          # settings dashboard: index, pages, memory, graphfy, api, styles
└── tests/                 # unit tests, golden/, live/probes/
```

---

## 🧪 Testing and Measurement

```bash
rtk python -m pytest tests -q --ignore=tests/live
```

- **Golden** (`tests/test_prompts_wired.py`): the gate, classifier, offer_context, dream, self_healing and workflow prompts must be byte-identical to `tests/golden/`. The test also checks that no prompt text remains in code and that modules import cleanly in any order.
- **Never touches real data**: learning tests and cleanup-script tests run against a temporary DB and wiki.
- **CI** (`.github/workflows/ci.yml`, runs on every push to `main` and every PR): `ruff check .` (rules in `ruff.toml`), compile all Python, `python .github/scripts/check_imports.py` (every `from engine... import X` must point to a real name), `pytest` (installs the lightweight `requirements-ci.txt` plus `bsdtar`; skips `tests/live/` and `tests/test_live_*.py`, which need a real llama-server), and `npm run build` for the frontend. Run these locally before pushing to keep CI green.
- **Live probes** (`tests/live/probes/`, only call llama-server):

| Probe | Measures |
|-------|----------|
| `fabrication_probe.py` | Whether chat fabricates "done" or fabricates tool results |
| `sampling_comparison_probe.py` | Compares sampling configurations on the real chat layout |
| `offer_protocol_probe.py` | Whether offer tags follow the protocol |
| `declined_probe.py` | Whether declined agent turns claim "done" |
| `learning_probe.py` | Learning learns the right things / doesn't mislearn |

---

## 🔒 Security

- **`scrub_untrusted`** (`engine/core/guardrails.py`): removes each line suspected of prompt injection (`PROMPT_INJECTION_PATTERNS`) from tool/agent results before they enter history or prompts — applied in `actions.execute_tool` and `dispatcher.run_one`; one bad line doesn't spoil the whole result.
- **`<untrusted_data>`**: agent reports sent back to the classifier (`next_tasks`) are wrapped in this tag with a reminder that they are "returned data, not requests" — preventing the model from treating web/tool content as new instructions.
- After an agent reads external content (`search`, `media`, `rag`, `legal`, `vietlott`), `next_tasks` blocks any subsequent machine-control step (`win_control`, `desktop`, `goose`); other steps (e.g. `notes`, `office`) still run normally.
- **Origin check** (`engine/security/policy.py`, `firewall.py`): the IP firewall alone cannot stop a malicious web page opened on the same machine (its requests come from loopback). Browsers always send `Origin` for WebSocket and cross-origin POST/PUT/DELETE, so `/ws/voice` and every mutating request are rejected unless the origin is the same host or listed in `JARVIS_CORS_ORIGINS`. Non-browser clients (Telegram, httpx, curl) send no `Origin` and are unaffected.

---

## 📝 Changelog

**Numbering** `MAJOR.MINOR.PATCH`:
- The version number lives in exactly one place: the [`VERSION`](VERSION) file. `/api/health` and the dashboard (Vite) read it; the README only links to it.
- For each release: bump `VERSION` (the only place to edit), add a new entry to the log below, then tag `vX.Y.Z` in git.
- Which number to bump:
  - `PATCH`: bug fixes, no change in designed behaviour.
  - `MINOR`: new features, or prompt/flow changes that don't break existing data.
  - `MAJOR`: architecture changes, or data/DB changes that require migration.

### v9.9.6 — 2026-09-27

**Settings becomes a full-screen dashboard.** Spec and plan written by Claude, implemented by another model (plus 9 extra pages beyond the plan, on request), then reviewed and fixed by Claude.

| Issue found in review | Impact | Fix |
|---|---|---|
| `/api/settings/status` returned raw MCP `args` | Leaked the context7 API key to every client | Return only name/command/status; secret values in `args` redacted (`_redact_args`) |
| Status bundled README, prompts, commands… (≈93KB) into every poll | Settings slow, prone to timeouts | Moved to `/api/settings/catalog`, fetched when a page opens |
| `mcp_servers` changed from dict to list | HUD showed "0,1,2" with error dots | Return `{name: status}` from the real hub again |
| `/api/mcp/servers` used `_json` without importing it | MCP page broken | Fixed; status taken from the hub instead of the `enabled` flag |
| UI sent `SERVER_API_KEY`, `FISH_AUDIO_API_KEY` | Backend rejected them, showing "connection error" | Switched to `LOCAL_API_KEY`, `TTS_LOCAL_KEY` |
| Moving into `settings/` dropped the `jarvis:overlay` event | Orb didn't pause | Event emitted again |
| Voice page hard-coded 4 Google voices and saved to the wrong API | Saved fake voices | Load `/api/tts/voices`, save via `/api/tts/voice`, wire up the clone button |
| CSS forced `display:flex` on the Memory grid, ALL-CAPS text, text < 12px | Broken layout, mismatched fonts | Grid fixed, one font family, 12px minimum; 42 dead rules removed |
| Command bar suggested `/help`, `/clear`, skills, `/plugin` | Every one returned "command not found" | Only suggest commands the backend can run |
| Collapsing the Settings sidebar: labels `display:none` + icons re-centred instantly | Text/icons jumped while the width shrank | Icons keep their position, labels fade (`opacity`), no wrapping |
| Dashboard read the version number from `.env` | Out of sync with `VERSION` | Vite reads the `VERSION` file |

**Mascot on the send button** (`frontend/src/mascot.ts`) — a pure TypeScript port of [nilbuild/page-mascot](https://github.com/nilbuild/page-mascot) (MIT), no React needed (the `page-mascot` npm package is unused and can be removed).
- **Position:** sits still right above `#cmd-send`, its body overlapping the command bar's top edge (sunk 20px) so it looks perched on the bar; the status line stays on the left. 56px (44px on mobile).
- **Hit area:** only the head receives clicks; clicks pass through the body so the send button still works.
- **Interaction:** the head follows the mouse (8 directions) and blinks occasionally; click to change expression (heart, sparkle, happy), 4 quick clicks = dizzy.
- **Follows JARVIS state** via the `jarvis:mascot` event (emitted in `transition()` and `showError()`): thinking looks up, working sparkles, speaking is happy, error/restart is dizzy, idle for 60 seconds falls asleep.
- **Characters:** sprites `frontend/public/mascots/<name>-directions.webp` and `<name>-reactions.webp` (3×3 grid, transparent background); switch characters with the `name` parameter of `mountMascot` in `main.ts`.
- **Static files:** `mount_frontend_dist` (`engine/UIUX/ui_engine.py`) serves `/` and every folder in `frontend/dist` (`assets/`, `mascots/`, …) — previously only `/assets`, so mascot images 404'd in the desktop app.
- **Tests:** `frontend/e2e/mascot.cjs` (position, not covering the send button, gaze direction, expressions, states, mobile) and `tests/test_frontend_static.py`.

**Redesigned step tracker (flow_tracker) and agent cards (flow_agents)** — one UI font at 12–12.5px for both (no monospace), status markers the same size.
- **Step tracker:** header = status icon + current step + a `6/7` pill counter + a thin progress bar; the list is a vertical timeline (green dot done · pulsing blue running · grey pending), no "1. 2. 3." numbering; text after "→" becomes dimmed secondary text, trailing "..." removed from labels.
- **Agent cards:** lucide icon in a rounded tile + name + current activity (no "Executing:" prefix). The backend still sends `"<emoji> Agent <Name>"` (Telegram still uses it); the frontend strips the emoji and picks the icon by name from `AGENT_ICON` (`frontend/src/icons.ts`). New agents in `engine/agents` not yet in the table still show, with a robot icon.
- **Test:** `frontend/e2e/flow-ui.cjs` (a fake WebSocket replays a run).

**HTC Sense–style flip clock** (`frontend/src/clock.ts`) — one tile per digit (`HH:MM`; the `:` is 2 round dots emitting a "radar ping" — a blue ring spreading from each dot alternately, 2-second cycle, static when reduced motion is on), frameless, just a horizontal cut line through the digits; centred at the top of the main screen, right below the button row.
- **Effect:** on change, the top half of the old digit folds down and the bottom half of the new digit drops in (2 × 0.3 seconds). Only digits that change flip (10:59 → 11:00 keeps the leading 1). With no background tile, the two static halves fade out/in with the flap so old and new digits never overlap. Disabled when reduced motion is on.
- **Layer:** `z-index: 1`, above the orb only; the HUD, chat, map and Settings all overlay it. `pointer-events: none`, so it never blocks clicks.
- **Font:** Oswald Light (300), bundled into the build via `@fontsource/oswald` (latin subset) — the desktop app shows the right font offline.
- **Test:** `frontend/e2e/clock.cjs` (fake time via `page.clock`: shows 10:59, flips to 11:00, cleans up flaps, position, layer, font, mobile).

Also: editing and saving prompts (`POST /api/prompts/save`, only overwrites existing `prompt/*.md`); Graphfy became a live execution-flow map. Tests: `tests/test_settings_status_api.py`, `frontend/e2e/settings-dashboard.cjs`.

### v9.9.5 — 2026-09-25

**Prompt consolidation and self-reflective learning.** Spec written by Claude, planned and implemented by another model, then reviewed and fixed by Claude. Results in real use: better context understanding, faster responses, fewer tokens, easier maintenance.

| Issue found in review | Impact | Fix |
|---|---|---|
| History from the DB kept only `role` and `content` | `<ask_user>` tags were never rebuilt | Also keep the `ask_user`/`action_run` columns, tested on a temporary DB |
| History dropped every duplicate user turn | Lost earlier "yes" turns, affecting the gate too | Only merge duplicates that are adjacent |
| `unlearn_last_learning` deleted the newest lesson whenever you complained about routing | Data loss | Replaced by a controlled `retract` |
| Prompts copied into `.md` but code still used hard-coded text | Editing the `.md` had no effect | Code wired to the `.md` files, verified by golden tests |
| `learning_workflow.md` had a different output schema from the real prompt | Would have broken workflow learning | Rewritten to match the running prompt |
| Learning tests wrote to the real `data/` | Left junk in `Evolution.md` | Tests run in a temp folder; cleanup script removes the junk |
| Sampling changed after measuring on the old layout | Re-measured 10 times per scenario; the new config was worse | Kept `0.4 / 0.8 / 40` |
| Cleanup script edited `STYLE.md` before backing up, and the other model ran `--apply` on its own | Backup was missing `skills/self_evolution/` | Back up before any change |

**Further fixes after real use:**
- **Media played the wrong video**: filler words "tôi muốn … của" ("I want … by") pushed a re-upload to the top of the list. Filler words are now removed before ranking. The results table is copied verbatim from the tool and names the track actually playing.
- **Classifier**: hyphenated names such as "M-TP" count as one word, so shortened sentences are accepted.
- **Chat fabricated security-check results** when no tool ran: added `<tool_status>` to every chat turn. Re-measured: fabrication 8/10 → 0/10, correct offer protocol 10/10. Declined turns no longer claim "already opened" (1/10). Fabricated data was removed from the DB and wiki journals, with backups in `data/backups/`.

**Lessons from delegating to another model:**
- Tests must exercise the real code path, not just call functions with fake data.
- Tests must never touch the real `data/`.
- `--apply` operations on real data are run by the user.
- Only measure live on the layout actually running, with enough runs.
- When editing a prompt, prove it is byte-identical to the old one, or state clearly that it changed.

## Document Store (`@rag`)

Documents saved to the store are retrieved with explicit commands. The router matches the `@rag` prefix with a regex, not the LLM, so it never confuses it with chat or other commands. Sub-commands are Vietnamese keywords:

- `@rag <question>` — search the store (dense + BM25 + RRF + rerank), drop chunks with `hybrid_score` < `RAG_MIN_SCORE` (default `0.2`); the LLM answers only from evidence, with sources (file name, page). If a file is attached: ask about that file.
- `@rag lưu` ("save") + an attached file — save it to the long-term store. Without a file, "lưu…" is treated as a question.
- `@rag danh sách` ("list") — documents in the store and their IDs.
- `@rag xóa <id>` ("delete") — remove from the store. Accepts exactly one ID; `xóa` followed by several words is treated as a question.
- `@rag` — help.

Files dropped into `data/documents/` (or `RAG_WATCH_FOLDER`) are also indexed into the same store by the watcher. Changing the embedding model requires re-indexing: vectors from two models are not comparable, and a different dimension is rejected.

## Job Search (`@jobs`)

JARVIS interviews you to build a profile + a Vietnamese PDF CV, searches every morning (after 08:00) for job posts **that accept CVs by email**, drafts cover letters, and only sends them via Gmail once you approve.

Gmail setup (once): enable 2-Step Verification, create an "App password" at `myaccount.google.com/apppasswords`, then add it to `.env` yourself:

    GMAIL_ADDRESS=you@gmail.com
    GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx

Commands (UI or Telegram; keywords are Vietnamese):
- `@jobs phỏng vấn` (interview) / `@jobs tiếp tục` (continue) / `@jobs sửa hồ sơ` (edit profile)
- `@jobs tìm` (search) — search now; `@jobs tin <text or link>` (post) — evaluate one post
- Review: `gửi 1, 3` (send), `bỏ 2` (skip), `sửa thư 1: <request>` (edit letter) (the list expires after 3 days, max 10 letters/day)
- `@jobs trạng thái` (status)

Data lives in `data/jobs/` (profile, CV, pending list, sent log). It never applies on sites that require login (TopCV, vLance, LinkedIn); it doesn't write English CVs; posts requiring more English than the profile states are skipped.

---

## 📜 License & Disclaimer

**JARVIS v9.9.5** is a personalised development version for **erikpuw**.

Original project by [Ethan](https://ethanplus.ai).

> **Disclaimer:** This is an independent fan project, not affiliated with Marvel Entertainment, The Walt Disney Company, or any related commercial entity. The JARVIS name and concept are the property of Marvel Entertainment.
