---
name: take_note
description: Luu ghi chu ca nhan, tim kiem va quan ly Knowledge Base
parameters:
  - name: action
    type: string
    enum: [save, search, list, delete]
    description: Hanh dong can thuc hien
  - name: content
    type: string
    description: Noi dung ghi chu (khi action=save)
  - name: query
    type: string
    description: Tu khoa tim kiem (khi action=search)
  - name: note_id
    type: integer
    description: ID ghi chu (khi action=delete)
---

# Lenh: take_note

Su dung lenh nay khi nguoi dung muon:
- Luu mot ghi chu: "ghi chu: [noi dung]"
- Tim kiem ghi chu: "tim ghi chu [tu khoa]"
- Xem danh sach: "danh sach ghi chu" hoac "hien ghi chu"
- Xoa ghi chu: "xoa ghi chu #[id]"

Ghi chu duoc luu vao SQLite va tu dong duoc tich hop vao RAG khi tim kiem.
