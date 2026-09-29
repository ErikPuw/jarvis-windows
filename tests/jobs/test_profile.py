"""Gom hồ sơ bằng code, không LLM (spec mục 6)."""
from engine.jobs import profile


def test_build_splits_lists_and_defaults():
    p = profile.build({
        "full_name": " Nguyễn Văn A ", "phone": "0901234567", "email": "", "location": "Hà Nội",
        "positions": "kế toán, kế toán tổng hợp, thủ quỹ, thu ngân",
        "experience": ["Công ty X, 2020-2023", "  "],
        "education": "ĐH Kinh tế, Kế toán, 2019\nCao đẳng Y",
        "certificates": "", "skills": "Excel; MISA", "english": "", "expectations": "10 triệu",
        "dealbreakers": "ca đêm",
    }, gmail="a@gmail.com")
    assert p["full_name"] == "Nguyễn Văn A"
    assert p["email"] == "a@gmail.com"
    assert p["positions"] == ["kế toán", "kế toán tổng hợp", "thủ quỹ"]
    assert p["experience"] == ["Công ty X, 2020-2023"]
    assert p["education"] == ["ĐH Kinh tế, Kế toán, 2019", "Cao đẳng Y"]
    assert p["skills"] == ["Excel", "MISA"]
    assert p["english"] == "không"
    assert p["dealbreakers"] == ["ca đêm"]


def test_missing_required_fields():
    assert profile.missing(profile.build({})) == [
        "họ tên (câu 1)", "số điện thoại (câu 2)", "email (câu 3)", "vị trí ứng tuyển (câu 5)"]
    full = profile.build({"full_name": "A", "phone": "1", "email": "a@b.vn", "positions": "x"})
    assert profile.missing(full) == []
