---
name: check_project
description: Quét kiểm tra lỗi cú pháp tĩnh trên toàn bộ dự án và xem báo cáo sức khỏe cùng lịch sử sửa lỗi.
usage: '{}'
category: maintenance
tags: [maintain, debug, audit, syntax]
enabled: true
---

Công cụ này cho phép Jarvis chủ động kiểm tra sức khỏe của toàn bộ mã nguồn dự án:
1. Duyệt qua tất cả các tệp Python trong hệ thống và chạy py_compile để phát hiện lỗi cú pháp tĩnh.
2. Tổng hợp lịch sử tiến hóa và các bài học đã giải quyết từ cơ sở dữ liệu học tập.
3. Không kích hoạt cơ chế Goose CLI tự động sửa chữa để đảm bảo an toàn tuyệt đối.
