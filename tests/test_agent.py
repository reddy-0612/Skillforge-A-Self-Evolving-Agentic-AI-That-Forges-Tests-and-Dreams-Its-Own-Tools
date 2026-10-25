from skillforge import ForgeAgent, Registry
from skillforge.mock_llm import MockLLM

def agent(tmp_path, events=None):
    emit = (lambda k, m: events.append(k)) if events is not None else None
    return ForgeAgent(MockLLM(), Registry(tmp_path), emit)

def test_chained_task_forges_two_tools(tmp_path):
    res = agent(tmp_path).solve("Reverse the words in 'the quick brown fox' then count the vowels")
    assert res.ok and res.final == 5
    assert [s.origin for s in res.steps] == ["forged", "forged"]

def test_second_run_reuses_skills(tmp_path):
    task = "Reverse the words in 'the quick brown fox' then count the vowels"
    agent(tmp_path).solve(task)
    res = agent(tmp_path).solve(task)  # fresh agent, same museum on disk
    assert [s.origin for s in res.steps] == ["reused", "reused"]

def test_buggy_first_draft_is_mutated_before_release(tmp_path):
    events = []
    res = agent(tmp_path, events).solve("Is 1 a prime number?")
    assert res.ok and res.final is False
    assert "mutate" in events
    assert Registry(tmp_path).get("is_prime").generation == 2

def test_dream_repairs_hidden_bug(tmp_path):
    task = "Is 'Was it a car or a cat I saw?' a palindrome?"
    a = agent(tmp_path)
    assert a.solve(task).final is False          # blind spot in the first draft
    stats = a.dream()
    assert stats["evolved"] == 1
    assert agent(tmp_path).solve(task).final is True

def test_unknown_task_degrades_gracefully(tmp_path):
    res = agent(tmp_path).solve("write me a sonnet")
    assert not res.ok and "mock" in res.note.lower()
