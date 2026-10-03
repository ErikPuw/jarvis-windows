# JARVIS

**Tiếng Việt** | [English](README.en.md)

**Just A Rather Very Intelligent System** — Trợ lý AI giọng nói tiếng Việt, với "bộ não" chạy ngay trên máy Windows của bạn.

> *"Thưa ngài, tôi có thể giúp gì cho ngài?"*

**Version:** xem file [`VERSION`](VERSION) (nguồn duy nhất) · [Nhật ký phiên bản](CHANGELOG.md)

![Màn hình chính của JARVIS: quả cầu hạt phản ứng theo âm thanh, đồng hồ và bảng telemetry](assets/screenshots/hud-main.webp)

## 🎯 JARVIS Làm Gì?

Bạn nói hoặc gõ bằng tiếng Việt, JARVIS hiểu và **làm việc thật** trên máy của bạn:

- 🎙️ **Trò chuyện bằng giọng nói** tiếng Việt, theo thời gian thực.
- 🖥️ **Điều khiển máy**: mở/đóng ứng dụng, đọc màn hình, dùng webcam, tạo và sửa tệp Word/Excel/PowerPoint.
- 🔎 **Tra cứu**: tin tức, thời tiết, giá vàng và tỷ giá, YouTube, luật Việt Nam.
- 📄 **Hỏi đáp trên tài liệu của bạn** (RAG).
- 🧠 **Nhớ và tự học** từ các cuộc trò chuyện, có bản chiếu sang Obsidian để bạn đọc lại.

**Chạy ở đâu?** LLM, embeddings và bộ nhớ chạy **trên máy bạn** (llama.cpp, SQLite). Nhận giọng (Web Speech API của Chrome), giọng đọc mặc định (Edge-TTS) và các tính năng tra cứu web cần internet.

