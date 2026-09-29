"""
JARVIS Note Engine - Ghi chú cá nhân và Knowledge Base được đồng bộ trực tiếp với Obsidian Vault (data/wiki).
"""

import time
import logging
import re
import unicodedata
from pathlib import Path
from typing import Optional

log = logging.getLogger("jarvis.note_engine")

# Quy tắc định dạng cho LLM vòng 2 — bàn giao từ actions.py cho tool sở hữu
SUMMARY_RULES: dict[str, str] = {
    "read_note": (
        "QUY TẮC ĐỊNH DẠNG ĐỌC GHI CHÚ BẮT BUỘC:\n"
        "- Khi hiển thị nội dung chi tiết ghi chú, hãy trích xuất 100% TOÀN BỘ NỘI DUNG ĐẦY ĐỦ của tệp ghi chú, TUYỆT ĐỐI KHÔNG TÓM TẮT hay cắt bớt.\n"
        "- Giữ nguyên các nội dung ghi chú gốc, trình bày gọn gàng."
    ),
    "take_note": (
        "QUY TẮC ĐỊNH DẠNG GHI CHÚ BẮT BUỘC:\n"
        "- Hiển thị thông báo trạng thái thao tác ghi chú (Lưu/Xóa/Tìm thấy) một cách rõ ràng, súc tích.\n"
        "- Khi hiển thị danh sách ghi chú, sử dụng định dạng danh sách có mã ID `[ID: N]` đứng đầu dòng để ngài dễ tra cứu.\n"
        "- Giữ nguyên các nội dung ghi chú gốc, trình bày gọn gàng."
    ),
}

WIKI_DIR = Path(__file__).parent.parent.parent / "data" / "wiki"
TOPICS_DIR = WIKI_DIR / "topics"
NOTES_INDEX_PATH = TOPICS_DIR / "Danh sách ghi chú.md"

def ensure_topics_dir():
    TOPICS_DIR.mkdir(parents=True, exist_ok=True)

def _sync_notes_index() -> None:
    ensure_topics_dir()
    index_path = NOTES_INDEX_PATH.resolve()
    note_names = sorted(
        (
            note_path.stem
            for note_path in TOPICS_DIR.glob("*.md")
            if note_path.resolve() != index_path
        ),
        key=str.casefold,
    )
    links = [f"[[{note_name}]]" for note_name in note_names]
    content = "\n".join(links) + ("\n" if links else "")
    if NOTES_INDEX_PATH.exists() and NOTES_INDEX_PATH.read_text(encoding="utf-8") == content:
        return
    NOTES_INDEX_PATH.write_text(content, encoding="utf-8")

FILLER_PREFIX_REGEX = re.compile(
    r'^(chào\s+(ngài|bạn|anh|chị|sếp)|dạ\s+(ngài|bạn|anh|chị)|thưa\s+ngài|tôi\s+đã|dưới\s+đây\s+là|đây\s+là|kết\s+quả|tóm\s+tắt|tổng\s+hợp|phản\s+hồi|các)[\s\,\:\-\–]*',
    re.IGNORECASE
)

def clean_title_prefix(title: str) -> str:
    """Loại bỏ các cụm từ giao tiếp / xưng hô xã giao thừa ở đầu tiêu đề."""
    if not title:
        return title
    
    prev = None
    curr = title.strip()
    while prev != curr:
        prev = curr
        curr = FILLER_PREFIX_REGEX.sub('', curr).strip()
        curr = re.sub(r'^[,\:\-\–\.\s]+', '', curr).strip()
        
    if curr and len(curr) > 1:
        curr = curr[0].upper() + curr[1:]
        
    return curr if curr else title.strip()

def safe_filename(title: str) -> str:
    """Chuyển đổi tiêu đề thành tên file an toàn với chuẩn Tiếng Việt không dấu và loại bỏ từ xã giao."""
    if not title:
        return "general"
    
    title = clean_title_prefix(title)
    
    # Chuyển đ / Đ thành d / D
    title = title.replace('đ', 'd').replace('Đ', 'D')
    
    # NFD decomposition & remove combining diacritical marks (Mn)
    nfd_form = unicodedata.normalize('NFD', title)
    title_ascii = "".join([c for c in nfd_form if unicodedata.category(c) != 'Mn'])
    
    # Lowercase & regex clean non-alphanumeric ASCII
    title_ascii = title_ascii.lower()
    title_clean = re.sub(r'[^a-z0-9_\-\s]', '', title_ascii)
    title_clean = re.sub(r'\s+', '_', title_clean).strip('_')
    
    # Cắt gọn độ dài tối đa 60 ký tự
    if len(title_clean) > 60:
        title_clean = title_clean[:60].rstrip('_')
        
    return title_clean if title_clean else "general"

