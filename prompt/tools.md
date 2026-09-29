# DANH MỤC AGENTS VÀ TOOLS

## @desktop
alias: @agent_desktop
Mở, đóng ứng dụng Windows.
- open_app | mở ứng dụng | offer
- close_app | đóng ứng dụng | offer

## @dream
alias: @agent_dream
Dọn dẹp, tóm tắt hội thoại cũ và kích hoạt chu kỳ Dream.
- dream | chu kỳ dream | -

## @email
alias: @agent_email, @mail, @calendar
Kiểm tra 10 email gần nhất hoặc lịch hẹn 7 ngày tới trong Outlook.
- check_mail | xem email | offer
- check_calendar | xem lịch hẹn | offer

## @goose
alias: @agent_goose
Chỉ mở giao diện ứng dụng Goose (Windows GUI) để người dùng tự thao tác.

## @history
alias: @agent_history
Tra cứu và xem lại lịch sử trò chuyện cũ.
- query_history | xem lại lịch sử trò chuyện | offer

## @image
alias: @agent_image, @upscale
Tăng độ phân giải và chi tiết của ảnh bằng AI Upscayl.
- upscale_image | tăng độ phân giải ảnh | -

## @legal
alias: @agent_legal
Tra cứu văn bản pháp luật Việt Nam.
- legal_lookup | tra cứu pháp luật | -

## @media
alias: @agent_media
Nghe nhạc, xem livestream, xem video Youtube.
- search_media | mở nhạc/video | offer

## @notes
alias: @agent_notes
Ghi lại, hiển thị danh sách, hoặc xoá note.
- take_note | ghi chú | offer
- read_note | xem ghi chú | -

## @office
alias: @agent_office, @officecli
Tạo hoặc chỉnh sửa nội dung tệp Word, Excel, PowerPoint qua officecli.
- office_tool | thao tác office | -

## @project
alias: @agent_project
Kiểm tra project, quét lỗi cú pháp, báo cáo sức khỏe, lịch sử vá lỗi.
- check_project | kiểm tra dự án | -

## @rag
alias: @agent_rag
Đọc, tóm tắt hoặc phân tích nội dung tệp đính kèm.
- rag_tool | hỏi đáp tài liệu rag | -

## @search
alias: @agent_search
Tra cứu thời gian thực dạng văn bản: thời tiết, tin tức, giá thị trường, bản đồ, lịch vạn niên, cung hoàng đạo, phim CGV, game.
- weather_search | tra thời tiết | offer
- search_news | tìm tin tức | offer
- get_market_data | giá vàng/xăng/tỷ giá | offer
- get_cgv_movies | lịch chiếu phim | offer
- get_epic_free_games | game miễn phí | offer
- get_vannien_data | lịch vạn niên | offer
- get_zodiac_data | tra cứu cung hoàng đạo | -
- vietnam_data_lookup | tra cứu dữ liệu việt nam | -
- map_route | tìm đường đi | -
- map_pois | tìm địa điểm | -
- search_products | tra cứu giá sản phẩm | -
- web_research | tìm hiểu trên web | -

## @security
alias: @agent_security
Kiểm tra an ninh mạng, quét cổng, giám sát firewall, nhật ký xâm nhập.
- check_security | kiểm tra an ninh | -

## @vietlott
alias: @agent_vietlott
Phân tích kết quả Mega 6/45, Power 6/55.
- vietlott_analysis | phân tích vietlott | -

## @vision
alias: @agent_vision
Chụp hoặc xem màn hình hiện tại.
- cap_screen | chụp màn hình | offer
- read_screen | xem màn hình | offer

## @webcam
alias: @agent_webcam
Xem hoặc dùng webcam, camera trực tiếp.
- read_webcam | xem webcam | -

## @win_control
alias: @agent_win_control, @agent_control, @control
Điều khiển ứng dụng Windows chạy nền (mở app, bấm, nhập chữ) qua cua-driver, hoặc phóng to/thu nhỏ/khôi phục cửa sổ.
- win_control | điều khiển windows | -

## @system
Mục hệ thống không thuộc agent nào, không đề nghị qua chat.
- install_extension | cài đặt extension | -
- mcp_call | gọi công cụ mcp | -
