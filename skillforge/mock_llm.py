"""Offline stand-in for an LLM so the whole loop runs with zero API keys.

It knows five tiny skills. Two of its first drafts are deliberately flawed so you
can watch the agent's immune system work:
  * is_prime  : fails its OWN tests (1 is not prime)  -> repaired at forge time
  * palindrome: passes its own weak tests but has a blind spot -> found by `dream`
"""
from __future__ import annotations

import copy
import re

RECIPES = {
    "reverse": dict(
        name="reverse_words", tags=["text", "words", "reverse"],
        description="Reverse the order of the words in a text",
        code='def run(x):\n    return " ".join(reversed(str(x).split()))\n',
        tests=[{"input": "hello big world", "expected": "world big hello"},
               {"input": "single", "expected": "single"},
               {"input": "a b", "expected": "b a"}],
        edge=[{"input": "  spaced   out  ", "expected": "out spaced"}, {"input": "", "expected": ""}],
    ),
    "vowel": dict(
        name="count_vowels", tags=["text", "vowels", "count"],
        description="Count the vowels in a text",
        code='def run(x):\n    return sum(1 for c in str(x).lower() if c in "aeiou")\n',
        tests=[{"input": "hello", "expected": 2}, {"input": "rhythm", "expected": 0},
               {"input": "Queue", "expected": 4}],
        edge=[{"input": "AEIOU", "expected": 5}, {"input": "", "expected": 0}],
    ),
    "prime": dict(
        name="is_prime", tags=["number", "prime", "math"],
        description="Check whether a number is prime",
        code=("def run(n):\n    n = int(n)\n    if n < 1:\n        return False\n"
              "    for i in range(2, int(n ** 0.5) + 1):\n        if n % i == 0:\n            return False\n"
              "    return True\n"),
        fixed=("def run(n):\n    n = int(n)\n    if n < 2:\n        return False\n"
               "    for i in range(2, int(n ** 0.5) + 1):\n        if n % i == 0:\n            return False\n"
               "    return True\n"),
        tests=[{"input": 7, "expected": True}, {"input": 1, "expected": False},
               {"input": 12, "expected": False}, {"input": 97, "expected": True}],
        edge=[{"input": 0, "expected": False}, {"input": 2, "expected": True}, {"input": -7, "expected": False}],
    ),
    "fibonacci": dict(
        name="nth_fibonacci", tags=["number", "fibonacci", "math"],
        description="Compute the nth Fibonacci number",
        code=("def run(n):\n    n = int(n)\n    a, b = 0, 1\n    for _ in range(n):\n"
              "        a, b = b, a + b\n    return a\n"),
        tests=[{"input": 0, "expected": 0}, {"input": 1, "expected": 1}, {"input": 10, "expected": 55}],
        edge=[{"input": 2, "expected": 1}, {"input": 20, "expected": 6765}],
    ),
    "palindrome": dict(
        name="is_palindrome", tags=["text", "palindrome"],
        description="Check whether a text is a palindrome",
        code='def run(x):\n    s = str(x)\n    return s == s[::-1]\n',
        fixed=('def run(x):\n    s = [c.lower() for c in str(x) if c.isalnum()]\n    return s == s[::-1]\n'),
        tests=[{"input": "racecar", "expected": True}, {"input": "hello", "expected": False},
               {"input": "noon", "expected": True}],
        edge=[{"input": "Was it a car or a cat I saw?", "expected": True}, {"input": "", "expected": True}],
    ),
}
NUMERIC = {"prime", "fibonacci"}
CAPABILITY = {k: v["description"] for k, v in RECIPES.items()}


def _key_for(text: str):
    t = text.lower()
    for key in RECIPES:
        if key in t:
            return key
    return None


class MockLLM:
    def json(self, kind: str, system: str, user: str, ctx: dict | None = None) -> dict:
        ctx = ctx or {}
        return getattr(self, f"_{kind}")(ctx)

    def _plan(self, ctx):
        task = ctx["task"]
        t = task.lower()
        found = sorted((t.find(k), k) for k in RECIPES if k in t)
        if not found:
            return {"steps": [], "note": "The offline mock only knows: " + ", ".join(RECIPES)
                    + ". Set ANTHROPIC_API_KEY to unlock arbitrary tasks."}
        quoted = re.search(r"""['"\u201c\u2018](.+?)['"\u201d\u2019]""", task)
        number = re.search(r"-?\d+", task)
        steps = []
        for i, (_, key) in enumerate(found):
            if i:
                value = "$prev"
            elif key in NUMERIC:
                value = int(number.group()) if number else 10
            else:
                value = quoted.group(1) if quoted else task
            steps.append({"capability": CAPABILITY[key], "input": value})
        return {"steps": steps}

    def _forge(self, ctx):
        key = _key_for(ctx["capability"])
        if key is None:
            raise RuntimeError("mock LLM cannot forge: " + ctx["capability"])
        r = copy.deepcopy(RECIPES[key])
        return {k: r[k] for k in ("name", "description", "tags", "code", "tests")}

    def _evolve(self, ctx):
        spec = copy.deepcopy(ctx["spec"])
        key = _key_for(spec.get("name", "") + " " + ctx.get("capability", ""))
        if key and "fixed" in RECIPES[key]:
            spec["code"] = RECIPES[key]["fixed"]
        return spec

    def _edge_tests(self, ctx):
        key = _key_for(ctx["spec"].get("name", ""))
        return {"tests": copy.deepcopy(RECIPES[key]["edge"]) if key else []}
