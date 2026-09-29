---
name: search_media
description: Tìm kiếm và tự động phát nhạc, video trên YouTube hoặc file local.
usage: '{"query": "CHỈ tên bài hát/video cần tìm, KHÔNG bao gồm từ khóa định tuyến (youtube, video, nhạc...)", "source": "youtube hoặc auto"}'
category: media
tags: ["utility", "music", "video"]
enabled: true
---

# Lệnh search_media

## QUY TẮC QUAN TRỌNG
- **query**: CHỈ chứa tên bài hát/video cần tìm. KHÔNG bao gồm từ khóa định tuyến.
- **source**: "youtube" cho nhạc/video, hoặc "auto".

## VÍ DỤ
| Câu người dùng | query (đúng) | source |
|---|---|---|
| "youtube come my way sơn tùng" | "come my way sơn tùng" | youtube |
| "video tối nay em thức anh nhé" | "tối nay em thức anh nhé" | youtube |
| "bài hát see tình" | "see tình" | youtube |

## CÁC TỪ KHÓA CẦN LOẠI BỎ KHỎI query
- youtube, video, nhạc, bài hát, nghe — định tuyến youtube
- mở, tìm, xem — từ hành động chung
