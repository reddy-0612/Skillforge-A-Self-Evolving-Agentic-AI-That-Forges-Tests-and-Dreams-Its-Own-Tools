"""The agent loop: plan -> (reuse | forge -> test -> mutate) -> execute -> heal -> dream."""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from .prompts import (EDGE_SYSTEM, EVOLVE_SYSTEM, FORGE_SYSTEM, PLAN_SYSTEM,
                      edge_prompt, evolve_prompt, forge_prompt, plan_prompt)
from .registry import Registry, Skill, slugify
from .sandbox import execute

Emit = Callable[[str, str], None]


@dataclass
class Report:
    passed: bool
    summary: str


@dataclass
class StepResult:
    capability: str
    skill: str
    origin: str  # "reused" | "forged"
    input: Any
    output: Any = None
    ok: bool = True
    error: Optional[str] = None


@dataclass
class RunResult:
    task: str
    steps: List[StepResult] = field(default_factory=list)
    final: Any = None
    ok: bool = True
    note: str = ""


def same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


def validate(spec: dict) -> Report:
    """Run a tool spec's own tests inside the sandbox."""
    try:
        code, tests = spec["code"], spec["tests"]
        if not isinstance(tests, list) or len(tests) < 2:
            return Report(False, "at least 2 tests are required")
        inputs = [t["input"] for t in tests]
    except (KeyError, TypeError):
        return Report(False, "spec must contain 'code' and 'tests' (each with 'input' and 'expected')")
    failures = []
    for t, o in zip(tests, execute(code, inputs)):
        if not o.ok:
            failures.append(f"input={t['input']!r} raised {o.error}")
        elif not same(o.value, t.get("expected")):
            failures.append(f"input={t['input']!r} expected={t.get('expected')!r} got={o.value!r}")
    if failures:
        return Report(False, "; ".join(failures[:5]))
    return Report(True, f"{len(tests)}/{len(tests)} tests passed")


def skill_spec(s: Skill) -> dict:
    return {"name": s.name, "description": s.description, "tags": s.tags, "code": s.code, "tests": s.tests}


