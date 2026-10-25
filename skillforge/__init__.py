"""Skillforge: an agent that forges, tests, evolves and dreams about its own tools."""
from .agent import ForgeAgent, RunResult, StepResult
from .registry import Registry, Skill

__version__ = "0.1.0"
__all__ = ["ForgeAgent", "Registry", "Skill", "RunResult", "StepResult"]
