---
name: check_security
description: Quét và kiểm tra trạng thái bảo mật của hệ thống JARVIS bao gồm cổng mạng, log xâm nhập và kiểm soát Whitelist IP.
usage: '{}'
category: security
tags: [security, firewall, scan, connections, whitelist]
enabled: true
---

Công cụ này thực hiện quét an ninh hệ thống thời gian thực:
1. Đọc và phân tích logs/security_alerts.log để báo cáo số lần xâm nhập bị chặn.
2. Kiểm tra xem cấu hình .env là chỉ cho phép nội bộ (local-only) hay mở rộng mạng LAN.
3. Liệt kê các cổng mạng và kiểm tra xem có kết nối đáng ngờ nào đang hoạt động không.
