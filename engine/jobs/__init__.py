"""Tìm việc và nộp hồ sơ qua Gmail (spec docs/superpowers/specs/2026-09-27-job-search-design.md)."""
SESSION_IDLE_S = 30 * 60
PENDING_TTL_S = 3 * 24 * 3600
MAX_PENDING = 5
MIN_SCORE = 6
RESULTS_PER_QUERY = 10
EMAIL_WINDOW = 300
POST_CHARS = 4000
MAX_SENT_PER_DAY = 10
SEND_GAP_S = 60
LETTER_MAX_WORDS = 400
RUN_HOUR = 8
SCHEDULER_TICK_S = 30 * 60
ENGLISH_LEVELS = ("không", "cơ bản", "giao tiếp", "thành thạo")
LOW_ENGLISH = ("không", "cơ bản")
