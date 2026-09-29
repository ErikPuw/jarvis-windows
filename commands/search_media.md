---
name: search_media
description: Tìm kiếm và tự động phát nội dung giải trí (phim, nhạc, video) trên YouTube, trang phim (hhpanda), hoặc file local.
usage: '{"query": "CHỈ tên phim/nội dung, KHÔNG bao gồm từ khóa định tuyến (hhpanda, hhpada, phim, xem phim, youtube, video, nhạc...)", "source": "youtube, phim, hoặc auto"}'
category: media
tags: ["utility", "music", "video"]
enabled: true
---

# Lệnh search_media

## QUY TẮC QUAN TRỌNG
- **query**: CHỈ chứa tên phim/bài hát/nội dung cần tìm. KHÔNG bao gồm từ khóa định tuyến.
- **source**: "phim" cho phim (hhpanda), "youtube" cho nhạc/video.

## VÍ DỤ
| Câu người dùng | query (đúng) | source |
|---|---|---|
| "hhpanda phim đấu phá thương khung tập 5" | "đấu phá thương khung" | phim |
| "youtube come my way sơn tùng" | "come my way sơn tùng" | youtube |
| "video tối nay em thức anh nhé" | "tối nay em thức anh nhé" | youtube |
| "hhpada phim tiên nghịch tập 10" | "tiên nghịch" | phim |
| "bài hát see tình" | "see tình" | youtube |
| "xem phim đấu phá thương khung phần 5" | "đấu phá thương khung phần 5" | phim |

## CÁC TỪ KHÓA CẦN LOẠI BỎ KHỎI query
- hhpanda, hhpada (và mọi biến thể) — định tuyến phim
- phim, xem phim — định tuyến phim
- youtube, video, nhạc, bài hát, nghe — định tuyến youtube
- mở, tìm, xem — từ hành động chung

## LƯU Ý
Nếu người dùng nói "tập {số}" thì GIỮ LẠI tên phim, chỉ LOẠI bỏ từ khóa định tuyến.
Ví dụ: "hhpanda phim tiên nghịch tập 10" → query="tiên nghịch", source="phim"
