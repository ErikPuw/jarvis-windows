---
name: close_app
description: Tắt hoặc đóng một ứng dụng bất kỳ trên hệ thống Windows.
usage: '{"app_name": "tên ứng dụng cần đóng, ví dụ: notepad, chrome, taskmgr, spotify"}'
category: system
tags: ["utility", "control"]
enabled: true
---

# Lệnh close_app
Sử dụng lệnh này để đóng hoặc tắt bất kỳ ứng dụng Windows nào đang chạy. Truyền tham số dưới dạng JSON string vào trường `args` của tool `execute_command`.
Ví dụ: `{"app_name": "notepad"}`