class ForgeAgent:
    def __init__(self, llm, registry: Registry, emit: Optional[Emit] = None,
                 max_generations: int = 4, reuse_threshold: float = 0.35):
        self.llm, self.registry = llm, registry
        self.emit: Emit = emit or (lambda kind, msg: None)
        self.max_generations = max_generations
        self.reuse_threshold = reuse_threshold

    # ---------------------------------------------------------------- solve
    def solve(self, task: str) -> RunResult:
        self.emit("task", task)
        plan = self.llm.json("plan", PLAN_SYSTEM, plan_prompt(task, self.registry.catalog()), {"task": task})
        steps = plan.get("steps") or []
        result = RunResult(task=task)
        if not steps:
            result.ok, result.note = False, plan.get("note", "The planner produced no steps.")
            self.emit("warn", result.note)
            return result
        self.emit("plan", " -> ".join(s["capability"] for s in steps))

        prev: Any = None
        for step in steps:
            cap = step["capability"]
            inp = prev if step.get("input") == "$prev" else step.get("input")
            skill = self.registry.best(cap, self.reuse_threshold)
            origin = "reused"
            if skill:
                self.emit("reuse", f"{skill.name} (gen {skill.generation}, fitness {skill.fitness:.2f})")
            else:
                origin = "forged"
                skill = self._forge(cap, inp)
            if skill is None:
                result.steps.append(StepResult(cap, "-", origin, inp, ok=False, error="could not forge a working tool"))
                result.ok = False
                self.emit("warn", f"giving up on: {cap}")
                break
            value, err = self._invoke(skill, inp)
            result.steps.append(StepResult(cap, skill.name, origin, inp, value, err is None, err))
            if err:
                result.ok = False
                break
            prev = value
        result.final = prev if result.ok else None
        if result.ok:
            self.emit("answer", repr(result.final))
        self._log(result)
        return result

    # ---------------------------------------------------------------- forge
    def _forge(self, capability: str, sample_input: Any) -> Optional[Skill]:
        self.emit("forge", f"no skill matches: '{capability}'")
        spec = self.llm.json("forge", FORGE_SYSTEM, forge_prompt(capability, sample_input),
                             {"capability": capability, "sample_input": sample_input})
        for gen in range(1, self.max_generations + 1):
            report = validate(spec)
            self.emit("test", f"gen {gen}: {report.summary}")
            if report.passed:
                skill = Skill(
                    name=self.registry.unique_name(slugify(spec.get("name", capability))),
                    description=spec.get("description", capability), code=spec["code"],
                    tests=spec["tests"], tags=list(spec.get("tags", [])), generation=gen,
                    history=[f"forged at generation {gen}"],
                )
                self.registry.add(skill)
                self.emit("born", f"{skill.name} survived {gen} generation(s)")
                return skill
            if gen == self.max_generations:
                break
            self.emit("mutate", "feeding the failure back to the smith")
            spec = self.llm.json("evolve", EVOLVE_SYSTEM, evolve_prompt(capability, spec, report.summary),
                                 {"capability": capability, "spec": spec, "report": report.summary})
        return None

    # --------------------------------------------------------------- invoke
    def _invoke(self, skill: Skill, inp: Any):
        out = execute(skill.code, [inp])[0]
        if out.ok:
            self.registry.record(skill.name, True)
            self.emit("exec", f"{skill.name}({inp!r}) = {out.value!r}")
            return out.value, None
        if self.registry.record(skill.name, False):
            self.emit("retire", f"{skill.name} moved to the graveyard")
        healed = self._heal(skill, inp, out.error or "unknown error")
        if healed:
            out = execute(skill.code, [inp])[0]
            if out.ok:
                self.registry.record(skill.name, True)
                self.emit("exec", f"{skill.name}({inp!r}) = {out.value!r}")
                return out.value, None
        return None, out.error

    def _heal(self, skill: Skill, inp: Any, error: str) -> bool:
        if skill.name not in self.registry.skills:
            return False
        self.emit("heal", f"{skill.name} crashed on {inp!r}: {error}")
        spec = skill_spec(skill)
        fixed = self.llm.json("evolve", EVOLVE_SYSTEM,
                              evolve_prompt(skill.description, spec, f"runtime failure on input {inp!r}: {error}"),
                              {"capability": skill.description, "spec": spec, "report": error})
        fixed["tests"] = skill.tests
        if validate(fixed).passed and execute(fixed["code"], [inp])[0].ok:
            self._adopt(skill, fixed, f"healed after crash on {inp!r}")
            return True
        return False

    def _adopt(self, skill: Skill, spec: dict, note: str) -> None:
        skill.parent = f"{skill.name}@g{skill.generation}"
        skill.generation += 1
        skill.code, skill.tests = spec["code"], spec["tests"]
        skill.history.append(f"g{skill.generation}: {note}")
        self.registry.save()
        self.emit("evolved", f"{skill.name} -> generation {skill.generation}")

    # ---------------------------------------------------------------- dream
    def dream(self) -> dict:
        """Sleep-time self-improvement: attack every skill with fresh edge cases."""
        stats = {"checked": 0, "hardened": 0, "evolved": 0, "failed": 0}
        for skill in self.registry.all():
            stats["checked"] += 1
            spec = skill_spec(skill)
            extra = self.llm.json("edge_tests", EDGE_SYSTEM, edge_prompt(spec), {"spec": spec}).get("tests", [])
            spec["tests"] = skill.tests + extra
            report = validate(spec)
            if report.passed:
                skill.tests = spec["tests"]
                stats["hardened"] += 1
                self.emit("dream", f"{skill.name} survived {len(extra)} new edge case(s)")
                continue
            self.emit("nightmare", f"{skill.name}: {report.summary}")
            fixed = self.llm.json("evolve", EVOLVE_SYSTEM, evolve_prompt(skill.description, spec, report.summary),
                                  {"capability": skill.description, "spec": spec, "report": report.summary})
            fixed["tests"] = spec["tests"]  # the expanded suite is now the law
            if validate(fixed).passed:
                self._adopt(skill, fixed, "evolved after a nightmare: " + report.summary[:80])
                stats["evolved"] += 1
            else:
                stats["failed"] += 1
                self.emit("warn", f"could not repair {skill.name} tonight")
        self.registry.save()
        return stats

    # ------------------------------------------------------------------ log
    def _log(self, r: RunResult) -> None:
        line = {"t": time.time(), "task": r.task, "ok": r.ok, "final": r.final,
                "steps": [{"skill": s.skill, "origin": s.origin} for s in r.steps]}
        with open(self.registry.home / "runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=repr) + "\n")