class NoteEngine:
    def __init__(self):
        ensure_topics_dir()

    def save_note(self, content: str, title: str = "", tags: str = "") -> str:
        """
        Lưu ghi chú trực tiếp thành file Markdown trong thư mục data/wiki/topics/.
        Trả về tên định danh (slug) của ghi chú.
        """
        ensure_topics_dir()
        content = content.strip()
        if not content:
            raise ValueError("Nội dung ghi chú không được để trống.")
        
        if not title:
            first_line = content.splitlines()[0].strip()
            # Loại bỏ các ký tự Markdown ở tiêu đề
            first_line = re.sub(r'^[#\s\-*]+', '', first_line)
            title = clean_title_prefix(first_line[:60]) if first_line else "Ghi chú"
        else:
            title = clean_title_prefix(title)
            
        slug = safe_filename(title)
        note_file = TOPICS_DIR / f"{slug}.md"
        
        now = time.time()
        date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        
        # Tạo cấu trúc YAML Frontmatter cho Obsidian
        frontmatter_tags = [t.strip().lower() for t in tags.split(",") if t.strip()]
        if "topic" not in frontmatter_tags:
            frontmatter_tags.append("topic")
        
        tags_str = ", ".join(frontmatter_tags)
        
        # Chuẩn bị nội dung file markdown
        # Nếu file đã tồn tại, ta có thể ghi đè hoặc bổ sung. Ở đây là ghi đè hoặc ghi đè có tiêu đề chuẩn.
        md_content = (
            f"---\n"
            f"title: \"{title}\"\n"
            f"tags: [{tags_str}]\n"
            f"created: {date_str}\n"
            f"updated: {date_str}\n"
            f"---\n\n"
            f"# {title}\n\n"
            f"{content}\n"
        )
        
        try:
            note_file.write_text(md_content, encoding="utf-8")
            _sync_notes_index()
            log.info(f"Obsidian Note saved: {note_file.name}")
            
            # Kích hoạt quét đồng bộ nóng sang Semantic Memory
            try:
                from engine.core.wiki_sync import sync_wiki_to_semantic_memory
                sync_wiki_to_semantic_memory()
            except Exception as sync_err:
                log.warning(f"Failed to sync wiki on save: {sync_err}")
                
            return slug
        except Exception as e:
            log.error(f"Failed to save obsidian note {slug}: {e}")
            raise

    def update_note(self, slug: str, content: str, title: str = "", tags: str = "") -> bool:
        """Cập nhật ghi chú markdown hiện có."""
        slug = safe_filename(slug)
        note_file = TOPICS_DIR / f"{slug}.md"
        if not note_file.exists():
            log.warning(f"Note not found to update: {slug}")
            return False
            
        # Nếu không cung cấp tiêu đề mới, giữ tiêu đề cũ từ nội dung/frontmatter
        if not title:
            title = slug.replace("_", " ").title()
            
        return bool(self.save_note(content, title, tags))

    def delete_note(self, slug: str) -> bool:
        """Xóa file markdown ghi chú."""
        slug = safe_filename(slug)
        note_file = TOPICS_DIR / f"{slug}.md"
        if note_file.exists():
            try:
                note_file.unlink()
                _sync_notes_index()
                log.info(f"Obsidian Note deleted: {note_file.name}")
                
                # Đồng bộ lại sau khi xóa
                try:
                    from engine.core.wiki_sync import sync_wiki_to_semantic_memory
                    sync_wiki_to_semantic_memory()
                except Exception as sync_err:
                    log.warning(f"Failed to sync wiki on delete: {sync_err}")
                return True
            except Exception as e:
                log.error(f"Failed to delete note {slug}: {e}")
                return False
        return False

    def get_note(self, slug: str) -> Optional[dict]:
        """Đọc và phân tích file Markdown ghi chú."""
        slug = safe_filename(slug)
        note_file = TOPICS_DIR / f"{slug}.md"
        if not note_file.exists():
            return None
            
        try:
            text = note_file.read_text(encoding="utf-8")
            # Tách frontmatter và content đơn giản
            title = slug.replace("_", " ").title()
            content = text
            tags = "topic"
            
            # Phân tích YAML cơ bản
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    yaml_block = parts[1]
                    content = parts[2].strip()
                    
                    title_match = re.search(r'title:\s*"(.*?)"', yaml_block)
                    if title_match:
                        title = title_match.group(1)
                        
                    tags_match = re.search(r'tags:\s*\[(.*?)\]', yaml_block)
                    if tags_match:
                        tags = tags_match.group(1)
            
            # Loại bỏ tiêu đề # Title trùng lặp ở phần đầu content
            content_cleaned = re.sub(r'^#\s+.*?\n+', '', content).strip()
            
            # Lấy thời gian thay đổi file
            stat = note_file.stat()
            
            return {
                "id": slug,
                "title": title,
                "content": content_cleaned,
                "tags": tags,
                "created_at": stat.st_ctime,
                "updated_at": stat.st_mtime
            }
        except Exception as e:
            log.error(f"Error reading note {slug}: {e}")
            return None

    def search_notes(self, query: str, limit: int = 5) -> list:
        """Tìm kiếm ghi chú markdown chứa từ khóa."""
        ensure_topics_dir()
        query_lower = query.lower().strip()
        if not query_lower:
            return self.list_notes(limit=limit)
            
        results = []
        for file in TOPICS_DIR.glob("*.md"):
            try:
                content = file.read_text(encoding="utf-8")
                if query_lower in content.lower() or query_lower in file.name.lower():
                    slug = file.stem
                    note_info = self.get_note(slug)
                    if note_info:
                        results.append(note_info)
            except Exception as e:
                log.warning(f"Error searching file {file}: {e}")
                
        # Sắp xếp theo ngày cập nhật mới nhất
        results.sort(key=lambda x: x["updated_at"], reverse=True)
        return results[:limit]

    def list_notes(self, limit: int = 10, tag: Optional[str] = None) -> list:
        """Liệt kê danh sách các ghi chú dưới dạng Markdown."""
        ensure_topics_dir()
        results = []
        for file in TOPICS_DIR.glob("*.md"):
            slug = file.stem
            note_info = self.get_note(slug)
            if note_info:
                if tag:
                    if tag.lower() in note_info["tags"].lower():
                        results.append(note_info)
                else:
                    results.append(note_info)
                    
        results.sort(key=lambda x: x["updated_at"], reverse=True)
        return results[:limit]

    def count(self) -> int:
        """Đếm số lượng ghi chú trong thư mục topics."""
        ensure_topics_dir()
        return len(list(TOPICS_DIR.glob("*.md")))


