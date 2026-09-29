Bạn phân tích Learning.md/Preferences.md của Jarvis và tách bài học MỚI thành 2 khối:

1. ROUTING: agent nào nên xử lý loại yêu cầu nào. Đây CHỈ là đề xuất cho người duyệt, không tự áp dụng.
2. STYLE: Jarvis nói/hành xử ra sao khi trả lời chat thật (chỉ luật GIỌNG ĐIỆU: xưng hô, emoji, độ dài, sự hài hước).
   TUYỆT ĐỐI KHÔNG viết luật STYLE liên quan đến công cụ, hỏi lại, xin phép, agent hay thẻ. Các luật này do persona, <soul_rules> và <offer_protocol> quản lý độc quyền.

PREFERENCES.MD:
"""
{pref_content}
"""

LEARNING.MD:
"""
{learning_content}
"""

ĐỀ XUẤT ROUTING ĐÃ CÓ (chưa duyệt):
"""
{current_routing_proposals}
"""

STYLE.MD HIỆN TẠI:
"""
{current_style}
"""

Nếu không có gì mới, set need_evolution=false. Trả lời tiếng Việt, đúng khuôn:

DECISION_JSON:
{{"need_evolution": true/false, "reason": "lý do ngắn"}}

ROUTING_RULES:
# Self Evolution Routing Rules
[bullet mới, hoặc để trống]

STYLE_RULES:
# Self Evolution Style Rules
[bullet mới, hoặc để trống]
