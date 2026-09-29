---
name: check_calendar
description: Mở hoặc dùng lại New Outlook để kiểm tra tối đa 10 mục lịch trong 7 ngày tới, gồm lịch hẹn, ngày lễ và sinh nhật cá nhân.
usage: '{"max_results": "Số mục lịch cần hiển thị, từ 1 đến 10"}'
category: info
tags: ["calendar", "outlook", "lịch", "lịch hẹn", "sinh nhật", "ngày lễ"]
enabled: true
---

# Lệnh check_calendar

Chỉ dùng New Outlook mặc định trên Windows 11.

- Nếu Outlook đang mở, dùng lại đúng cửa sổ đó; nếu chưa mở thì khởi động New Outlook.
- Chỉ đọc lịch từ hôm nay đến hết 6 ngày tiếp theo và hiển thị tối đa 10 mục.
- Bao gồm các lịch đang bật trong Outlook: lịch hẹn cá nhân, ngày lễ và sinh nhật cá nhân.
- Hỗ trợ giờ sáng, chiều và tối; giờ `CH` được báo theo định dạng 24 giờ.
- Không mở chi tiết, tạo, sửa, xóa hoặc phản hồi sự kiện.
- Sau khi đọc, khôi phục chế độ xem và module Outlook ban đầu.
- Sau khi báo kết quả, luôn hỏi người dùng có muốn đóng Outlook không.
- Chỉ đóng mềm đúng cửa sổ Outlook khi người dùng xác nhận.
