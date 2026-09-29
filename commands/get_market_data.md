---
name: get_market_data
description: Tra cứu thông tin giá vàng SJC, tỷ giá USD/VND, giá xăng dầu Petrolimex hoặc giá gas thời gian thực.
usage: '{"query": "từ khóa tìm kiếm ví dụ: vàng, xăng, đô la, gas, hoặc tổng hợp"}'
category: info
tags: ["finance", "market"]
enabled: true
---

# Lệnh get_market_data
Sử dụng lệnh này để tra cứu thông tin thị trường trong nước. Truyền tham số dưới dạng JSON string vào trường `args` của tool `execute_command`.
Ví dụ: `{"query": "vàng"}` hoặc `{"query": "tổng hợp"}`
