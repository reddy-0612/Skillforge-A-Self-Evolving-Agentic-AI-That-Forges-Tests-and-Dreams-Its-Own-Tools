# 🔨 Skillforge: A Self-Evolving Agentic AI

**An agentic AI that doesn't just *use* tools: it forges them, tests them, evolves them when they fail, and dreams about its own mistakes.**

Most agent frameworks ship with a fixed toolbox. Skillforge starts with an *empty* one.
When a task needs a capability the agent doesn't have, it writes the tool, proves it works in a sandbox, and keeps it forever in a persistent **Skill Museum**. The agent literally gets more capable the more you use it.

```text
 ┌──────────┐   ┌──────────────┐  match   ┌───────────────┐
 │  Planner │──▶│ Skill Museum │─────────▶│ Reuse (fast)  │──┐
 └──────────┘   └──────┬───────┘          └───────────────┘  │
                       │ miss                                 ▼
                       ▼                              ┌─────────────┐
              ┌─────────────────┐  fail + report      │  Sandboxed  │──▶ answer
              │ Forge (write    │◀────────────┐       │  execution  │
              │ code + tests)   │             │       └──────┬──────┘
              └────────┬────────┘      ┌──────┴─────┐        │ crash
                       ▼               │  Mutate    │        ▼
              ┌─────────────────┐ fail │ (LLM fixes │   ┌─────────┐
              │ Sandbox tests   │─────▶│  own code) │   │  Heal   │
              └────────┬────────┘      └────────────┘   └─────────┘
                       │ pass                       
                       ▼                            🌙 `dream`: attack every skill with
                 stored with fitness,                  fresh edge cases, evolve the losers
                 lineage & history                  🪦 chronically failing skills retire
```

## What makes it different

| Idea | What it means |
|---|---|
| 🔨 **Tool forging** | The agent writes new Python tools at runtime, with its own unit tests. |
| 🧪 **Proof before release** | A tool is only accepted if it passes its tests inside an isolated subprocess. |
| 🧬 **Evolution loop** | Failing code + the exact failure report are fed back to the model for repair, up to N generations. |
| 🏛 **Skill Museum** | Skills persist as JSON with versions, lineage, history and a Laplace-smoothed **fitness score**. |
| 🌙 **Dreaming** | Offline, sleep-time self-improvement: the agent generates adversarial edge cases against its *own* skills and evolves any that break. |
| 🪦 **Natural selection** | Skills with poor fitness are retired to a graveyard. |
| 🔌 **Zero-key demo** | A built-in mock brain lets the entire loop run offline with **no dependencies**. Plug in Claude for open-ended tasks. |

## Quick start

```bash
git clone https://github.com/reddy-0612/skillforge-self-evolving-agent && cd skillforge-self-evolving-agent
# 1) Offline demo, no API key, no dependencies
python -m skillforge --mock run "Reverse the words in 'the quick brown fox' then count the vowels"

# 2) With a real LLM (Claude): arbitrary pure-computation tasks
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python -m skillforge run "Convert 'hello world' to title case, then count its unique letters"

# Inspect, improve, reset
python -m skillforge museum     # browse what the agent has learned
python -m skillforge dream      # sleep-time self-improvement
python -m skillforge reset
```

Optional: `export SKILLFORGE_MODEL=<model-id>` to choose the Claude model, `SKILLFORGE_HOME=<dir>` to choose where the museum lives.

## Real output (offline mock brain)

**Forging two tools and chaining them:**
```text
🎯 task      Reverse the words in 'the quick brown fox' then count the vowels
🧭 plan      Reverse the order of the words in a text -> Count the vowels in a text
🔨 forge     no skill matches: 'Reverse the order of the words in a text'
🧪 test      gen 1: 3/3 tests passed
✨ born      reverse_words survived 1 generation(s)
⚙️  exec      reverse_words('the quick brown fox') = 'fox brown quick the'
🔨 forge     no skill matches: 'Count the vowels in a text'
🧪 test      gen 1: 3/3 tests passed
✨ born      count_vowels survived 1 generation(s)
⚙️  exec      count_vowels('fox brown quick the') = 5
🏁 answer    5
```
Run it again and both steps become `♻️ reuse` with zero forging.

**A buggy first draft is caught by its own tests and mutated before it ever ships:**
```text
🧪 test      gen 1: input=1 expected=False got=True
🧬 mutate    feeding the failure back to the smith
🧪 test      gen 2: 4/4 tests passed
✨ born      is_prime survived 2 generation(s)
```

**Dreaming finds a blind spot nobody asked about:**
```text
$ python -m skillforge run "Is 'Was it a car or a cat I saw?' a palindrome?"
✅ False                       # <- the first-draft tool was wrong!

$ python -m skillforge dream
🌙 dream     reverse_words survived 2 new edge case(s)
😱 nightmare is_palindrome: input='Was it a car or a cat I saw?' expected=True got=False
🦋 evolved   is_palindrome -> generation 2

$ python -m skillforge run "Is 'Was it a car or a cat I saw?' a palindrome?"
♻️  reuse     is_palindrome (gen 2, fitness 0.67)
✅ True
```

## Project layout

```text
skillforge/
├── agent.py      # the loop: plan → reuse/forge → test → mutate → execute → heal → dream
├── sandbox.py    # AST screening + isolated subprocess + import allowlist + limits
├── registry.py   # Skill Museum: persistence, retrieval, fitness, retirement
├── prompts.py    # all LLM prompts (JSON-only protocols)
├── llm.py        # Claude backend (swap in any model: implement `.json(...)`)
├── mock_llm.py   # offline brain with two deliberately flawed first drafts
└── cli.py        # run | museum | dream | reset
tests/            # 15 tests: sandbox, registry, full agent loop
```

## Extending it

- **New brain:** any object with `json(kind, system, user, ctx) -> dict` works (OpenAI, Ollama, ...).
- **Better retrieval:** `Registry.search` is a lightweight token-overlap scorer. Swap in embeddings for large museums.
- **Skill composition:** have `dream` merge frequently chained skills into composite tools.
- **Shared museums:** publish `registry.json` so agents can inherit each other's vetted skills.
- **Stronger isolation:** run inside Docker/gVisor/Firecracker for untrusted use.

## Safety notes

Skillforge executes model-written code. The sandbox is layered (AST allowlist, no dunder access, restricted builtins, import allowlist, separate isolated process, CPU/memory/time limits), but it is **defense in depth, not a hardened security boundary**. Tools are pure functions on JSON: no network, files or clock. If you run untrusted tasks or models, put the whole process in a container.

## Development

```bash
pip install pytest && python -m pytest -q
```

## License

MIT
