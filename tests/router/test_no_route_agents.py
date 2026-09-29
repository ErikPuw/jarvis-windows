import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_route_agents_module_is_gone_and_unreferenced():
    assert not (ROOT / "engine" / "server" / "route_agents.py").exists()
    offenders = [
        str(p.relative_to(ROOT)) for p in list(ROOT.glob("engine/**/*.py")) + list(ROOT.glob("tests/**/*.py")) + [ROOT / "server.py"]
        if re.search(r"(from|import)\s+engine\.server(\.route_agents| import route_agents)", p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], offenders