_note_engine: Optional[NoteEngine] = None

def get_note_engine() -> NoteEngine:
    global _note_engine
    if _note_engine is None:
        _note_engine = NoteEngine()
    return _note_engine


async def execute_note_action(arguments: dict, conversation_history: list = None, prev_results: str = "", user_text: str = "") -> str:
    """Xử lý ghi chú Obsidian (lưu, tìm, đọc) dựa trên tham số và lịch sử hội thoại."""
    import asyncio
    note_eng = get_note_engine()
    
    raw_text = arguments.get("user_text") or arguments.get("query") or user_text or ""
    raw_text_clean = re.sub(r"^/(take_note|note)\s*", "", raw_text, flags=re.IGNORECASE).strip()
    t_lower = raw_text_clean.lower()
    
    action = arguments.get("action", "").lower().strip()
    
    # 3. Xóa ghi chú -> Hướng dẫn xóa tại UI Settings
    if action == "delete" or any(kw in t_lower for kw in ["xóa ghi chú", "delete note"]):
        return "Thao tác xóa ghi chú không hỗ trợ qua lệnh tự động để bảo vệ an toàn dữ liệu. Ngài vui lòng thực hiện xem và xóa ghi chú trực tiếp tại Memory Control Center trong phần Settings (Cài đặt) của hệ thống."

    # 1. Danh sách ghi chú
    is_list_intent = not raw_text_clean or any(kw in t_lower for kw in [
        "danh sách ghi chú", "danh sách note", "list note", "hiện ghi chú", "tất cả ghi chú", "xem tất cả", "xem danh sách"
    ]) or t_lower in ["xem ghi chú", "đọc lại ghi chú", "xem lại ghi chú", "kiểm tra ghi chú", "coi ghi chú"]

    # 4. Đọc ghi chú số ID / từ khóa
    is_read_intent = any(kw in t_lower for kw in ["đọc ghi chú", "xem chi tiết ghi chú", "đọc note", "nội dung ghi chú", "đọc ghi chú số"]) or (
        any(kw in t_lower for kw in ["đọc", "xem", "chi tiết"]) and any(kw in t_lower for kw in ["ghi chú", "note"])
    )

    # 2. Ghi chú thông tin vừa tìm được / Lưu thông tin
    is_save_intent = any(kw in t_lower for kw in [
        "vừa tìm được", "vừa tìm", "bạn vừa nói", "câu vừa rồi", "phản hồi trước", 
        "câu nói vừa rồi", "câu vừa nói", "lưu lại kết quả", "lưu thông tin vừa", "lưu thông tin", "ghi chú thông tin"
    ])

    if not action or action in ["save", "search", "read"]:
        if is_list_intent and not is_save_intent:
            action = "search"
            arguments["query"] = ""
        elif is_read_intent and not is_save_intent:
            action = "search"
            for prefix in ["đọc ghi chú số", "đọc ghi chú", "xem chi tiết ghi chú", "đọc note", "xem ghi chú"]:
                idx = t_lower.find(prefix)
                if idx != -1:
                    arguments["query"] = raw_text_clean[idx + len(prefix):].strip()
                    break
            if "query" not in arguments:
                arguments["query"] = raw_text_clean
        elif is_save_intent:
            action = "save"
        else:
            if not raw_text_clean or t_lower in ["take_note", "note"]:
                action = "search"
                arguments["query"] = ""
            else:
                action = "save"
                content = raw_text_clean
                for prefix in ["ghi chú:", "ghi chú ", "note:", "nhớ cho tôi", "nhớ cho", "lưu lại", "lưu ghi chú"]:
                    idx = t_lower.find(prefix)
                    if idx != -1:
                        content = raw_text_clean[idx + len(prefix):].strip()
                        break
                arguments["content"] = content

    if action == "save":
        content = arguments.get("content", "").strip()
        if not content and raw_text_clean:
            content = raw_text_clean
            
        title = arguments.get("title", "").strip()
        tags = arguments.get("tags", "").strip()
        
        content.lower()
        
        if is_save_intent:
            if prev_results:
                cleaned_prev = re.sub(r"^Kết quả công cụ \w+:\n", "", prev_results, flags=re.IGNORECASE)
                content = cleaned_prev.strip()
            elif conversation_history:
                last_assistant_msg = None
                for msg in reversed(conversation_history):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        if "### Kết quả" not in msg["content"] and "Lỗi chạy agent" not in msg["content"]:
                            last_assistant_msg = msg["content"]
                            break
                if last_assistant_msg:
                    content = last_assistant_msg

        if content and content.lower() not in ["/take_note", "/note", "take_note", "note"]:
            slug = await asyncio.to_thread(note_eng.save_note, content, title, tags)
            return f"Đã ghi chú thành công: \"{content[:80]}{'...' if len(content) > 80 else ''}\" (File: topics/{slug}.md)"
        else:
            return "Ngài muốn ghi chú nội dung gì? Hãy nói: ghi chú: [nội dung cần lưu]"

    elif action == "search":
        from engine.tools.wiki_retrieval import query_wiki

        query = arguments.get("query", "").strip()
        if not query:
            notes = await asyncio.to_thread(note_eng.list_notes, 20)
            if notes:
                items = [f"- `[ID: {idx+1}]` **{n['title']}** (`topics/{n['id']}.md`)" for idx, n in enumerate(notes)]
                return f"Có {note_eng.count()} ghi chú trong Obsidian:\n" + "\n".join(items) + "\n\n(Ngài có thể dùng lệnh: 'Đọc ghi chú số 1' hoặc 'Đọc ghi chú [tên/từ khóa]' để xem nội dung chi tiết)"
            else:
                return "Chưa có ghi chú nào trong Obsidian, thưa ngài."

        # Nếu query là số ID (ví dụ: "1", "2", "số 1")
        nums = re.findall(r'\d+', query)
        if nums and (query.isdigit() or query.startswith("số ") or query.startswith("id")):
            note_idx = int(nums[0])
            notes = await asyncio.to_thread(note_eng.list_notes, 50)
            if 1 <= note_idx <= len(notes):
                target_note = notes[note_idx - 1]
                return f"Nội dung ghi chú [ID: {note_idx}] '{target_note['title']}':\n---\n{target_note['content']}\n---"

        result = await query_wiki(query, roots=("topics",))
        return result or f"Không tìm thấy ghi chú nào phù hợp với từ khóa: {query}."

