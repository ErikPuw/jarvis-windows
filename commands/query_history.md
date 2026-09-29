---
name: query_history
description: Truy van lich su hoi thoai cu giua nguoi dung va tro ly ao Jarvis. Dung khi nguoi dung muon tim lai noi dung cuoc tro chuyen trong qua khu.
parameters:
  - name: query
    type: string
    description: Tu khoa tim kiem hoac mo ta khoang thoi gian can truy van (vi du 'sangs nay', 'hom qua', 'tuan truoc')
  - name: limit
    type: integer
    description: Gioi han so luot hoi thoai can lay (mac dinh la 20)
---

# Lenh: query_history

Su dung lenh nay khi nguoi dung muon xem lai:
- Lịch sử trò chuyện: "nãy tôi bảo gì", "hôm qua mình đã nói những gì"
- Tìm kiếm tin nhắn cũ.
