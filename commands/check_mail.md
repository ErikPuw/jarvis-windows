---
name: check_mail
description: Mở hoặc dùng lại New Outlook để kiểm tra tối đa 10 email gần nhất; không mở nội dung, gửi, xóa hoặc thay đổi trạng thái thư.
usage: '{"max_results": "Số email gần nhất cần hiển thị, từ 1 đến 10"}'
category: info
tags: ["email", "mail", "outlook", "thư gần nhất"]
enabled: true
---

# Lệnh check_mail

Chỉ dùng New Outlook mặc định trên Windows 11.

- Nếu cửa sổ Thư đang mở, dùng đúng cửa sổ đó.
- Nếu chưa mở, khởi động New Outlook và chờ cửa sổ Thư sẵn sàng.
- Dùng danh sách Tất cả và lấy tối đa 10 hàng thư gần nhất đang hiển thị.
- Nếu Outlook đang có bộ lọc, chỉ dùng nút Xóa bộ lọc; không mở menu bộ lọc.
- Không mở email, không gửi, không xóa và không thay đổi trạng thái đã đọc.
- Sau khi báo kết quả, luôn hỏi người dùng có muốn đóng Outlook không.
- Chỉ đóng mềm đúng cửa sổ Outlook khi người dùng xác nhận.