**Cần gì để chạy?** Windows 10/11, Python 3.11+, Node.js 18+, Chrome, llama.cpp server (LLM và embeddings) và Redis. Chi tiết ở mục [Cài đặt và cấu hình](#-cài-đặt-và-cấu-hình).

**Xưng hô:** JARVIS tự xưng "tôi" và gọi người dùng là "ngài" (luật cứng trong [`prompt/identity.md`](prompt/identity.md); muốn đổi thì sửa file này và `prompt/user.md`). Tài liệu này gọi người đọc là "bạn".

> **Trạng thái:** dự án cá nhân, đang phát triển liên tục. Gặp lỗi hoặc có ý tưởng? Mở [issue](https://github.com/erikpuw/jarvis-windows/issues) (có mẫu sẵn).

## 📑 Mục Lục

1. [JARVIS Làm Gì?](#-jarvis-làm-gì)
2. [Tính Năng Nổi Bật](#-tính-năng-nổi-bật)
3. [Một Lượt Hội Thoại Chạy Thế Nào](#-một-lượt-hội-thoại-chạy-thế-nào)
4. [Prompt Tập Trung Một Nơi](#-prompt-tập-trung-một-nơi)
5. [Lời Đề Nghị, "ừ" và Chống Bịa](#-lời-đề-nghị-ừ-và-chống-bịa)
6. [16 Chuyên Viên Tác Vụ (Agents)](#-16-chuyên-viên-tác-vụ-agents)
7. [Tự Học, Tự Tiến Hóa, Dream, Tự Vá Lỗi](#-tự-học-tự-tiến-hóa-dream-tự-vá-lỗi)
8. [Bộ Nhớ, Memory Center và Obsidian Wiki](#️-bộ-nhớ-memory-center-và-obsidian-wiki)
9. [Giao Diện (Frontend)](#-giao-diện-frontend)
10. [Mở Rộng: Lệnh, Skill, Hook, MCP, Telegram](#-mở-rộng-lệnh-skill-hook-mcp-telegram)
11. [Công Cụ Nền Tảng: Cào Web và Điều Khiển Windows](#-công-cụ-nền-tảng-cào-web-và-điều-khiển-windows)
12. [Kho Tài Liệu (`@rag`)](#-kho-tài-liệu-rag)
13. [Tìm Việc (`@jobs`)](#-tìm-việc-jobs)
14. [Kiến Trúc Hệ Thống](#️-kiến-trúc-hệ-thống)
15. [Cài Đặt và Cấu Hình](#-cài-đặt-và-cấu-hình)
16. [API](#-api)
17. [Cấu Trúc Thư Mục](#-cấu-trúc-thư-mục)
18. [Kiểm Thử và Đo Đạc](#-kiểm-thử-và-đo-đạc)
19. [Bảo Mật](#-bảo-mật)
20. [Nhật Ký Phiên Bản](#-nhật-ký-phiên-bản)
21. [Giấy Phép & Tuyên Bố Miễn Trừ](#-giấy-phép--tuyên-bố-miễn-trừ)

---

## 🌟 Tính Năng Nổi Bật

### 🧱 Lõi — hội thoại và điều khiển máy

| Tính năng | Mô tả |
|-----------|-------|
| **LLM local** | Gemma 4 E4B-it QAT (profile đang dùng) hoặc Qwen3.5-9B, chạy qua llama.cpp tại `http://localhost:8080/v1`, xử lý được cả văn bản lẫn hình ảnh |
| **Embeddings local** | `nomic-embed-text-v1.5-q8_0` tại `http://localhost:8081/v1`, dùng cho RAG và bộ nhớ ngữ nghĩa |
| **Giọng nói tiếng Việt** | Nhận giọng bằng Web Speech API (`vi-VN`), có sửa lỗi nhận dạng. Đọc thành tiếng bằng Edge-TTS (`vi-VN-NamMinhNeural`) hoặc VieNeu streaming (port 8082); chỉ bật một trong hai |
| **Điều khiển Windows** | Agent `win_control` dùng cua-driver (UI Automation) điều khiển app chạy nền, không chiếm chuột; xác nhận trước mỗi thao tác đổi máy. Cách cài cua-driver: xem [chi tiết](#-công-cụ-nền-tảng-cào-web-và-điều-khiển-windows) |
| **Cào web** | Scrapling hai tầng: HTTP giả vân tay trình duyệt, dự phòng trình duyệt headless cho trang chống bot hoặc cần JavaScript. Dùng cho tin tức, giá sản phẩm, tìm việc, thời tiết |
| **Định tuyến 2 tầng** | Gate chỉ quyết định **trò chuyện hay làm việc**, không cần biết có những agent nào. Orchestrator chọn agent bằng native tool calling, có thể gọi nhiều agent nối tiếp nhau |
| **Lời đề nghị có kiểm soát** | Khi bạn chỉ trò chuyện, Jarvis đề nghị việc có thể làm bằng thẻ `<ask_user>`/`<action_run>`. Bạn đáp "ừ" thì code chạy đúng tool đã đề nghị, không cần LLM đoán lại |
| **Prompt tập trung** | Chữ của mọi prompt nằm trong `prompt/*.md`, code ghép prompt nằm trong `engine/prompts/` |
| **Chống bịa kết quả** | Mọi lượt chat đều có chỉ thị `<tool_status>` nói rằng ở lượt này không có công cụ nào chạy, nên chat không được tự nói "đã kiểm tra" hay nêu trạng thái hệ thống |
| **An ninh** | Guardrails chống prompt injection, firewall IP + kiểm tra Origin (chống CSRF/WebSocket hijacking) cho REST và WebSocket, theo dõi kết nối |

### 🧠 Trí nhớ và tự học

| Tính năng | Mô tả |
|-----------|-------|
| **HyperRAG** | Kết hợp Dense Vector, BM25 và Reciprocal Rank Fusion để tra cứu tài liệu local. Tự theo dõi thư mục `data/documents/` |
| **Bộ nhớ & Obsidian** | SQLite + FTS5 (`data/jarvis.db`) là nguồn gốc. Obsidian Vault (`data/wiki/`) là bản chiếu một chiều. Memory Center trong WebUI là nơi sửa duy nhất |
| **Tự học tự phản tư** | Mỗi lượt học gồm một lượt đề xuất và một lượt phản biện, rồi code chốt chặn. Có thể gỡ đúng điều vừa học (`retract`). Workflow chạy thành công được dùng lại khi câu lệnh khớp nguyên văn |
| **Dream Cycle** | Chạy lúc rảnh ban đêm để tóm tắt và dọn hội thoại, kết quả agent, wiki cũ. Luôn sao lưu trước khi gộp |
| **Self-Healing** | Quét log mỗi 60 giây, phân loại lỗi và ghi vào `Errors.md`. Chỉ nhờ Goose sửa code khi bạn đã duyệt |

### 🇻🇳 Tiện ích thêm (tùy chọn)

Mỗi tiện ích là một agent riêng trong `engine/agents/` (danh sách đầy đủ ở mục [16 chuyên viên tác vụ](#-16-chuyên-viên-tác-vụ-agents)):

- **Đời sống Việt Nam**: thời tiết, tin tức, giá vàng/xăng/tỷ giá, lịch vạn niên, cung hoàng đạo, lịch chiếu CGV, game miễn phí Epic, bản đồ và chỉ đường.
- **Giải trí**: nghe nhạc, YouTube, livestream.
- **Công việc**: email và lịch Outlook, ghi chú, `@jobs` tìm việc và soạn thư xin việc (chỉ gửi khi bạn duyệt).

---

## 🔀 Một Lượt Hội Thoại Chạy Thế Nào

`engine/router/decide.py` xét lần lượt từng bước dưới đây. Bước nào khớp thì dừng ở đó:

| # | Bước | Khi nào | Kết quả |
|---|------|---------|---------|
| 0 | `@plans` | Câu bắt đầu bằng `@plans <mục tiêu>`, ví dụ `@plans hôm nay không biết ăn gì` | Chế độ mục tiêu ([engine/plans](engine/plans)): lập kế hoạch tra cứu → gọi agent đọc (search/web/history) → lập lại khi cần → một kết luận. Chat **không** tự đề nghị chế độ này |
| 0b | `@rag` | Câu bắt đầu bằng `@rag` | Kho tài liệu lâu dài ([engine/rag](engine/rag)), xem mục "Kho tài liệu (`@rag`)". Chạy trước `@mention`, nên `@rag` không còn rơi vào agent RAG bắt buộc có tệp |
| 1 | `@mention` | Câu bắt đầu bằng `@desktop`, `@mail`… (danh bạ ở `prompt/tools.md`) | Gọi thẳng agent đó |
| 2 | Đáp lời đề nghị | Lượt trước Jarvis đã hỏi `<ask_user>`, giờ bạn đáp "ừ", "đồng ý", "không"… | Code chạy đúng tool trong `<action_run>`, không qua LLM |
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

- **Bạn chỉ trò chuyện**, ví dụ "tôi lười mở notepad quá": Jarvis trả lời rồi đề nghị
  `Ngài có muốn tôi <ask_user>mở Notepad</ask_user> không?<action_run>open_app</action_run>`.
  Bạn đáp "ừ" thì code chạy `open_app` ngay. Danh sách tool được phép đề nghị nằm ở cột `offer` trong `prompt/tools.md`.
- **Bạn nhờ rõ ràng**, ví dụ "bạn mở notepad giúp tôi": Jarvis làm luôn, không hỏi lại.
- **Chống bịa**:
  - Lượt chat thường luôn có `<tool_status>` với nội dung "ở lượt này không có công cụ nào chạy": không nói đã làm, không nêu kết quả hay trạng thái; cần dữ liệu thật thì đề nghị.
  - Lượt agent từ chối có `<tool_status>` với nội dung "chưa làm được": không dựa vào lịch sử để nói "đã … rồi".
- **Media**: trước khi xếp hạng kết quả YouTube, bỏ các từ đệm của câu nói tự nhiên ("tôi muốn … của …"). Bảng kết quả chép nguyên từ tool, và câu trả lời nói đúng tên bài **đang phát**.

---

## 🤖 16 Chuyên Viên Tác Vụ (Agents)

Các agent đăng ký trong `engine/orchestrator/registry.py`, mã nguồn ở `engine/agents/`.

| Agent | Chức năng chính |
|-------|-----------------|
| **desktop** | Mở/đóng ứng dụng Windows, giữ đúng tên gốc ứng dụng |
| **search** | Thời tiết, tin tức, giá vàng/xăng/tỷ giá, lịch vạn niên, cung hoàng đạo, lịch chiếu CGV, game miễn phí Epic, bản đồ và chỉ đường |
| **media** | Nghe nhạc, xem YouTube, livestream (phát ngay trong giao diện) |
| **notes** | Ghi, xem, xoá ghi chú |
| **vision** | Chụp và phân tích màn hình bằng LLM Vision |
| **webcam** | Chụp và phân tích khung hình webcam |
| **office** | Tạo/sửa tệp Word, Excel, PowerPoint đính kèm (skill `officecli`) |
| **rag** | Đọc, tóm tắt, hỏi đáp trên tệp đính kèm hoặc tài liệu đã index |
| **security** | Kiểm tra an ninh mạng, cổng, firewall |
| **email** | 10 email gần nhất và lịch hẹn 7 ngày tới trong Outlook |
| **history** | Xem lại lịch sử trò chuyện |
| **image** | Tăng độ phân giải ảnh bằng Upscayl |
| **project** | Kiểm tra dự án code, quét lỗi cú pháp |
| **goose** | Mở giao diện Goose để bạn tự thao tác |
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

Tất cả chạy nền khi hệ thống rảnh, không làm chậm lượt trò chuyện. Nếu bạn chat tiếp, tác vụ nền đang chạy nhường chỗ và chạy lại sau.

### 📖 Learning tự phản tư ([learning.py](engine/core/learning.py))

1. **Đề xuất** (`learning_propose.md`): model đọc 3–5 lượt gần nhất trong DB và các kết quả agent thành công, rồi đề xuất tối đa 2 mục. Mỗi mục có `kind` là một trong `user_fact`, `preference`, `behaviour_lesson`, `routing_note`.
2. **Phản biện** (`learning_critique.md`): model đặt mỗi đề xuất cạnh mục cũ gần nhất, rồi quyết định `skip`, `merge`, `replace` hoặc `new`.
3. **Code chốt chặn**:
   - Bằng chứng phải khớp nguyên văn hội thoại; với `user_fact`/`preference`, phải nằm trong lời của bạn.
   - Không học trạng thái nhất thời ("lười", "mệt").
   - Luật hành vi không được bàn chuyện hỏi, xin phép, công cụ, agent hay thẻ.
   - `merge`/`replace` chỉ được đụng đúng mục cũ đã đưa cho model xem.
4. **Gỡ bài học**: nếu bạn phủ nhận đúng điều vừa học, lượt học kế tiếp đề xuất `retract`. Code chỉ hoàn tác được mục do chính lượt học trước ghi: mục mới thì xoá, mục đã gộp thì trả về nội dung cũ.
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
- Với lỗi code, Jarvis **xin bạn duyệt** trên phiên WebUI trước khi nhờ Goose CLI sửa đúng một tệp. Không có phiên để duyệt thì không sửa.

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

Xây dựng bằng **Vite + TypeScript + Three.js**, phong cách Dark-Tech Glassmorphism.

<p align="center"><img src="assets/screenshots/mobile.webp" alt="JARVIS trên điện thoại: khung các bước xử lý 8/8 và câu trả lời" width="260"></p>

*Trên điện thoại: khung các bước xử lý hiện từng bước (guardrail, định tuyến, LLM, TTS) rồi mới đến câu trả lời.*

![Graphfy: bản đồ module tự sinh từ code](assets/screenshots/graphfy.webp)

*Graphfy trong Settings: bản đồ module tự sinh từ code, đường tím là chỗ gọi LLM.*

![Graphfy khi rê chuột: chỉ giữ các đường của một module](assets/screenshots/graphfy-focus.webp)

*Rê chuột vào một khối để chỉ giữ lại các đường liên quan đến nó.*

Mã nguồn ở `frontend/src/`:

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
- **2 skill** trong `skills/`: `officecli`, `self_evolution`.
- **Hook & plugin**: các sự kiện `on_startup`, `on_shutdown`, `ON_MESSAGE_RECEIVE`, `ON_RESPONSE_GENERATE`, nạp plugin `.py`/`.ts` động.
- **Tự cài extension** (`install_extension`): nạp nóng plugin/skill/hook mới từ URL hoặc code, không cần khởi động lại.
- **MCP** (`config/mcp_config.json`): `wikipedia-mcp` (bật sẵn); `gitnexus`, `headroom`, `codebase-memory-mcp` (có cấu hình, mặc định tắt). Scrapling và cua-driver **không** phải MCP server: JARVIS gọi trực tiếp, xem [Công cụ nền tảng](#-công-cụ-nền-tảng-cào-web-và-điều-khiển-windows).
- **Command Bar**: `/tên_lệnh <tham số>` chạy lệnh trong `commands/` (gõ `/tên_lệnh` trống để JARVIS hỏi từng tham số); `@agent câu lệnh` gọi thẳng agent (bước 1 của router). Trang Commands và Agents trong Settings ghi đúng cú pháp này.
- **Telegram Bot**: điều khiển từ xa, xác thực Chat ID. Lệnh `/agents` đọc danh bạ từ `prompt/tools.md`.

---

## 🔧 Công Cụ Nền Tảng: Cào Web và Điều Khiển Windows

Hai thành phần này JARVIS gọi **trực tiếp từ code**, không đi qua MCP Hub và không nằm trong `config/mcp_config.json`.

### Cào dữ liệu web (Scrapling)

Mã nguồn: [`engine/tools/browser.py`](engine/tools/browser.py). Dùng Scrapling thay cho Playwright thuần, theo hai tầng:

| Tầng | Cách chạy | Khi nào dùng |
|------|-----------|--------------|
| `AsyncFetcher` | Yêu cầu HTTP giả vân tay TLS và header của trình duyệt, không mở trình duyệt | Mặc định: nhanh và nhẹ |
| `StealthyFetcher` | Trình duyệt headless (Patchright), hướng tới vượt trang chống bot như Cloudflare | Dự phòng khi tầng 1 bị chặn, hoặc trang cần JavaScript mới ra nội dung (vd. trang liệt kê sản phẩm) |

- `StealthyFetcher` ưu tiên Edge/Chrome đã cài sẵn trên máy, không dùng bản "Chrome for Testing" đi kèm (bản đó có thể không khởi động được trên một số máy Windows).
- Nơi dùng: tin tức (Google News RSS, DuckDuckGo), giá sản phẩm ở các trang bán lẻ đã duyệt (`shop_engine`), tra cứu của `@plans` (`web_research`), tìm tin tuyển dụng (`@jobs`), thời tiết.
- Kết quả tool được lọc các dòng nghi prompt injection trước khi vào prompt (`scrub_untrusted`, xem mục [Bảo mật](#-bảo-mật)).

### Điều khiển Windows (cua-driver)

Agent `win_control` ([`engine/tools/windows_control.py`](engine/tools/windows_control.py)) điều khiển ứng dụng Windows chạy nền, không chiếm chuột và bàn phím, bằng [cua-driver](https://github.com/trycua/cua). cua-driver đọc cây giao diện qua UI Automation (UIA); JARVIS thao tác theo `element_index`, không bấm theo toạ độ.

**Cài cua-driver** (PowerShell, một lần):

```powershell
irm https://cua.ai/driver/install.ps1 | iex
```

JARVIS tìm `cua-driver.exe` theo thứ tự: biến `CUA_DRIVER_PATH` → `PATH` → `%LOCALAPPDATA%\Programs\Cua\cua-driver\bin`. Chưa cài thì lệnh `win_control` báo "chưa tìm thấy cua-driver".

- **Cách gọi**: mỗi lệnh, JARVIS bật một tiến trình `cua-driver mcp` (nói chuyện qua stdio, khởi động khoảng 0,2 giây, không cần daemon hay Docker) rồi đóng lại. Đây là kết nối trực tiếp của code, **không** phải MCP server trong `config/mcp_config.json`.
- **Cách chạy**: LLM đang dùng chọn từng bước dưới dạng JSON, chỉ dùng chữ (không cần vision). Tối đa `CUA_MAX_STEPS` bước mỗi lệnh (mặc định 12).
- **An toàn**: mặc định (`CUA_CONFIRM=each`) hỏi xác nhận trước mỗi thao tác làm thay đổi máy; nút có nhãn Delete/Uninstall/Xóa… luôn hỏi dù đặt `off`. Chỉ cho phép các tool nhắm vào phần tử theo `element_index` và một tiến trình cụ thể: không có bấm theo toạ độ x/y, không nhập chữ vào cả màn hình.
- **Phần cua-driver không thấy**: taskbar và Start/Search menu đi qua `pywinauto` (UIA). Phóng to/thu nhỏ/khôi phục cửa sổ cũng qua `pywinauto`, có đọc lại để xác minh.
- Mở/đóng ứng dụng theo tên là việc của agent `desktop` (PowerShell + Start Menu), tách với `win_control`.

---

## 📚 Kho Tài Liệu (`@rag`)

Tài liệu lưu vào kho được tìm lại bằng lệnh tường minh. Router bắt tiền tố `@rag` bằng regex, không qua LLM, nên không nhầm với câu chat hay lệnh khác.

- `@rag <câu hỏi>` — tìm trong kho (dense + BM25 + RRF + rerank), bỏ đoạn có `hybrid_score` < `RAG_MIN_SCORE` (mặc định `0.2`), LLM trả lời chỉ từ bằng chứng, kèm nguồn (tên tệp, trang). Nếu đang đính kèm tệp: hỏi về chính tệp đó.
- `@rag lưu` + đính kèm tệp — lưu vào kho lâu dài. Không có tệp thì "lưu…" được hiểu là câu hỏi.
- `@rag danh sách` — tài liệu trong kho và mã.
- `@rag xóa <mã>` — xóa khỏi kho. Chỉ nhận đúng một mã; `xóa` kèm nhiều từ được hiểu là câu hỏi.
- `@rag` — trợ giúp.

Tệp thả vào `data/documents/` (hoặc `RAG_WATCH_FOLDER`) cũng được watcher tự index vào cùng kho. Đổi model embedding thì phải index lại: vector của hai model không so được với nhau, và khác số chiều sẽ bị từ chối.

## 💼 Tìm Việc (`@jobs`)

JARVIS phỏng vấn bạn để tạo hồ sơ + CV PDF tiếng Việt, tự tìm tin tuyển dụng **có email nhận CV** mỗi sáng (sau 08:00), soạn thư xin việc, và chỉ gửi qua Gmail khi bạn duyệt.

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
┌── engine/agents (16) ──┐  ┌── engine/tools ───────────────┐  ┌── engine/core ─────────────┐
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
- Tùy chọn: [cua-driver](https://github.com/trycua/cua) cho agent `win_control`. Cài bằng PowerShell: `irm https://cua.ai/driver/install.ps1 | iex` (xem [chi tiết](#-công-cụ-nền-tảng-cào-web-và-điều-khiển-windows)).

### Lưu ý khi tải về

- **Một số tính năng đã gỡ** khỏi bản công khai: tra cứu văn bản pháp luật, phân tích Vietlott, tra cứu đơn vị hành chính (tỉnh/thành, phường/xã). Hiện còn 16 agent.
- **officecli**: skill `skills/officecli` chỉ chứa hướng dẫn dùng. Hãy cài officecli từ mã nguồn gốc và lấy thư mục `examples/` (ví dụ Word/Excel/PowerPoint) từ đó, thay cho bản sao trong repo này.
- **Goose**: agent `goose` chỉ mở giao diện Goose (Windows GUI) và, khi bạn duyệt, nhờ Goose CLI sửa một tệp. Cần cài Goose CLI và Goose cho Windows. Không dùng thì bỏ qua, hoặc thay bằng công cụ khác bạn quen (xoá agent trong `engine/orchestrator/registry.py`, `skills/agents/goose/` và `commands/` liên quan).
- **Dùng model lớn (Claude, Gemini, ChatGPT)**: đổi `LOCAL_URL`, `LOCAL_API_KEY`, `LOCAL_MODEL` trong `.env` sang endpoint tương thích OpenAI của nhà cung cấp. Nếu API của họ khác định dạng OpenAI, cần chỉnh hoặc viết lại [`engine/server/llm_server.py`](engine/server/llm_server.py) (cách gọi, tham số, stream). Prompt trong `prompt/` được tinh chỉnh cho model local nhỏ, model lớn có thể cần chỉnh lại.
- **Test có thể lỗi trên máy bạn**: một số test phụ thuộc dịch vụ ngoài (llama.cpp, Redis, `bsdtar`, mạng). Sau khi tải về hãy chạy `python -m pytest tests -q --ignore=tests/live --ignore-glob="tests/test_live_*"` và kiểm tra lại các test lỗi trước khi sửa code.

- **Dự án viết thuần tiếng Việt**: prompt, giọng đọc, nhận dạng giọng nói và nguồn dữ liệu đều theo tiếng Việt. Dùng ngôn ngữ khác thì xem mục [Đổi ngôn ngữ và giọng nói](#đổi-ngôn-ngữ-và-giọng-nói) ngay bên dưới.

#### Đổi ngôn ngữ và giọng nói

1. **Giọng đọc (TTS)**. Mặc định Edge TTS (`vi-VN-NamMinhNeural`).
   - Đổi sang ngôn ngữ khác trong `.env`: `TTS_LOCAL_MODEL=en-US-GuyNeural` (danh sách giọng: `edge-tts --list-voices`). Giữ `EDGE_TTS_ENABLED=true`, `VIENEU_TTS_ENABLED=false`, vì VieNeu chỉ đọc tiếng Việt.
   - Muốn dịch vụ mạnh hơn (ElevenLabs, OpenAI TTS, Azure, Google...): viết thêm một engine trong `engine/server/` theo mẫu `tts_engine.py` và đăng ký ở `tts_manager.py` (đọc `TTS_ENGINE`). Dịch vụ nên trả âm thanh từng câu để `voice_streamer.py` phát liên tục.
2. **Nhận dạng giọng nói (STT)**: `engine/server/whisper_server.py` đang cố định `language="vi"`. Đổi mã ngôn ngữ (vd `"en"`) hoặc bỏ tham số để Whisper tự nhận.
3. **Prompt**: toàn bộ prompt nằm trong `prompt/*.md`. Ưu tiên chỉnh `identity.md`, `soul.md`, `user.md`, `style_lock.md`, `voice_cues.md`, `persona_short.md`. Các prompt này đang yêu cầu trả lời tiếng Việt và xưng hô "tôi - ngài". Thêm chỉ dẫn rõ ràng cho model ở đầu `identity.md`, ví dụ:
   ```
   Ngôn ngữ của người dùng là English. Luôn trả lời bằng English, kể cả khi dữ liệu công cụ trả về tiếng Việt.
   Xưng hô: gọi người dùng là "sir", tự xưng "I". Câu ngắn, tự nhiên, phù hợp để đọc thành tiếng.
   ```
   Sau khi sửa, chạy lại test: nhiều test so prompt với bản mẫu trong `tests/golden/`, cần cập nhật các file này theo prompt mới.
4. **Dữ liệu và từ khoá tiếng Việt**: tin tức, thời tiết, giá vàng/xăng, lịch vạn niên, từ khoá chọn agent (`engine/agents/`) và tên lệnh trong `commands/` đều theo tiếng Việt/Việt Nam. Đổi ngôn ngữ thì các phần này cần xem lại, hoặc tắt các lệnh không dùng.

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
| `USER_NAME` / `HONORIFIC` | (trống) | Chỉ được trang Settings lưu và hiển thị. Cách JARVIS xưng hô khi trò chuyện ("tôi" – "ngài") nằm ở `prompt/identity.md` và `prompt/user.md`, không lấy từ hai biến này |
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
| Media | `/api/media/search`, `/api/media/resolve`, `/api/media/local/{path}` |
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
├── skills/                # officecli, self_evolution (STYLE.md)
├── config/                # mcp_config.json
├── scripts/               # cleanup_learning_2026_09.py (mặc định chỉ xem, --apply mới dọn)
├── data/                  # jarvis.db, wiki/ (Obsidian), documents/, backups/, dream_archive/
├── docs/superpowers/      # specs/, plans/, reports/ (tài liệu nội bộ, không đưa lên repo)
├── engine/
│   ├── router/            # decide, gate, replay, ask_user, fast_paths, dispatch, chat
│   ├── orchestrator/      # classifier, dispatcher, synthesizer, registry
│   ├── prompts/           # ghép prompt: persona, chat, router, results, learning, catalog
│   ├── agents/            # 16 agent
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
- **CI** (`.github/workflows/ci.yml`, chạy mỗi lần push `main` và mỗi PR): `ruff check .` (rule trong `ruff.toml`), compile toàn bộ Python, `python .github/scripts/check_imports.py` (mọi `from engine... import X` phải trỏ tới tên có thật), `pytest` (cài `requirements-ci.txt`, bộ thư viện nhẹ cộng `bsdtar`; bỏ qua `tests/live/` và `tests/test_live_*.py` vì cần llama-server thật), và `npm run build` cho frontend. Chạy lại các lệnh này trước khi push để khỏi đỏ CI.
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
- Sau khi một agent đọc nội dung ngoài (`search`, `media`, `rag`), `next_tasks` chặn mọi bước điều khiển máy tiếp theo (`win_control`, `desktop`, `goose`); các bước khác (vd. `notes`, `office`) vẫn chạy bình thường.
- **Kiểm tra Origin** (`engine/security/policy.py`, `firewall.py`): firewall IP không chặn được trang web độc hại mở trên chính máy này (request đi từ loopback). Trình duyệt luôn gửi `Origin` cho WebSocket và cho POST/PUT/DELETE khác origin, nên `/ws/voice` và mọi request ghi đều bị từ chối trừ khi origin cùng host hoặc nằm trong `JARVIS_CORS_ORIGINS`. Client không phải trình duyệt (Telegram, httpx, curl) không gửi `Origin` nên không bị ảnh hưởng.

---

## 📝 Nhật Ký Phiên Bản

Toàn bộ lịch sử thay đổi và quy tắc đánh số phiên bản nằm ở [CHANGELOG.md](CHANGELOG.md). Số phiên bản hiện tại: file [`VERSION`](VERSION).

---

## 📜 Giấy Phép & Tuyên Bố Miễn Trừ

Đây là bản phát triển cá nhân hóa dành cho **erikpuw**.

Dự án gốc bởi [Ethan](https://ethanplus.ai).

> **Disclaimer:** Đây là dự án fan hâm mộ độc lập, không liên kết với Marvel Entertainment, The Walt Disney Company, hoặc bất kỳ tổ chức thương mại nào liên quan. Tên và khái niệm JARVIS thuộc bản quyền của Marvel Entertainment.


