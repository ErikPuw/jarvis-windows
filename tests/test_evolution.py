"""Smoke test for engine.core.evolution changelog helpers. Run: python tests/test_evolution.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core.evolution import _extract_bullets

SKILL = '''---
name: self_evolution
version: "5.6.0"
---

# Self Evolution Routing Rules
- Tuyệt đối không kích hoạt tool/agent khi người dùng chỉ đang trò chuyện thông thường.
- Luôn ưu tiên phản hồi tự nhiên và chỉ sử dụng tool khi yêu cầu hành động hệ thống rõ ràng.
'''


def test_extract_bullets_skips_frontmatter_and_heading():
    bullets = _extract_bullets(SKILL)
    assert len(bullets) == 2
    assert all(b.startswith("- ") for b in bullets)
    assert not any("version" in b or "Rules" in b for b in bullets)


if __name__ == "__main__":
    test_extract_bullets_skips_frontmatter_and_heading()
    print("OK: all evolution smoke tests passed")
