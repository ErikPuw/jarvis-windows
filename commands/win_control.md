---
name: win_control
description: Điều khiển ứng dụng Windows chạy nền qua cua-driver (UI Automation, không chiếm chuột): mở app, đọc cây UI, bấm, nhập chữ, phím tắt, chọn menu; điều khiển taskbar và Start menu (pywinauto, không dùng chuột); và phóng to/thu nhỏ/khôi phục cửa sổ. Mỗi thao tác thay đổi máy cần xác nhận (CUA_CONFIRM).
usage: '{"user_text": "Yêu cầu @control của người dùng"}'
category: system
tags: ["windows", "control", "verified"]
enabled: true
---

# Lệnh win_control

Chỉ dùng thông qua `@control`. Model chọn từng bước (list_windows, launch_app, get_window_state, click, type_text, set_value, press_key, hotkey, scroll, invoke_menu, shell_state, shell_click, shell_set_text) và chỉ chạm phần tử theo `element_index`; không bấm theo toạ độ. Không tìm thấy cửa sổ/phần tử thì dừng và báo "Lỗi: …". Phóng to/thu nhỏ/khôi phục cửa sổ đi đường riêng có xác minh trạng thái.
