"""The Skill Museum: persistent, versioned, fitness-scored tool library."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

STOP = {
    "a", "an", "the", "of", "in", "on", "to", "for", "and", "or", "is", "are", "it", "that",
    "this", "with", "from", "by", "as", "be", "its", "given", "check", "whether", "compute",
    "calculate", "determine", "return", "find", "get", "function", "input", "output",
}


def tokenize(text: str) -> set:
    out = set()
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        if tok in STOP:
            continue
        out.add(tok[:-1] if len(tok) > 3 and tok.endswith("s") else tok)
    return out


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "skill"


@dataclass
class Skill:
    name: str
    description: str
    code: str
    tests: list
    tags: List[str] = field(default_factory=list)
    generation: int = 1
    successes: int = 0
    failures: int = 0
    parent: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    history: List[str] = field(default_factory=list)

    @property
    def uses(self) -> int:
        return self.successes + self.failures

    @property
    def fitness(self) -> float:
        """Laplace-smoothed success rate: new skills start at 0.5."""
        return (self.successes + 1) / (self.uses + 2)


class Registry:
    RETIRE_MIN_USES = 5
    RETIRE_BELOW = 0.30

    def __init__(self, home: str | os.PathLike):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "registry.json"
        self.skills: Dict[str, Skill] = {}
        self.graveyard: List[dict] = []
        self._load()

    # persistence -----------------------------------------------------------
    def _load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.skills = {s["name"]: Skill(**s) for s in data.get("skills", [])}
            self.graveyard = data.get("graveyard", [])

    def save(self) -> None:
        data = {"skills": [asdict(s) for s in self.skills.values()], "graveyard": self.graveyard}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def reset(self) -> None:
        self.skills, self.graveyard = {}, []
        self.save()

    # access ----------------------------------------------------------------
    def all(self) -> List[Skill]:
        return list(self.skills.values())

    def get(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def unique_name(self, base: str) -> str:
        taken = set(self.skills) | {g["name"] for g in self.graveyard}
        name, i = base, 2
        while name in taken:
            name, i = f"{base}_{i}", i + 1
        return name

    def add(self, skill: Skill) -> None:
        self.skills[skill.name] = skill
        self.save()

    def catalog(self) -> str:
        if not self.skills:
            return "(none yet)"
        return "\n".join(f"- {s.name}: {s.description}" for s in self.skills.values())

    # retrieval -------------------------------------------------------------
    def search(self, query: str, top_k: int = 3) -> List[Tuple[float, Skill]]:
        q = tokenize(query)
        scored = []
        for s in self.skills.values():
            doc = tokenize(f"{s.name} {s.description} {' '.join(s.tags)}")
            if not q or not doc:
                continue
            inter = len(q & doc)
            sim = 0.6 * inter / len(q | doc) + 0.4 * inter / len(q)
            scored.append((sim * (0.5 + 0.5 * s.fitness), s))
        return sorted(scored, key=lambda t: t[0], reverse=True)[:top_k]

    def best(self, query: str, threshold: float = 0.30) -> Optional[Skill]:
        hits = self.search(query, 1)
        return hits[0][1] if hits and hits[0][0] >= threshold else None

    # evolution bookkeeping -------------------------------------------------
    def record(self, name: str, ok: bool) -> bool:
        """Record a use. Returns True if the skill was just retired."""
        s = self.skills[name]
        if ok:
            s.successes += 1
        else:
            s.failures += 1
        retired = s.uses >= self.RETIRE_MIN_USES and s.fitness < self.RETIRE_BELOW
        if retired:
            entry = asdict(s)
            entry["retired_at"] = time.time()
            self.graveyard.append(entry)
            del self.skills[name]
        self.save()
        return retired
