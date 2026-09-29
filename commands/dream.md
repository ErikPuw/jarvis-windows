---
name: dream
description: Kích hoạt ngay 1 chu kỳ Dream — tóm tắt hội thoại cũ, gọn bớt agent_outcomes và tái tổ chức Obsidian Wiki (Daily digest, Topics, Errors.md, Evolution.md).
usage: '{}'
category: maintenance
tags: [maintain, memory, wiki, cleanup]
enabled: true
---

Công cụ này cho phép Jarvis chủ động dọn dẹp dữ liệu cũ thay vì chờ đến khung giờ tự động (02:00-05:00):
1. Gom nhóm và tóm tắt hội thoại thừa thải trong `messages` (SQLite) bằng LLM, chỉ giữ lại điều thật sự đáng nhớ.
2. Gọn bớt `agent_outcomes` cũ (giữ lỗi lâu hơn thành công để phục vụ debug).
3. Tóm tắt Daily digest cũ trong Obsidian Wiki vào file tổng-kết-tháng, nén bớt Topics đã phình to.
4. Xoay vòng `System/Errors.md` và `System/Evolution.md`, chuyển mục cũ sang `System/Archive/`.

An toàn: không xoá vĩnh viễn — mọi thứ được sao lưu vào `data/dream_archive/` hoặc `data/wiki/.trash/dream/` trước khi gộp. Chạy nền (fire-and-forget), không chặn cuộc trò chuyện hiện tại.
