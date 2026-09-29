---
name: upscale_image
description: Tăng độ phân giải và chi tiết của ảnh bằng AI (Upscayl), hỗ trợ các model: upscayl-standard-4x, upscayl-lite-4x, digital-art-4x, high-fidelity-4x, remacri-4x, ultramix-balanced-4x, ultrasharp-4x.
usage: '{"input_path": "Đường dẫn tuyệt đối tới file ảnh đầu vào (jpg/png/webp/bmp)", "output_path": "(tùy chọn) Đường dẫn lưu ảnh đầu ra", "scale": "(tùy chọn) Tỉ lệ phóng to: 2, 3, hoặc 4 (mặc định: 4)", "model_name": "(tùy chọn) Tên model AI (mặc định: upscayl-standard-4x)", "output_format": "(tùy chọn) Định dạng đầu ra: png, jpg, webp (mặc định: png)"}'
category: image
tags: ["utility", "image", "upscale", "ai"]
enabled: true
---

# Lệnh upscale_image
Sử dụng lệnh này để tăng độ phân giải và chi tiết của ảnh bằng AI Upscayl. Yêu cầu GPU có hỗ trợ Vulkan. Kết quả trả về là đường dẫn tới ảnh đã được upscale.
