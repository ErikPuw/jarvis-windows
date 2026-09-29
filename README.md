# JARVIS

**Tiếng Việt** | [English](README.en.md)

**Just A Rather Very Intelligent System** — Trợ lý AI giọng nói tiếng Việt chạy local trên Windows.
**Version:** xem file [`VERSION`](VERSION) (nguồn duy nhất).

> *"Thưa ngài, tôi có thể giúp gì cho ngài?"*

JARVIS là trợ lý AI cá nhân chạy hoàn toàn trên máy Windows, lấy cảm hứng từ JARVIS trong Iron Man. Hệ thống có các khả năng sau:
- nói chuyện bằng giọng tiếng Việt theo thời gian thực;
- điều khiển ứng dụng trên máy;
- tra cứu dữ liệu web;
- hỏi đáp trên tài liệu (RAG);
- tự học từ hội thoại;
- giao diện 3D HUD phản ứng theo âm thanh.

---

## 📑 Mục Lục

1. [Tính năng nổi bật](#-tính-năng-nổi-bật)
2. [Một lượt hội thoại chạy thế nào](#-một-lượt-hội-thoại-chạy-thế-nào)
3. [Prompt tập trung một nơi](#-prompt-tập-trung-một-nơi)
4. [Lời đề nghị, "ừ" và chống bịa](#-lời-đề-nghị-ừ-và-chống-bịa)
5. [18 chuyên viên tác vụ (Agents)](#-18-chuyên-viên-tác-vụ-agents)
6. [Tự học, tự tiến hóa, Dream, tự vá lỗi](#-tự-học-tự-tiến-hóa-dream-tự-vá-lỗi)
7. [Bộ nhớ, Memory Center và Obsidian Wiki](#️-bộ-nhớ-memory-center-và-obsidian-wiki)
8. [Giao diện (Frontend)](#-giao-diện-frontend)
9. [Mở rộng: lệnh, skill, hook, MCP, Telegram](#-mở-rộng-lệnh-skill-hook-mcp-telegram)
10. [Kiến trúc hệ thống](#️-kiến-trúc-hệ-thống)
11. [Cài đặt và cấu hình](#-cài-đặt-và-cấu-hình)
12. [API](#-api)
13. [Cấu trúc thư mục](#-cấu-trúc-thư-mục)
14. [Kiểm thử và đo đạc](#-kiểm-thử-và-đo-đạc)
15. [Nhật ký phiên bản](#-nhật-ký-phiên-bản)

---

## 🌟 Tính Năng Nổi Bật

| Tính năng | Mô tả |
|-----------|-------|
| **LLM local** | Gemma 4 E4B-it QAT (profile đang dùng) hoặc Qwen3.5-9B, chạy qua llama.cpp tại `http://localhost:8080/v1`, xử lý được cả văn bản lẫn hình ảnh |
| **Embeddings local** | `nomic-embed-text-v1.5-q8_0` tại `http://localhost:8081/v1`, dùng cho RAG và bộ nhớ ngữ nghĩa |
| **Giọng nói tiếng Việt** | Nhận giọng bằng Web Speech API (`vi-VN`), có sửa lỗi nhận dạng. Đọc thành tiếng bằng Edge-TTS (`vi-VN-NamMinhNeural`) hoặc VieNeu streaming (port 8082); chỉ bật một trong hai |
| **Định tuyến 2 tầng** | Gate chỉ quyết định **trò chuyện hay làm việc**, không cần biết có những agent nào. Orchestrator chọn agent bằng native tool calling, có thể gọi nhiều agent nối tiếp nhau |
| **Lời đề nghị có kiểm soát** | Khi ngài chỉ trò chuyện, Jarvis đề nghị việc có thể làm bằng thẻ `<ask_user>`/`<action_run>`. Ngài đáp "ừ" thì code chạy đúng tool đã đề nghị, không cần LLM đoán lại |
| **Prompt tập trung** | Chữ của mọi prompt nằm trong `prompt/*.md`, code ghép prompt nằm trong `engine/prompts/` |
| **Chống bịa kết quả** | Mọi lượt chat đều có chỉ thị `<tool_status>` nói rằng ở lượt này không có công cụ nào chạy, nên chat không được tự nói "đã kiểm tra" hay nêu trạng thái hệ thống |
| **Tự học tự phản tư** | Mỗi lượt học gồm một lượt đề xuất và một lượt phản biện, rồi code chốt chặn. Có thể gỡ đúng điều vừa học (`retract`). Workflow chạy thành công được dùng lại khi câu lệnh khớp nguyên văn |
| **HyperRAG** | Kết hợp Dense Vector, BM25 và Reciprocal Rank Fusion để tra cứu tài liệu local. Tự theo dõi thư mục `data/documents/` |
| **Bộ nhớ & Obsidian** | SQLite + FTS5 (`data/jarvis.db`) là nguồn gốc. Obsidian Vault (`data/wiki/`) là bản chiếu một chiều. Memory Center trong WebUI là nơi sửa duy nhất |
| **Dream Cycle** | Chạy lúc rảnh ban đêm để tóm tắt và dọn hội thoại, kết quả agent, wiki cũ. Luôn sao lưu trước khi gộp |
| **Self-Healing** | Quét log mỗi 60 giây, phân loại lỗi và ghi vào `Errors.md`. Chỉ nhờ Goose sửa code khi ngài đã duyệt |
| **An ninh** | Guardrails chống prompt injection, firewall IP + kiểm tra Origin (chống CSRF/WebSocket hijacking) cho REST và WebSocket, theo dõi kết nối |

---

## 🔀 Một Lượt Hội Thoại Chạy Thế Nào

`engine/router/decide.py` xét lần lượt từng bước dưới đây. Bước nào khớp thì dừng ở đó:

| # | Bước | Khi nào | Kết quả |
|---|------|---------|---------|
| 0 | `@plans` | Câu bắt đầu bằng `@plans <mục tiêu>`, ví dụ `@plans hôm nay không biết ăn gì` | Chế độ mục tiêu ([engine/plans](engine/plans)): lập kế hoạch tra cứu → gọi agent đọc (search/web/history) → lập lại khi cần → một kết luận. Chat **không** tự đề nghị chế độ này |
| 0b | `@rag` | Câu bắt đầu bằng `@rag` | Kho tài liệu lâu dài ([engine/rag](engine/rag)), xem mục "Kho tài liệu (`@rag`)". Chạy trước `@mention`, nên `@rag` không còn rơi vào agent RAG bắt buộc có tệp |
| 1 | `@mention` | Câu bắt đầu bằng `@desktop`, `@mail`… (danh bạ ở `prompt/tools.md`) | Gọi thẳng agent đó |
| 2 | Đáp lời đề nghị | Lượt trước Jarvis đã hỏi `<ask_user>`, giờ ngài đáp "ừ", "đồng ý", "không"… | Code chạy đúng tool trong `<action_run>`, không qua LLM |
| 3 | Điều khiển bằng giọng | Lệnh âm lượng, tắt máy… | Agent `win_control` |
| 4 | Phàn nàn định tuyến | "sai rồi, tôi chỉ hỏi thôi" | Gỡ workflow vừa chạy nhầm và ghi `routing_correction` |
| 5 | Dùng lại workflow | Câu **khớp nguyên văn** một lệnh đã chạy thành công trước đó | Chạy thẳng chuỗi tool đã lưu |
| 6 | Gate (LLM, `temperature 0`) | Mọi câu còn lại | `general`, `general_knowledge`, `orchestrator`, hoặc `attachment_clarify` khi có tệp đính kèm |

- **orchestrator**: classifier chọn agent. Với câu lệnh nằm lẫn trong lời chat, classifier được rút gọn câu (ví dụ "…bạn mở giúp tôi được không?" thành "mở Notepad"), nhưng chỉ khi câu rút gọn **chỉ bớt từ**, không thêm từ mới. Agent chạy xong, `next_tasks` quyết định có gọi thêm agent khác không. Nhiều kết quả được `synthesizer` gộp lại thành một câu trả lời.
- **plan** (`@plans`): tối đa 3 vòng × 3 bước (tổng 5), mỗi bước 60 giây; model chỉ chọn đích và viết câu tra cứu (JSON có schema), không cầm tool; vòng nào không bước nào thành công thì dừng. Tra web qua tool `web_research` (Google News RSS rồi đọc 3 bài), mỗi trang được soát chèn lệnh. Sở thích trong `Preferences.md` chỉ bước kết luận thấy, không bao giờ nằm trong câu tra cứu gửi ra ngoài.
- **general / general_knowledge**: nhánh chat ghép 5 khối message (xem mục sau). Nếu agent từ chối làm, lượt đó cũng rơi về nhánh chat, kèm chỉ thị "chưa làm được".
- **Tệp đính kèm**: bảng chọn chỉ đưa agent đọc được định dạng đó (`attachment_agents_for` lấy từ `rag_tool` + `image_engine` + đuôi Office): pdf/txt/md/csv/json/html → RAG; docx/xlsx/pptx → RAG hoặc OfficeCLI; jpg/png/webp/bmp → Upscayl. Định dạng khác thì Jarvis nói "chưa xử lý được". Có tệp mà classifier chọn agent không dùng tệp → hỏi lại bằng bảng chọn (trừ `@mention`).
- **Tệp nén** (`.zip .rar .7z .tar .gz .tgz .bz2 .xz .zst`, [engine/router/archive.py](engine/router/archive.py)): xử lý **trước gate** bằng `bsdtar` có sẵn của Windows (không cài thêm thư viện). Bên trong có **đúng 1** tệp xử lý được → giải nén riêng tệp đó và xử lý như gửi thẳng; **nhiều tệp** → dừng, liệt kê tên, nhờ gửi từng tệp; **không có** → báo rõ. Chặn: > 200 mục, tệp > 200 MB, đường dẫn `..`/tuyệt đối, tệp nén lồng; timeout 60 giây.

---

## 🧩 Prompt Tập Trung Một Nơi

Muốn sửa prompt thì sửa file `.md`, không viết chữ prompt trong code.

| Nhóm | File trong `prompt/` | Code dùng (`engine/prompts/`) |
|------|----------------------|-------------------------------|
| Persona, luật cứng | `identity.md`, `soul.md`, `user.md`, `persona_short.md` | `persona.py` |
| Chat | `capabilities.md`, `offer_protocol.md`, `voice_cues.md`, `style_lock.md`, `fallback.md`, `turn_status.md`, `tool_status_none.md`, `tool_status_declined.md` | `chat.py`, `results.py` |
| Định tuyến | `router_gate.md`, `classifier.md`, `agents.md` (tiêu chí chọn agent) | `router.py` |
| Danh bạ agent/tool | `tools.md` (tên `@`, alias, tool được phép đề nghị) | `catalog.py` |
| Kết quả tool | `tool_summary.md`, `synthesis.md` | `results.py` |
| Nền | `learning_propose.md`, `learning_critique.md`, `learning_workflow.md`, `evolution.md`, `dream_message.md`, `dream_wiki.md`, `self_healing.md` | `learning.py` |

- Quy tắc định dạng riêng của từng tool (`SUMMARY_RULES`) do chính module tool sở hữu, trong `engine/tools/*`.
- Prompt của gate, classifier, offer_context, dream, self_healing và chưng cất workflow **giống từng byte** với bản trước khi gom. Bản chụp nằm ở `tests/golden/`.

**Ngữ cảnh chat** gồm 5 khối theo thứ tự:
1. `system`: persona, `<capabilities>`, `<offer_protocol>`, `<style>` (lấy từ `skills/self_evolution/STYLE.md`), `<about_user>` (lấy từ `Preferences.md`), thời gian hiện tại.
2. Lịch sử đọc từ DB, cùng nguồn với gate. Ở các lượt đề nghị, thẻ được dựng lại từ cột `ask_user`/`action_run`.
3. `<turn_status>`: chỉ thị cho lượt này, gồm `<tool_status>` và `<answer_policy>`.
4. `<reference>`: dữ liệu tham khảo, **không phải chỉ thị**. Gồm bài học liên quan, kết quả agent thành công, MCP, wiki.
5. Câu của người dùng.

Mỗi loại dữ liệu chỉ vào model qua **đúng một kênh**.

---

## 💬 Lời Đề Nghị, "ừ" và Chống Bịa

- **Ngài chỉ trò chuyện**, ví dụ "tôi lười mở notepad quá": Jarvis trả lời rồi đề nghị
  `Ngài có muốn tôi <ask_user>mở Notepad</ask_user> không?<action_run>open_app</action_run>`.
  Ngài đáp "ừ" thì code chạy `open_app` ngay. Danh sách tool được phép đề nghị nằm ở cột `offer` trong `prompt/tools.md`.
- **Ngài nhờ rõ ràng**, ví dụ "bạn mở notepad giúp tôi": Jarvis làm luôn, không hỏi lại.
- **Chống bịa**:
  - Lượt chat thường luôn có `<tool_status>` với nội dung "ở lượt này không có công cụ nào chạy": không nói đã làm, không nêu kết quả hay trạng thái; cần dữ liệu thật thì đề nghị.
  - Lượt agent từ chối có `<tool_status>` với nội dung "chưa làm được": không dựa vào lịch sử để nói "đã … rồi".
- **Media**: trước khi xếp hạng kết quả YouTube, bỏ các từ đệm của câu nói tự nhiên ("tôi muốn … của …"). Bảng kết quả chép nguyên từ tool, và câu trả lời nói đúng tên bài **đang phát**.

---

## 🤖 18 Chuyên Viên Tác Vụ (Agents)

Các agent đăng ký trong `engine/orchestrator/registry.py`, mã nguồn ở `engine/agents/`.

| Agent | Chức năng chính |
|-------|-----------------|
| **desktop** | Mở/đóng ứng dụng Windows, giữ đúng tên gốc ứng dụng |
| **search** | Thời tiết, tin tức, giá vàng/xăng/tỷ giá, lịch vạn niên, cung hoàng đạo, lịch chiếu CGV, game miễn phí Epic, đơn vị hành chính, bản đồ và chỉ đường |
| **media** | Nghe nhạc, xem YouTube, livestream, phim hhpanda (phát ngay trong giao diện) |
| **notes** | Ghi, xem, xoá ghi chú |
| **vision** | Chụp và phân tích màn hình bằng LLM Vision |
| **webcam** | Chụp và phân tích khung hình webcam |
| **office** | Tạo/sửa tệp Word, Excel, PowerPoint đính kèm (skill `officecli`) |
| **rag** | Đọc, tóm tắt, hỏi đáp trên tệp đính kèm hoặc tài liệu đã index |
| **legal** | Tra cứu văn bản pháp luật Việt Nam |
| **vietlott** | Kết quả Mega 6/45, Power 6/55, xác suất, backtest (không dự đoán) |
| **security** | Kiểm tra an ninh mạng, cổng, firewall |
| **email** | 10 email gần nhất và lịch hẹn 7 ngày tới trong Outlook |
| **history** | Xem lại lịch sử trò chuyện |
| **image** | Tăng độ phân giải ảnh bằng Upscayl |
| **project** | Kiểm tra dự án code, quét lỗi cú pháp |
| **goose** | Mở giao diện Goose để ngài tự thao tác |
| **win_control** | Điều khiển ứng dụng Windows chạy nền qua cua-driver (mở app, bấm, nhập chữ), đổi trạng thái cửa sổ |
| **dream** | Chạy ngay một chu kỳ Dream |

### ➕ Thêm agent mới

Chat, WebUI (gợi ý `@`), Telegram `/agents` và classifier đều **tự lấy** danh sách agent từ các file dưới đây, không phải sửa prompt hay code chat. Chỉ cần làm đủ các bước:

| # | File | Việc cần làm |
|---|------|--------------|
| 1 | `engine/agents/agent_<tên>.py` | Viết agent: hàm `run_<tên>_agent` |
| 2 | `engine/orchestrator/registry.py` | Thêm `"<tên>": {"module": ..., "runner": ...}` vào `AGENT_REGISTRY` |
| 3 | `prompt/tools.md` | Thêm mục `## @<tên>`: dòng `alias:`, một dòng mô tả, rồi mỗi tool một dòng `- tool | nhãn | offer` (hoặc `-` nếu chat không được đề nghị tool này). Chat sẽ tự thấy tên **"Agent <Tên>"** |
| 4 | `prompt/agents.md` | Thêm dòng `- <tên>: <khi nào chọn agent này>`. Đây là mô tả tool mà classifier nhìn thấy |
| 5 | `commands/<tool>.md` | Mỗi tool của agent cần một file lệnh |
| 6 | Test | Cập nhật `EXPECTED_AGENT_CRITERIA` trong `tests/test_prompts_catalog.py` (và danh sách tool `offer` nếu có thêm), rồi chụp lại golden của classifier bằng lệnh bên dưới |
| 7 | Chạy lại | `rtk python -m pytest tests -q --ignore=tests/live`, sau đó **khởi động lại JARVIS** (`tools.md` được đọc một lần và giữ trong bộ nhớ) |

```bash
rtk python -c "import json; from engine.orchestrator.classifier import _build_tools; open('tests/golden/classifier_tools.json','w',encoding='utf-8').write(json.dumps(_build_tools(), ensure_ascii=False, indent=1))"
```

Nếu thiếu một bước, `tests/test_prompts_catalog.py` sẽ báo lỗi. Test này đòi tập agent trong `tools.md`, `agents.md` và `AGENT_REGISTRY` phải giống hệt nhau, và mỗi tool phải có file lệnh cùng đúng agent sở hữu. Vì vậy không thể có agent chạy được mà chat hay classifier lại không biết.

---

## 🧬 Tự Học, Tự Tiến Hóa, Dream, Tự Vá Lỗi

Tất cả chạy nền khi hệ thống rảnh, không làm chậm lượt trò chuyện. Nếu ngài chat tiếp, tác vụ nền đang chạy nhường chỗ và chạy lại sau.

### 📖 Learning tự phản tư ([learning.py](engine/core/learning.py))

1. **Đề xuất** (`learning_propose.md`): model đọc 3–5 lượt gần nhất trong DB và các kết quả agent thành công, rồi đề xuất tối đa 2 mục. Mỗi mục có `kind` là một trong `user_fact`, `preference`, `behaviour_lesson`, `routing_note`.
2. **Phản biện** (`learning_critique.md`): model đặt mỗi đề xuất cạnh mục cũ gần nhất, rồi quyết định `skip`, `merge`, `replace` hoặc `new`.
3. **Code chốt chặn**:
   - Bằng chứng phải khớp nguyên văn hội thoại; với `user_fact`/`preference`, phải nằm trong lời của ngài.
   - Không học trạng thái nhất thời ("lười", "mệt").
   - Luật hành vi không được bàn chuyện hỏi, xin phép, công cụ, agent hay thẻ.
   - `merge`/`replace` chỉ được đụng đúng mục cũ đã đưa cho model xem.
4. **Gỡ bài học**: nếu ngài phủ nhận đúng điều vừa học, lượt học kế tiếp đề xuất `retract`. Code chỉ hoàn tác được mục do chính lượt học trước ghi: mục mới thì xoá, mục đã gộp thì trả về nội dung cũ.
5. **Workflow**: chuỗi tool chạy thành công được lưu vào `validated_workflows` và dùng lại khi câu lệnh khớp nguyên văn (không phân biệt hoa/thường). Theo thiết kế, không so khớp gần đúng và không bỏ dấu, vì bỏ dấu làm trùng các từ như `bật`/`bắt`, `tắt`/`tát`.
6. `routing_note` chỉ được ghi thành **đề xuất** vào `data/wiki/System/Evolution.md` để người duyệt. Không bao giờ tự áp dụng.

### 🧬 Evolution ([evolution.py](engine/core/evolution.py))
- Chỉ viết luật **giọng điệu** (xưng hô, emoji, độ dài, sự hài hước) vào `skills/self_evolution/STYLE.md`. Luật mới không được đụng tới persona, `<soul_rules>` hay `<offer_protocol>`.
- Mỗi lần cập nhật đều tăng version và ghi changelog gọn vào `Evolution.md`.

### 💤 Dream Cycle ([dream.py](engine/core/dream.py))
- **Khi nào chạy**: trong khung giờ yên tĩnh (mặc định 02:00–05:00), mỗi 24 giờ, khi hệ thống đang rảnh. Có thể gọi thủ công bằng `@dream`, câu nói tự nhiên, hoặc `POST /api/dream/run`.
- **Làm gì**: tóm tắt hội thoại cũ (hơn 14 ngày), dọn `agent_outcomes`, gộp nhật ký tháng, nén `topics/*.md`, xoay vòng `Errors.md` và `Evolution.md`.
- **An toàn**: luôn sao lưu vào `data/dream_archive/` hoặc `data/wiki/.trash/dream/` trước khi gộp. Nếu LLM không trả lời được, Dream giữ nguyên dữ liệu gốc để thử lại ở chu kỳ sau.

### 🛡️ Self-Healing ([self_healing.py](engine/core/self_healing.py))
- Quét log mỗi 60 giây khi rảnh. LLM phân loại lỗi (`CODE_BUG`, `TRANSIENT`, `CONFIG`, `DEPENDENCY`, `OTHER`) và ghi một mục vào `data/wiki/System/Errors.md`.
- Với lỗi code, Jarvis **xin ngài duyệt** trên phiên WebUI trước khi nhờ Goose CLI sửa đúng một tệp. Không có phiên để duyệt thì không sửa.

---

## 🗂️ Bộ Nhớ, Memory Center và Obsidian Wiki

- **Nguồn gốc**: `data/jarvis.db` (SQLite + FTS5), gồm các bảng `messages` (có cột `ask_user`/`action_run`), `memories`, `learnings`, `agent_outcomes`, `validated_workflows`.
- **Memory Center** (WebUI, `/api/memory-control/*`, `/api/learnings/*`…) là **nơi sửa duy nhất**. Mọi đường ghi, kể cả learning tự động và script dọn, đều đi qua cùng các hàm của Memory Center.
- **Obsidian Vault** `data/wiki/` là bản chiếu **một chiều** từ DB:
  - `System/Preferences.md`, `System/Learning.md`, `System/Workflows/*.md`;
  - `System/Evolution.md`, `System/Errors.md`, `System/Dream.md`;
  - nhật ký ngày `daily/MM-YYYY/YYYY-MM-DD.md`.

  Jarvis không đọc ngược dữ liệu từ Obsidian.
- **Truy vấn kép**: `history_engine.py` và `wiki_retrieval.py` tìm song song trong SQLite FTS5 và các tệp Markdown.
- **Ghi chú** (`note_engine.py`): Markdown có YAML frontmatter, mở và sửa được bằng Obsidian.

---

## 🎨 Giao Diện (Frontend)

Xây dựng bằng **Vite + TypeScript + Three.js**, phong cách Dark-Tech Glassmorphism. Mã nguồn ở `frontend/src/`:

| File | Vai trò |
|------|---------|
| `main.ts` | Máy trạng thái, Command Bar (Ctrl+K; gõ `/` gợi ý lệnh trong `commands/`, gõ `@` gợi ý agent), thẻ tương tác, trình phát media, bản đồ MapLibre |
| `orb.ts` | Quả cầu hạt Three.js phản ứng theo âm thanh |
| `voice.ts` | Web Speech API, micro, phát âm thanh, ngắt TTS tức thì |
| `ws.ts` | WebSocket client, tự kết nối lại |
| `dashboard-hud.ts` | Telemetry: RAM, CPU, VRAM GPU, NPU, agent đang chạy, token |
| `icons.ts` | Icon morph (morphicons + lucide) cho nút, flow-step, tracker; `runAction` cho nút có vòng xoay → ✓/✗ |
| `settings/` | Dashboard cài đặt toàn màn hình (xem dưới) |
| `style.css` | Giao diện HUD |

**Settings dashboard** (`frontend/src/settings/`): mở ra phủ toàn màn hình, orb tạm dừng; sidebar 15 trang, trên mobile thành ngăn kéo.

| File | Vai trò |
|------|---------|
| `index.ts` | Khung: mở/đóng, sidebar, chuyển trang, cài đặt lần đầu, nạp dữ liệu, các nút lưu/kiểm tra |
| `pages.ts` | HTML các trang: Tổng quan, Kết nối & API, Giọng đọc, Người dùng, Hệ thống, Bộ nhớ, Agents, Hooks, Skills, Prompts (sửa và lưu được), Commands, Plugins, MCP Connect, Graphfy, Thông tin (README) |
| `memory.ts` | Memory Center: xem, sửa, xoá có kiểm tra quan hệ, chọn nhiều để xoá |
| `graphfy.ts` | Bản đồ cấu trúc **tự sinh từ code** qua `GET /api/graphfy` (`engine/UIUX/graphfy.py` quét import bằng `ast`): mỗi gói `engine/` một khối, riêng `core/` và `server/` tách theo file; đường tím = chỗ gọi LLM; khối LLM vẽ thành **bộ não mạch điện** (nửa não · nửa mạch có xung chạy, rộng 90%), đường từ dưới lên cắm vào chân tín hiệu. Làn: Đầu vào · Xử lý lượt · LLM (trục giữa) · Phản hồi / Bộ nhớ · Nạp tài liệu · Chạy nền · Hỗ trợ (mờ) · Khác. Module mới tự hiện ở làn "Khác" cho tới khi được gán trong `LANES`. Xung sáng mô phỏng luồng trên mọi đường; rê chuột lọc đường của khối và xem file; kéo thả, lưu bố cục `jarvis.graphfy.positions.v4` |
| `api.ts`, `types.ts`, `styles.css` | Gọi API (timeout 20s, hiện đúng lỗi từ backend), kiểu dữ liệu, giao diện |

Danh sách nặng (agents, hooks, skills, prompts, commands, plugins) lấy từ `/api/settings/catalog` khi mở trang cần, không nằm trong `/api/settings/status` (endpoint này được gọi mỗi 5 giây).

---

## 🔌 Mở Rộng: Lệnh, Skill, Hook, MCP, Telegram

- **33 lệnh Markdown** trong `commands/` (`open_app`, `check_mail`, `search_media`, `rag_tool`, `win_control`, `dream`…), nạp nóng.
- **3 skill** trong `skills/`: `legal`, `officecli`, `self_evolution`.
- **Hook & plugin**: các sự kiện `on_startup`, `on_shutdown`, `ON_MESSAGE_RECEIVE`, `ON_RESPONSE_GENERATE`, nạp plugin `.py`/`.ts` động.
- **Tự cài extension** (`install_extension`): nạp nóng plugin/skill/hook mới từ URL hoặc code, không cần khởi động lại.
- **MCP** (`config/mcp_config.json`): `wikipedia-mcp`, `gitnexus`, `context7`, `headroom`, `ScraplingServer`, `codebase-memory-mcp`.
- **Command Bar**: `/tên_lệnh <tham số>` chạy lệnh trong `commands/` (gõ `/tên_lệnh` trống để JARVIS hỏi từng tham số); `@agent câu lệnh` gọi thẳng agent (bước 1 của router). Trang Commands và Agents trong Settings ghi đúng cú pháp này.
- **Telegram Bot**: điều khiển từ xa, xác thực Chat ID. Lệnh `/agents` đọc danh bạ từ `prompt/tools.md`.

---

## 🏗️ Kiến Trúc Hệ Thống

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
│ decide: @mention → "ừ" → voice →      │◄──│ prompt/*.md → persona, chat, │
│ complaint → replay → gate             │   │ router, results, learning,   │
└──────┬─────────────────────┬──────────┘   │ catalog                      │
       │ orchestrator        │ general      └──────────────────────────────┘
       ▼                     ▼
┌──── engine/orchestrator ───┐  ┌── chat (5 khối) ──┐
│ classifier → agents →      │  │ system · lịch sử  │
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

## 🚀 Cài Đặt và Cấu Hình

### Yêu cầu
- Windows 10/11 64-bit, Python 3.11+, Node.js 18+, Google Chrome.
- llama.cpp server: LLM tại `:8080`, embeddings tại `:8081`.
- Redis tại port 6379 (Windows native hoặc WSL).
- `yt-dlp` trong PATH (cho tìm kiếm YouTube).

### Các bước

```bash
git clone https://github.com/erikpuw/jarvis-windows.git
cd jarvis-windows
pip install -r requirements.txt
cd frontend && npm install && cd ..

# Chứng chỉ SSL cho HTTPS/WSS
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'

# Tạo .env từ mẫu rồi điền giá trị (bảng giải thích bên dưới). Nếu quên, server tự copy mẫu khi khởi động.
cp .env.example .env           # PowerShell: Copy-Item .env.example .env
# Chạy llama.cpp (8080, 8081) và Redis (6379)

python server.py               # backend, tự bật Stream TTS :8082 khi dùng VieNeu
cd frontend && npm run dev     # frontend, mở terminal riêng
# Mở Chrome: https://localhost:8340
```

### Cấu hình `.env`

Danh sách đầy đủ kèm giải thích nằm trong [`.env.example`](.env.example). Các biến quan trọng nhất:

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `LOCAL_URL` | `http://localhost:8080/v1` | Endpoint LLM llama.cpp |
| `LOCAL_API_KEY` | `sk-no-key-required` | API key cho LLM local |
| `LOCAL_MODEL` / `VISION_MODEL` | tên model đang chạy | Model văn bản / hình ảnh |
| `LOCAL_EMBED_URL` | `http://localhost:8081/v1` | Endpoint embeddings |
| `LOCAL_EMBED_MODEL` | `nomic-embed-text-v1.5-q8_0` | Model embeddings |
| `EDGE_TTS_ENABLED` / `VIENEU_TTS_ENABLED` | `true` / `false` | Chọn engine TTS; không được bật cả hai |
| `TTS_LOCAL_MODEL` | `vi-VN-NamMinhNeural` | Giọng Edge-TTS |
| `USER_NAME` / `HONORIFIC` | `erikpuw` / `thưa ngài` | Cá nhân hóa |
| `REDIS_URL` | `redis://localhost:6379` | Redis |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_CHAT_IDS` | tùy chọn | Telegram Bot |
| `JARVIS_CORS_ORIGINS` | `localhost:5173`, `localhost:8340` | Danh sách origin (phân cách dấu phẩy) được phép gọi API/WebSocket từ trình duyệt. `*` bị bỏ qua. Trang cùng host với server (`https://<ip>:8340`) luôn được phép |
| `RAG_WATCH_FOLDER` | `data/documents` | Thư mục RAG tự theo dõi |
| `DREAM_ENABLED` | `true` | Bật/tắt Dream |
| `DREAM_RETENTION_DAYS` | `14` | Số ngày giữ nguyên dữ liệu trước khi Dream gộp |
| `DREAM_OUTCOME_RETENTION_DAYS` | `= DREAM_RETENTION_DAYS` | Số ngày giữ `agent_outcomes` thành công (lỗi được giữ gấp đôi) |
| `DREAM_QUIET_HOUR_START` / `_END` | `2` / `5` | Khung giờ Dream được tự chạy |
| `DREAM_INTERVAL_HOURS` | `24` | Khoảng cách tối thiểu giữa hai lần Dream |

**Sampling nhánh chat** (Gemma, `engine/server/llm_server.py`): `temperature 0.4 / top_p 0.8 / top_k 40`, đã đo và giữ nguyên. Gate và classifier luôn dùng `temperature 0`.

### 📱 Truy cập từ xa qua Tailscale
1. Cài Tailscale trên máy chạy JARVIS và trên điện thoại, đăng nhập **cùng một tài khoản**.
2. Trên máy chủ: chạy `npm run dev -- --host` trong `frontend/`, và đặt `JARVIS_CORS_ORIGINS=http://<IP-Tailscale-của-PC>:5173` trong `.env` (không dùng `*`: giá trị này bị bỏ qua, và WebSocket sẽ từ chối origin không có trong danh sách).
3. Trên điện thoại: mở Safari hoặc Chrome, vào `http://<IP-Tailscale-của-PC>:5173`.

Cách này không cần mở port trên router và không lộ IP ra ngoài.

---

## 🌐 API

**WebSocket**: `/ws/voice` truyền giọng nói, stream chữ và âm thanh, thẻ tương tác, `media_open`, ghim bản đồ.

| Nhóm | Endpoint |
|------|----------|
| Sức khỏe | `GET /api/health`, `/api/health/detailed`, `/api/usage`, `/api/logs` |
| Cài đặt | `/api/settings/status`, `/api/settings/catalog`, `/api/settings/keys` (chỉ nhận `LOCAL_API_KEY`, `TTS_LOCAL_KEY`, `LOCAL_URL`, `TTS_LOCAL_MODEL`, `USER_NAME`, `HONORIFIC`), `/api/settings/preferences`, `/api/settings/test-llm`, `/api/settings/test-tts`, `/api/settings/reset-tokens`, `POST /api/prompts/save`, `/api/system/readme`, `POST /api/restart` |
| TTS/STT | `/api/tts/voices`, `/api/tts/voice`, `/api/tts/voices/clone`, `/api/tts-test`, `/api/stt` |
| Memory Center | `/api/memory-control/{summary,dependencies,update,delete}`, `/api/learnings/*`, `/api/memories/*`, `/api/notes/*`, `/api/workflows/*`, `/api/outcomes/list`, `/api/memory-registry/list` |
| Hội thoại | `/api/history`, `/api/conversations`, `/api/conversations/sessions`, `/api/conversations/session/{id}`, `/api/conversations/update`, `/api/conversations/delete` |
| Media | `/api/media/search`, `/api/media/resolve`, `/api/media/episodes`, `/api/media/local/{path}` |
| RAG & tệp | `/api/rag/status`, `DELETE /api/rag/document`, `/api/upload` |
| MCP | `/api/mcp/servers` (trạng thái thật từ hub; `args` được che giá trị bí mật) |
| Khác | `/api/command-bar/skills`, `/api/command-bar/context`, `/api/feedback`, `/api/feedback/stats`, `POST /api/dream/run`, `/api/agents/goose/launch` |

---

## 📂 Cấu Trúc Thư Mục

```
jarvis/
├── server.py              # FastAPI + WebSocket
├── prompt/                # CHỮ của mọi prompt (*.md) + danh bạ tools.md, agents.md
├── commands/              # 33 lệnh Markdown nạp nóng
├── skills/                # legal, officecli, self_evolution (STYLE.md)
├── config/                # mcp_config.json
├── scripts/               # cleanup_learning_2026_09.py (mặc định chỉ xem, --apply mới dọn)
├── data/                  # jarvis.db, wiki/ (Obsidian), documents/, backups/, dream_archive/
├── docs/superpowers/      # specs/, plans/, reports/ (tài liệu nội bộ, không đưa lên repo)
├── engine/
│   ├── router/            # decide, gate, replay, ask_user, fast_paths, dispatch, chat
│   ├── orchestrator/      # classifier, dispatcher, synthesizer, registry
│   ├── prompts/           # ghép prompt: persona, chat, router, results, learning, catalog
│   ├── agents/            # 18 agent
│   ├── tools/             # công cụ thực thi (media_search, desktop_automation, ...)
│   ├── core/              # memory, learning, evolution, dream, self_healing, RAG, guardrails
│   ├── server/            # llm_server, tts_manager, stream_tts, telegram_bot
│   ├── context/           # quản lý ngữ cảnh, ngân sách token
│   ├── security/          # firewall, connection monitor
│   ├── UIUX/              # REST router, thẻ tương tác
│   ├── main/              # FlowTracker, FlowAgents, xác nhận người dùng
│   └── chunking/          # AST chunker (Tree-sitter)
├── frontend/src/          # main.ts, orb.ts, voice.ts, ws.ts, icons.ts, dashboard-hud.ts, style.css
│   └── settings/          # dashboard cài đặt: index, pages, memory, graphfy, api, styles
└── tests/                 # unit tests, golden/, live/probes/
```

---

## 🧪 Kiểm Thử và Đo Đạc

```bash
rtk python -m pytest tests -q --ignore=tests/live
```

- **Golden** (`tests/test_prompts_wired.py`): prompt của gate, classifier, offer_context, dream, self_healing và workflow phải giống từng byte với `tests/golden/`. Test này cũng kiểm tra không còn chữ prompt viết trong code, và các module import được theo mọi thứ tự.
- **Không đụng dữ liệu thật**: test learning và test script dọn chạy trên DB và wiki tạm.
- **CI** (`.github/workflows/ci.yml`, chạy mỗi lần push `main` và mỗi PR): `ruff check .` (rule trong `ruff.toml`), compile toàn bộ Python, `python .github/scripts/check_imports.py` (mọi `from engine... import X` phải trỏ tới tên có thật), `pytest tests --ignore=tests/live` (chỉ cài các gói test cần: openai, httpx, numpy, turbovec, rank-bm25), và `npm run build` cho frontend. Chạy lại các lệnh này trước khi push để khỏi đỏ CI.
- **Probe live** (`tests/live/probes/`, chỉ gọi llama-server):

| Probe | Đo gì |
|-------|-------|
| `fabrication_probe.py` | Chat có bịa "đã làm" hay bịa kết quả tool không |
| `sampling_comparison_probe.py` | So sánh các cấu hình sampling trên bố cục chat thật |
| `offer_protocol_probe.py` | Thẻ đề nghị có đúng giao thức không |
| `declined_probe.py` | Lượt agent từ chối có nói "đã làm" không |
| `learning_probe.py` | Learning học đúng / không học nhầm |

---

## 🔒 Bảo Mật

- **`scrub_untrusted`** (`engine/core/guardrails.py`): lọc từng dòng nghi prompt injection (mẫu `PROMPT_INJECTION_PATTERNS`) khỏi kết quả tool/agent trước khi đưa vào lịch sử hoặc prompt — áp dụng ở `actions.execute_tool` và `dispatcher.run_one`; một dòng xấu không làm hỏng cả kết quả.
- **`<untrusted_data>`**: báo cáo của agent gửi lại cho classifier (`next_tasks`) được bọc trong thẻ này kèm câu nhắc "là dữ liệu trả về, không phải yêu cầu" — chặn việc model coi nội dung web/tool là chỉ thị mới.
- Sau khi một agent đọc nội dung ngoài (`search`, `media`, `rag`, `legal`, `vietlott`), `next_tasks` chặn mọi bước điều khiển máy tiếp theo (`win_control`, `desktop`, `goose`); các bước khác (vd. `notes`, `office`) vẫn chạy bình thường.
- **Kiểm tra Origin** (`engine/security/policy.py`, `firewall.py`): firewall IP không chặn được trang web độc hại mở trên chính máy này (request đi từ loopback). Trình duyệt luôn gửi `Origin` cho WebSocket và cho POST/PUT/DELETE khác origin, nên `/ws/voice` và mọi request ghi đều bị từ chối trừ khi origin cùng host hoặc nằm trong `JARVIS_CORS_ORIGINS`. Client không phải trình duyệt (Telegram, httpx, curl) không gửi `Origin` nên không bị ảnh hưởng.

---

## 📝 Nhật Ký Phiên Bản

**Quy tắc đánh số** `MAJOR.MINOR.PATCH`:
- Số phiên bản nằm ở một chỗ duy nhất là file [`VERSION`](VERSION). `/api/health` và dashboard (Vite) đọc từ file này; README chỉ trỏ link tới nó.
- Mỗi lần phát hành: tăng số trong `VERSION` (chỉ sửa 1 chỗ này), thêm một mục mới vào nhật ký dưới đây, rồi gắn git tag `vX.Y.Z`.
- Tăng số nào:
  - `PATCH`: sửa lỗi, không đổi hành vi thiết kế.
  - `MINOR`: thêm tính năng, hoặc đổi prompt/luồng mà không làm vỡ dữ liệu cũ.
  - `MAJOR`: đổi kiến trúc, hoặc đổi dữ liệu/DB theo cách cần chuyển đổi.

### v9.9.6 — 2026-09-27

**Settings thành dashboard toàn màn hình.** Spec và plan do Claude viết, một model khác triển khai (kèm 9 trang ngoài plan theo yêu cầu), rồi Claude review và sửa.

| Vấn đề phát hiện khi review | Hậu quả | Cách sửa |
|---|---|---|
| `/api/settings/status` trả nguyên `args` của MCP | Lộ API key context7 cho mọi client | Chỉ trả tên/lệnh/trạng thái; `args` che giá trị bí mật (`_redact_args`) |
| Status nhét README, prompts, commands… (≈93KB) vào mỗi lần poll | Settings chậm, dễ timeout | Tách sang `/api/settings/catalog`, gọi khi mở trang |
| `mcp_servers` đổi từ dict sang list | HUD hiện "0,1,2" với chấm lỗi | Trả lại `{tên: trạng thái}` từ hub thật |
| `/api/mcp/servers` dùng `_json` chưa import | Trang MCP lỗi | Sửa, trạng thái lấy từ hub thay vì cờ `enabled` |
| UI gửi `SERVER_API_KEY`, `FISH_AUDIO_API_KEY` | Backend từ chối, báo "lỗi kết nối" | Đổi sang `LOCAL_API_KEY`, `TTS_LOCAL_KEY` |
| Bản chuyển vào `settings/` bỏ sự kiện `jarvis:overlay` | Orb không tạm dừng | Phát lại sự kiện |
| Giọng đọc gõ cứng 4 giọng Google, lưu sai API | Lưu giọng giả | Nạp `/api/tts/voices`, lưu qua `/api/tts/voice`, gắn nút clone |
| CSS ép `display:flex` lên lưới Bộ nhớ, chữ IN HOA, chữ < 12px | Bố cục vỡ, font lệch | Sửa lưới, một họ font, tối thiểu 12px; gỡ 42 rule chết |
| Command-bar gợi ý `/help`, `/clear`, skill, `/plugin` | Gõ vào đều "Không tìm thấy lệnh" | Chỉ gợi ý lệnh backend chạy được |
| Thu nhỏ sidebar Settings: nhãn `display:none` + icon căn giữa ngay lập tức | Chữ/icon nhảy trong lúc co chiều rộng | Icon giữ nguyên toạ độ, nhãn mờ dần (`opacity`), không xuống dòng |
| Dashboard lấy số phiên bản từ `.env` | Lệch với `VERSION` | Vite đọc file `VERSION` |

**Mascot trên nút gửi** (`frontend/src/mascot.ts`) — port TypeScript thuần của [nilbuild/page-mascot](https://github.com/nilbuild/page-mascot) (MIT), không cần React (gói npm `page-mascot` không dùng tới, có thể gỡ).
- **Vị trí:** đứng yên ngay trên `#cmd-send`, thân đè lên viền trên command-bar (lún 20px) để trông như ngồi trên thanh lệnh; bên trái vẫn là dòng trạng thái. Cỡ 56px (mobile 44px).
- **Vùng bấm:** chỉ phần đầu nhận click; phần thân cho click xuyên qua nên nút gửi vẫn bấm bình thường.
- **Tương tác:** đầu quay theo chuột (8 hướng), thỉnh thoảng chớp mắt; bấm để đổi biểu cảm (tim, lấp lánh, vui), bấm nhanh 4 lần = choáng.
- **Theo trạng thái JARVIS** qua sự kiện `jarvis:mascot` (phát trong `transition()` và `showError()`): thinking nhìn lên, working lấp lánh, speaking vui, lỗi/restart choáng, idle 60 giây thì ngủ.
- **Nhân vật:** sprite `frontend/public/mascots/<tên>-directions.webp` và `<tên>-reactions.webp` (lưới 3×3, nền trong suốt); đổi nhân vật bằng tham số `name` của `mountMascot` trong `main.ts`.
- **Phục vụ file tĩnh:** `mount_frontend_dist` (`engine/UIUX/ui_engine.py`) phục vụ `/` và mọi thư mục trong `frontend/dist` (`assets/`, `mascots/`, …) — trước đây chỉ `/assets` nên ảnh mascot bị 404 trên app desktop.
- **Test:** `frontend/e2e/mascot.cjs` (vị trí, không che nút gửi, hướng nhìn, biểu cảm, trạng thái, mobile) và `tests/test_frontend_static.py`.

**Khung các bước (flow_tracker) và thẻ agent (flow_agents) thiết kế lại** — một font giao diện 12–12.5px cho cả hai (bỏ monospace), dấu trạng thái cùng cỡ.
- **Khung các bước:** đầu khung = icon trạng thái + bước hiện tại + số đếm dạng viên `6/7` + thanh tiến độ mảnh; danh sách là dòng thời gian dọc (chấm xanh lá xong · xanh dương nhấp nháy đang chạy · xám chưa tới), bỏ số "1. 2. 3."; phần sau "→" thành chữ phụ mờ, bỏ "..." cuối nhãn.
- **Thẻ agent:** icon lucide trong ô bo góc + tên + việc đang làm (bỏ tiền tố "Thực thi:"). Backend giữ nguyên `"<emoji> Agent <Tên>"` (Telegram vẫn dùng); frontend tách emoji và chọn icon theo tên trong `AGENT_ICON` (`frontend/src/icons.ts`). Agent mới trong `engine/agents` chưa có trong bảng vẫn hiện, với icon robot.
- **Test:** `frontend/e2e/flow-ui.cjs` (WebSocket giả phát một lượt chạy).

**Đồng hồ lật kiểu HTC Sense** (`frontend/src/clock.ts`) — mỗi chữ số một ô (`HH:MM`; dấu `:` là 2 chấm tròn phát "sóng radar" — vòng sáng xanh lan ra từ từng chấm luân phiên, chu kỳ 2 giây, đứng yên khi bật giảm chuyển động), không khung, chỉ còn đường cắt ngang giữa số; giữa phía trên màn hình chính, ngay dưới hàng nút.
- **Hiệu ứng:** khi đổi số, nửa trên số cũ gập xuống rồi nửa dưới số mới rơi vào (2 × 0,3 giây). Chỉ chữ số vừa đổi mới lật (10:59→11:00 giữ nguyên số 1 đầu). Không có thẻ nền nên hai nửa tĩnh mờ dần ra/vào theo tấm lật, số cũ và mới không chồng lên nhau. Tắt khi máy bật giảm chuyển động.
- **Lớp:** `z-index: 1`, chỉ nằm trên orb; HUD, chat, bản đồ, Settings đều đè lên được. `pointer-events: none` nên không chặn click.
- **Font:** Oswald Light (300), nhúng vào bản build qua `@fontsource/oswald` (bộ latin) — app desktop chạy offline vẫn đúng font.
- **Test:** `frontend/e2e/clock.cjs` (giờ giả bằng `page.clock`: hiện 10:59, lật sang 11:00, dọn tấm lật, vị trí, lớp, font, mobile).

Thêm: sửa và lưu prompt (`POST /api/prompts/save`, chỉ ghi đè `prompt/*.md` có sẵn); Graphfy thành bản đồ luồng chạy thật. Test: `tests/test_settings_status_api.py`, `frontend/e2e/settings-dashboard.cjs`.

### v9.9.5 — 2026-09-25

**Gom prompt và learning tự phản tư.** Spec do Claude viết, một model khác lên plan và triển khai, rồi Claude review và sửa lại. Kết quả chạy thật: hiểu ngữ cảnh tốt hơn, phản hồi nhanh hơn, token giảm, dễ bảo trì.

| Vấn đề phát hiện khi review | Hậu quả | Cách sửa |
|---|---|---|
| Lịch sử từ DB chỉ lấy `role` và `content` | Thẻ `<ask_user>` không bao giờ được dựng lại | Giữ thêm cột `ask_user`/`action_run`, có test trên DB tạm |
| Lịch sử bỏ mọi lượt user trùng chữ | Mất lượt "ừ" cũ, ảnh hưởng cả gate | Chỉ gộp bản ghi trùng nằm liền nhau |
| `unlearn_last_learning` xoá bài học mới nhất mỗi khi ngài phàn nàn route sai | Mất dữ liệu | Thay bằng `retract` có kiểm soát |
| Prompt được chép sang `.md` nhưng code vẫn dùng chữ viết cứng | Sửa file `.md` không có tác dụng | Nối code vào file `.md`, kiểm bằng golden test |
| `learning_workflow.md` có schema đầu ra khác prompt thật | Sẽ làm hỏng việc học workflow | Viết lại theo đúng prompt đang chạy |
| Test learning ghi vào `data/` thật | Để lại rác trong `Evolution.md` | Test chạy trên thư mục tạm, script dọn gỡ rác |
| Sampling được đổi sau khi đo trên bố cục cũ | Đo lại 10 lần mỗi kịch bản, cấu hình mới tệ hơn | Giữ `0.4 / 0.8 / 40` |
| Script dọn sửa `STYLE.md` trước khi sao lưu, và model kia tự chạy `--apply` | Bản sao lưu thiếu `skills/self_evolution/` | Sao lưu trước mọi thay đổi |

**Sửa thêm sau khi chạy thật:**
- **Media phát nhầm video**: từ đệm "tôi muốn … của" kéo một video re-up lên đầu danh sách. Đã bỏ từ đệm trước khi xếp hạng. Bảng kết quả chép nguyên từ tool và nói đúng bài đang phát.
- **Classifier**: tên có gạch nối như "M-TP" được tính là một từ, nên câu rút gọn được nhận.
- **Chat bịa kết quả kiểm tra bảo mật** khi không có tool nào chạy: thêm `<tool_status>` cho mọi lượt chat. Đo lại: bịa 8/10 → 0/10, đề nghị đúng giao thức 10/10. Lượt từ chối không còn nói "đã mở rồi" (1/10). Đã gỡ các dữ liệu bịa khỏi DB và nhật ký wiki, có sao lưu trong `data/backups/`.

**Bài học khi giao việc cho model khác:**
- Test phải chạy qua đường code thật, không chỉ gọi hàm với dữ liệu giả.
- Test không được đụng `data/` thật.
- Thao tác `--apply` trên dữ liệu thật do người dùng tự chạy.
- Chỉ đo live trên đúng bố cục đang chạy, với đủ số lần chạy.
- Sửa prompt thì phải chứng minh nó giống từng byte với bản cũ, hoặc nói rõ là đã đổi.

## Kho tài liệu (`@rag`)

Tài liệu lưu vào kho được tìm lại bằng lệnh tường minh. Router bắt tiền tố `@rag` bằng regex, không qua LLM, nên không nhầm với câu chat hay lệnh khác.

- `@rag <câu hỏi>` — tìm trong kho (dense + BM25 + RRF + rerank), bỏ đoạn có `hybrid_score` < `RAG_MIN_SCORE` (mặc định `0.2`), LLM trả lời chỉ từ bằng chứng, kèm nguồn (tên tệp, trang). Nếu đang đính kèm tệp: hỏi về chính tệp đó.
- `@rag lưu` + đính kèm tệp — lưu vào kho lâu dài. Không có tệp thì "lưu…" được hiểu là câu hỏi.
- `@rag danh sách` — tài liệu trong kho và mã.
- `@rag xóa <mã>` — xóa khỏi kho. Chỉ nhận đúng một mã; `xóa` kèm nhiều từ được hiểu là câu hỏi.
- `@rag` — trợ giúp.

Tệp thả vào `data/documents/` (hoặc `RAG_WATCH_FOLDER`) cũng được watcher tự index vào cùng kho. Đổi model embedding thì phải index lại: vector của hai model không so được với nhau, và khác số chiều sẽ bị từ chối.

## Tìm việc (`@jobs`)

JARVIS phỏng vấn ngài để tạo hồ sơ + CV PDF tiếng Việt, tự tìm tin tuyển dụng **có email nhận CV** mỗi sáng (sau 08:00), soạn thư xin việc, và chỉ gửi qua Gmail khi ngài duyệt.

Cấu hình Gmail (một lần): bật Xác minh 2 bước, tạo "Mật khẩu ứng dụng" tại `myaccount.google.com/apppasswords`, rồi tự thêm vào `.env`:

    GMAIL_ADDRESS=ban@gmail.com
    GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx

Lệnh (giao diện hoặc Telegram):
- `@jobs phỏng vấn` / `@jobs tiếp tục` / `@jobs sửa hồ sơ`
- `@jobs tìm` — tìm ngay; `@jobs tin <nội dung hoặc link>` — đánh giá một tin
- Duyệt: `gửi 1, 3`, `bỏ 2`, `sửa thư 1: <ý muốn>` (danh sách hết hạn sau 3 ngày, tối đa 10 thư/ngày)
- `@jobs trạng thái`

Dữ liệu nằm trong `data/jobs/` (hồ sơ, CV, danh sách chờ, nhật ký đã gửi). Không nộp trên trang cần đăng nhập (TopCV, vLance, LinkedIn); không viết CV tiếng Anh; tin yêu cầu tiếng Anh cao hơn trình độ trong hồ sơ bị bỏ qua.

---

## 📜 Giấy Phép & Tuyên Bố Miễn Trừ

Phiên bản **JARVIS v9.9.5** là phiên bản phát triển cá nhân hóa dành cho **erikpuw**.

Dự án gốc bởi [Ethan](https://ethanplus.ai).

> **Disclaimer:** Đây là dự án fan hâm mộ độc lập, không liên kết với Marvel Entertainment, The Walt Disney Company, hoặc bất kỳ tổ chức thương mại nào liên quan. Tên và khái niệm JARVIS thuộc bản quyền của Marvel Entertainment.


