from skillforge.registry import Registry, Skill

def mk(name, desc, tags=()):
    return Skill(name=name, description=desc, code="def run(x):\n    return x\n",
                 tests=[], tags=list(tags))

def test_search_finds_relevant_skill(tmp_path):
    r = Registry(tmp_path)
    r.add(mk("count_vowels", "Count the vowels in a text"))
    r.add(mk("is_prime", "Check whether a number is prime"))
    assert r.best("how many vowels are in this text").name == "count_vowels"
    assert r.best("render a 3d pony in blender") is None

def test_persistence(tmp_path):
    Registry(tmp_path).add(mk("a_skill", "does a thing"))
    assert Registry(tmp_path).get("a_skill") is not None

def test_fitness_and_retirement(tmp_path):
    r = Registry(tmp_path)
    r.add(mk("flaky", "flaky tool"))
    retired = [r.record("flaky", False) for _ in range(5)]
    assert retired[-1] and r.get("flaky") is None
    assert r.graveyard[0]["name"] == "flaky"
    assert r.unique_name("flaky") == "flaky_2"
