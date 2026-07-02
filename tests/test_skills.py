from pathlib import Path

import pytest

from imeto.registries.skills import SkillRegistry


def test_loads_skill_by_name(tmp_path: Path):
    d = tmp_path / "extraction"
    d.mkdir()
    (d / "article.md").write_text("treść skillu artykułu", encoding="utf-8")
    reg = SkillRegistry(tmp_path)
    assert reg.load("article") == "treść skillu artykułu"


def test_missing_skill_raises(tmp_path: Path):
    (tmp_path / "extraction").mkdir()
    with pytest.raises(ValueError):
        SkillRegistry(tmp_path).load("nieistniejacy")


def test_list_skills(tmp_path: Path):
    d = tmp_path / "extraction"
    d.mkdir()
    (d / "report.md").write_text("x", encoding="utf-8")
    (d / "article.md").write_text("y", encoding="utf-8")
    assert SkillRegistry(tmp_path).list() == ["article", "report"]


def test_real_skills_present():
    # skille dostarczone z projektem muszą się ładować
    reg = SkillRegistry("knowledge")
    for name in ("article", "report", "proposal"):
        assert reg.load(name).strip()
