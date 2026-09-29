---
name: open_app
description: Mở một ứng dụng bất kỳ trên hệ thống Windows.
usage: '{"app_name": "tên ứng dụng cần mở, ví dụ: notepad, chrome, taskmgr, spotify"}'
category: system
tags: ["utility", "control"]
enabled: true
---

# Lệnh open_app
Sử dụng lệnh này để mở bất kỳ ứng dụng Windows nào. Truyền tham số dưới dạng JSON string vào trường `args` của tool `execute_command`.
Ví dụ: `{"app_name": "notepad"}`
