---
name: install_extension
description: Tải và cài đặt tự động các phần mở rộng cho Jarvis (Plugins, Skills, Hooks). Hỗ trợ nạp nóng (Hot Reload) không cần khởi động lại server.
usage: '{"ext_type": "plugin|skill|hook", "name": "ten_extension", "url": "url_tai_file", "code_content": "ma_nguon"}'
category: system
tags: ["system", "install", "extension", "plugin", "skill", "hook"]
enabled: true
---

# Lệnh install_extension
Sử dụng lệnh này khi người dùng yêu cầu cài đặt, tích hợp hoặc cập nhật một plugin, skill hoặc hook mới cho hệ thống Jarvis. 

Lệnh hỗ trợ hai cơ chế cài đặt:
1. **Qua URL**: Cung cấp đường dẫn raw (ví dụ từ GitHub) tại tham số `url`.
2. **Qua Code Content**: Truyền trực tiếp mã nguồn hoặc nội dung markdown vào tham số `code_content`.

Ví dụ tham số args:
- Cài plugin qua URL: `{"ext_type": "plugin", "name": "security_check", "url": "https://raw.githubusercontent.com/.../security_check.py"}`
- Cài skill qua Code: `{"ext_type": "skill", "name": "custom_skill", "code_content": "# Custom Skill\n..."}`
