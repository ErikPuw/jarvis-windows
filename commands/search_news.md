---
name: search_news
description: Tìm kiếm tóm tắt 5 bài báo, tin tức thời sự, công nghệ, đời sống tổng hợp trong nước (.vn).
usage: '{"query": "nội dung tin tức cần tìm kiếm, ví dụ: tin AI mới nhất, sự kiện thể thao"}'
category: info
tags: ["news", "search"]
enabled: true
---

# Lệnh search_news
Sử dụng lệnh này để tìm kiếm tin tức trực tuyến trong nước. Truyền tham số dưới dạng JSON string vào trường `args` của tool `execute_command`.
Ví dụ: `{"query": "tin công nghệ mới nhất"}`
