from __future__ import annotations

import argparse
import os
import shutil
import sys

from .agent import ForgeAgent
from .mock_llm import MockLLM
from .registry import Registry

ICONS = {"task": "🎯", "plan": "🧭", "reuse": "♻️ ", "forge": "🔨", "test": "🧪", "mutate": "🧬",
         "born": "✨", "exec": "⚙️ ", "heal": "🩹", "evolved": "🦋", "answer": "🏁", "dream": "🌙",
         "nightmare": "😱", "retire": "🪦", "warn": "⚠️ "}
COLORS = {"forge": "33", "mutate": "35", "born": "32", "answer": "1;32", "nightmare": "31",
          "evolved": "36", "warn": "31", "retire": "31", "dream": "34", "heal": "35"}


def printer(kind: str, msg: str) -> None:
    text = f"{ICONS.get(kind, '•')} {kind:<9} {msg}"
    if sys.stdout.isatty() and kind in COLORS:
        text = f"\033[{COLORS[kind]}m{text}\033[0m"
    print(text)


def build_llm(force_mock: bool):
    if not force_mock and os.getenv("ANTHROPIC_API_KEY"):
        try:
            from .llm import AnthropicLLM
            return AnthropicLLM(), "Claude"
        except ImportError:
            print("⚠️  `pip install anthropic` to use Claude; falling back to the offline mock.\n")
    return MockLLM(), "offline mock"


def bar(x: float, width: int = 10) -> str:
    n = round(x * width)
    return "█" * n + "░" * (width - n)


def museum(reg: Registry) -> None:
    if not reg.all():
        print("The museum is empty. Run a task first:  python -m skillforge run \"...\"")
    for s in reg.all():
        print(f"\n🏛  {s.name}  gen {s.generation}  {bar(s.fitness)} {s.fitness:.2f}  ({s.uses} uses)")
        print(f"    {s.description}")
        for h in s.history:
            print(f"    · {h}")
    if reg.graveyard:
        print("\n🪦 Graveyard: " + ", ".join(g["name"] for g in reg.graveyard))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="skillforge", description="An agent that forges, evolves and dreams about its own tools.")
    p.add_argument("--home", default=os.getenv("SKILLFORGE_HOME", "skillforge_home"), help="where skills are stored")
    p.add_argument("--mock", action="store_true", help="force the offline mock brain")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="solve a task"); r.add_argument("task")
    sub.add_parser("museum", help="list every skill the agent has forged")
    sub.add_parser("dream", help="sleep-time self-improvement: attack skills with new edge cases")
    sub.add_parser("reset", help="wipe the skill museum")
    a = p.parse_args(argv)

    reg = Registry(a.home)
    if a.cmd == "museum":
        return museum(reg)
    if a.cmd == "reset":
        shutil.rmtree(a.home, ignore_errors=True)
        return print("🧹 museum wiped")
    llm, name = build_llm(a.mock)
    print(f"brain: {name} | museum: {a.home} ({len(reg.all())} skills)\n")
    agent = ForgeAgent(llm, reg, printer)
    if a.cmd == "run":
        res = agent.solve(a.task)
        if res.ok:
            print(f"\n✅ {res.final}")
        else:
            sys.exit(1)
    elif a.cmd == "dream":
        print("🌙 closing eyes...\n")
        print("\nmorning report:", agent.dream())
