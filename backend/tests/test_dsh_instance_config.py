from pathlib import Path

import pytest

from app.services.dsh.instance_config import CONNECTOR_ID, ensure_home_config

ARGS = dict(
    platform_base="http://127.0.0.1:8000",
    user_id="u-1",
    platform_token="tok-1",
    trusted_host="localhost:3000",
)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    return home_dir


@pytest.fixture
def skills_src(tmp_path: Path) -> Path:
    src = tmp_path / "skills-src"
    skill_dir = src / "platform-knowledge"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: platform-knowledge\ndescription: test skill\n---\n\nbody\n",
        encoding="utf-8",
    )
    return src


def _patch_text(home: Path) -> str:
    return (home / "profiles" / "web" / "cordis.patch.yml").read_text(encoding="utf-8")


def test_patch_contains_connector_row_and_three_keys(home: Path, skills_src: Path):
    ensure_home_config(home, skills_src=skills_src, **ARGS)
    text = _patch_text(home)
    assert f"id: {CONNECTOR_ID}" in text
    assert "platformBase: http://127.0.0.1:8000" in text
    assert "userId: u-1" in text
    assert "platformToken: tok-1" in text


def test_idempotent_no_duplicate_rows(home: Path, skills_src: Path):
    ensure_home_config(home, skills_src=skills_src, **ARGS)
    ensure_home_config(home, skills_src=skills_src, **ARGS)
    text = _patch_text(home)
    assert text.count(f"- id: {CONNECTOR_ID}") == 1
    assert text.count(f"id: {CONNECTOR_ID}") == 1


def test_token_refresh_rewrites_full_config_row(home: Path, skills_src: Path):
    ensure_home_config(home, skills_src=skills_src, **ARGS)
    ensure_home_config(
        home,
        skills_src=skills_src,
        **{**ARGS, "platform_token": "tok-2"},
    )
    text = _patch_text(home)
    assert "platformToken: tok-2" in text
    assert "platformToken: tok-1" not in text
    assert "platformBase: http://127.0.0.1:8000" in text
    assert "userId: u-1" in text


def test_skills_tree_copied_into_home(home: Path, skills_src: Path):
    ensure_home_config(home, skills_src=skills_src, **ARGS)
    target = home / "skills" / "platform-knowledge" / "SKILL.md"
    assert target.exists()
    assert "name: platform-knowledge" in target.read_text(encoding="utf-8")


def test_patch_appends_row_into_empty_list_template(home: Path, skills_src: Path):
    patch_dir = home / "profiles" / "web"
    patch_dir.mkdir(parents=True)
    (patch_dir / "cordis.patch.yml").write_text("[]\n", encoding="utf-8")
    ensure_home_config(home, skills_src=skills_src, **ARGS)
    text = _patch_text(home)
    assert text.count(f"- id: {CONNECTOR_ID}") == 1
    assert "platformToken: tok-1" in text
