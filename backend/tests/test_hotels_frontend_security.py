from pathlib import Path


def test_credentials_do_not_appear_in_frontend_sources():
    frontend = Path(__file__).parents[2] / "frontend"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in frontend.rglob("*") if path.is_file() and "node_modules" not in path.parts and ".next" not in path.parts)
    assert "HOTELS_USERS_JSON" not in sources
    assert '"password":"0101"' not in sources
