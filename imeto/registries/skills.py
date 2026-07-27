"""SkillRegistry — layer 4: domain knowledge as DATA, not code.

Agent Skills format: a skill is a `knowledge/<subdir>/<name>/` directory with a
`SKILL.md` file (YAML frontmatter + instructions) and optional `few_shot/*.json`.
`subdir` = kind: "extraction" (what counts as a claim for a given work type) or
"criteria" (scoring rubrics, e.g. Criterion III). `load()` assembles a prompt
fragment: SKILL.md body (without frontmatter) + rendered examples. The expert
tunes knowledge without touching Python."""

import json
from pathlib import Path


def _strip_frontmatter(text: str) -> str:
    """Strips the leading YAML `--- ... ---` block, returns just the instructions."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


class SkillRegistry:
    def __init__(self, knowledge_dir: str | Path = "knowledge") -> None:
        self._base = Path(knowledge_dir)

    def load(self, name: str, subdir: str = "extraction") -> str:
        skill_dir = self._base / subdir / name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            raise ValueError(f"no skill '{name}' in '{subdir}' ({skill_md})")
        body = _strip_frontmatter(skill_md.read_text(encoding="utf-8")).strip()
        examples = self._render_few_shot(skill_dir / "few_shot")
        return f"{body}\n\n## Examples\n{examples}" if examples else body

    def list(self, subdir: str = "extraction") -> list[str]:
        d = self._base / subdir
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if (p / "SKILL.md").exists())

    def _render_few_shot(self, few_shot_dir: Path) -> str:
        if not few_shot_dir.exists():
            return ""
        blocks: list[str] = []
        for path in sorted(few_shot_dir.glob("*.json")):
            ex = json.loads(path.read_text(encoding="utf-8"))
            expected = json.dumps({"facts": ex.get("facts", [])}, ensure_ascii=False)
            blocks.append(f"Excerpt: {ex.get('fragment', '')}\nExpected: {expected}")
        return "\n\n".join(blocks)
