from pathlib import Path

import pytest

from imeto.registries.skills import SkillRegistry

SKILL_MD = """---
name: extract-article
metadata:
  work_type: article
---

## Rola
Wydobywasz fakty z artykułu.
"""


def _make_skill(root: Path, name: str, *, few_shot: dict | None = None) -> None:
    d = root / "extraction" / name
    (d / "few_shot").mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    if few_shot is not None:
        import json

        (d / "few_shot" / "ex1.json").write_text(
            json.dumps(few_shot, ensure_ascii=False), encoding="utf-8"
        )


def test_load_strips_frontmatter(tmp_path: Path):
    _make_skill(tmp_path, "article")
    body = SkillRegistry(tmp_path).load("article")
    assert body.startswith("## Rola")
    assert "name: extract-article" not in body  # frontmatter zdjęty


def test_load_appends_few_shot(tmp_path: Path):
    _make_skill(
        tmp_path,
        "article",
        few_shot={
            "fragment": "Uzyskano 92%.",
            "facts": [
                {"statement": "92%", "kind": "direct", "quotes": ["Uzyskano 92%"]}
            ],
        },
    )
    body = SkillRegistry(tmp_path).load("article")
    assert "## Przykłady" in body
    assert "Uzyskano 92%" in body


def test_missing_skill_raises(tmp_path: Path):
    (tmp_path / "extraction").mkdir()
    with pytest.raises(ValueError):
        SkillRegistry(tmp_path).load("nieistniejacy")


def test_list_skills(tmp_path: Path):
    _make_skill(tmp_path, "report")
    _make_skill(tmp_path, "article")
    assert SkillRegistry(tmp_path).list() == ["article", "report"]


def test_real_skills_present():
    # każdy zdefiniowany WorkType MUSI mieć skill z treścią i przykładem
    from imeto.worktypes import WorkType

    reg = SkillRegistry("knowledge")
    for wt in WorkType:
        loaded = reg.load(wt.value)
        assert "## Rola" in loaded
        assert "## Przykłady" in loaded
