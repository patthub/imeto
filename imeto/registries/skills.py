"""SkillRegistry — warstwa 4: wiedza dziedzinowa jako DANE, nie kod.

Format Agent Skills: każdy skill to katalog `knowledge/extraction/<typ>/` z plikiem
`SKILL.md` (frontmatter YAML + instrukcje) i opcjonalnym `few_shot/*.json` (przykłady).
`load()` składa fragment promptu: treść SKILL.md (bez frontmatteru) + wyrenderowane
przykłady. Ekspert stroi ekstrakcję per typ, nie dotykając Pythona."""

import json
from pathlib import Path


def _strip_frontmatter(text: str) -> str:
    """Usuwa blok YAML `--- ... ---` z początku, zwraca samą treść instrukcji."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


class SkillRegistry:
    def __init__(self, knowledge_dir: str | Path = "knowledge") -> None:
        self._dir = Path(knowledge_dir) / "extraction"

    def load(self, name: str) -> str:
        skill_dir = self._dir / name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            raise ValueError(f"brak skillu '{name}' ({skill_md})")
        body = _strip_frontmatter(skill_md.read_text(encoding="utf-8")).strip()
        examples = self._render_few_shot(skill_dir / "few_shot")
        return f"{body}\n\n## Przykłady\n{examples}" if examples else body

    def list(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(
            p.name for p in self._dir.iterdir() if (p / "SKILL.md").exists()
        )

    def _render_few_shot(self, few_shot_dir: Path) -> str:
        if not few_shot_dir.exists():
            return ""
        blocks: list[str] = []
        for path in sorted(few_shot_dir.glob("*.json")):
            ex = json.loads(path.read_text(encoding="utf-8"))
            expected = json.dumps({"facts": ex.get("facts", [])}, ensure_ascii=False)
            blocks.append(f"Fragment: {ex.get('fragment', '')}\nOczekiwane: {expected}")
        return "\n\n".join(blocks)
