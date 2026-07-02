"""SkillRegistry — warstwa 4: wiedza dziedzinowa jako DANE, nie kod. Skill to plik
`.md` z `knowledge/extraction/`, ładowany do promptu na żądanie fazy. Ekspert stroi
ekstrakcję per typ wytworu, nie dotykając Pythona."""

from pathlib import Path


class SkillRegistry:
    def __init__(self, knowledge_dir: str | Path = "knowledge") -> None:
        self._dir = Path(knowledge_dir) / "extraction"

    def load(self, name: str) -> str:
        path = self._dir / f"{name}.md"
        if not path.exists():
            raise ValueError(f"brak skillu ekstrakcji '{name}' ({path})")
        return path.read_text(encoding="utf-8")

    def list(self) -> list[str]:
        return sorted(p.stem for p in self._dir.glob("*.md"))
