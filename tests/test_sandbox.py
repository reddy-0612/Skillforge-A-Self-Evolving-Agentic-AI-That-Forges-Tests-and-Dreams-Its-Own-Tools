from skillforge.sandbox import check_code, execute, UnsafeCode
import pytest

def test_runs_simple_code():
    out = execute("def run(x):\n    return x * 2\n", [2, 5])
    assert [o.value for o in out] == [4, 10]

def test_blocks_dangerous_imports():
    assert not execute("import os\ndef run(x):\n    return os.getcwd()\n", [1])[0].ok

def test_blocks_open_and_dunders():
    with pytest.raises(UnsafeCode):
        check_code("def run(x):\n    return open('/etc/passwd').read()\n")
    with pytest.raises(UnsafeCode):
        check_code("def run(x):\n    return ().__class__.__bases__\n")

def test_requires_run_function():
    with pytest.raises(UnsafeCode):
        check_code("x = 1\n")

def test_timeout():
    out = execute("def run(x):\n    while True:\n        pass\n", [1], timeout=1.0)
    assert not out[0].ok and "Timeout" in out[0].error

def test_runtime_error_is_captured():
    out = execute("def run(x):\n    return 1 / x\n", [0, 2])
    assert not out[0].ok and out[1].value == 0.5

def test_print_does_not_corrupt_results():
    out = execute("def run(x):\n    print('noise')\n    return x\n", [3])
    assert out[0].value == 3
