"""Defense-in-depth sandbox for running LLM-written code.

Layers: (1) static AST screening, (2) a separate isolated Python process,
(3) a stripped-down builtins table with an import allowlist, (4) wall-clock,
CPU and memory limits (POSIX).

Honest note: this is NOT a hardened security boundary. If you point the agent
at an untrusted model or untrusted tasks, run the whole thing inside Docker/gVisor.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, List, Optional

ALLOWED_IMPORTS = {
    "math", "re", "json", "itertools", "collections", "statistics", "string",
    "functools", "datetime", "fractions", "decimal", "heapq", "bisect",
    "textwrap", "unicodedata", "operator",
}
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "input", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "breakpoint", "exit", "quit", "memoryview",
}
MARKER = "@@SKILLFORGE_RESULT@@"


class UnsafeCode(Exception):
    pass


@dataclass
class Outcome:
    ok: bool
    value: Any = None
    error: Optional[str] = None


def check_code(code: str) -> None:
    """Raise UnsafeCode if the source breaks the rules."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise UnsafeCode(f"SyntaxError: {e}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    raise UnsafeCode(f"import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in ALLOWED_IMPORTS:
                raise UnsafeCode(f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or (node.id.startswith("__") and node.id != "__name__"):
                raise UnsafeCode(f"use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise UnsafeCode(f"access to dunder attribute '{node.attr}' is not allowed")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body):
        raise UnsafeCode("code must define a top-level function `run(x)`")


_HARNESS = r'''
import sys, json, builtins
ALLOWED = set(json.loads(sys.argv[1]))
_real_import = builtins.__import__

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] not in ALLOWED:
        raise ImportError("import of %r is blocked" % name)
    return _real_import(name, globals, locals, fromlist, level)

_names = """abs all any bin bool bytes chr dict divmod enumerate filter float format
frozenset hash hex int isinstance iter len list map max min next object oct ord pow
print range repr reversed round set slice sorted str sum tuple zip type
ArithmeticError AssertionError Exception IndexError KeyError OverflowError
RuntimeError StopIteration TypeError ValueError ZeroDivisionError
True False None __build_class__""".split()
SAFE = {n: getattr(builtins, n) for n in _names if hasattr(builtins, n)}
SAFE["__import__"] = _safe_import

payload = json.loads(sys.stdin.read())
ns = {"__builtins__": SAFE, "__name__": "forged_skill"}
results = []
try:
    exec(compile(payload["code"], "<skill>", "exec"), ns)
    fn = ns["run"]
    for x in payload["inputs"]:
        try:
            results.append({"ok": True, "value": fn(x)})
        except BaseException as e:
            results.append({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
except BaseException as e:
    results = [{"ok": False, "error": "load error - %s: %s" % (type(e).__name__, e)} for _ in payload["inputs"]]
sys.stdout.write("\n" + "''' + MARKER + r'''" + json.dumps(results, default=repr) + "\n")
'''


def _limits(memory_mb: int, cpu_s: float):
    def apply() -> None:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_s) + 1, int(cpu_s) + 1))
            resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024,) * 2)
        except Exception:
            pass
    return apply


def execute(code: str, inputs: List[Any], timeout: float = 5.0, memory_mb: int = 512) -> List[Outcome]:
    """Run `run(x)` from `code` for each input inside an isolated subprocess."""
    def fail(msg: str) -> List[Outcome]:
        return [Outcome(False, error=msg) for _ in inputs]

    try:
        check_code(code)
    except UnsafeCode as e:
        return fail(f"rejected: {e}")

    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT")}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "harness.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_HARNESS)
        try:
            proc = subprocess.run(
                [sys.executable, "-I", path, json.dumps(sorted(ALLOWED_IMPORTS))],
                input=json.dumps({"code": code, "inputs": inputs}),
                capture_output=True, text=True, timeout=timeout, cwd=tmp, env=env,
                preexec_fn=_limits(memory_mb, timeout) if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired:
            return fail(f"TimeoutError: exceeded {timeout}s")
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(MARKER):
            try:
                raw = json.loads(line[len(MARKER):])
            except json.JSONDecodeError:
                break
            return [Outcome(r["ok"], r.get("value"), r.get("error")) for r in raw]
    tail = (proc.stderr or "no output").strip().splitlines()[-1:] or ["no output"]
    return fail(f"sandbox crashed: {tail[0]}")
