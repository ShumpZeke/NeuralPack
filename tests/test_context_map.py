"""Context map (E017): ranked places beyond the evidence, listed without text."""
import json
import subprocess
import sys

import pytest

from npk.pack import PackSelector, compile_pack

QUERY = "retry backoff jitter schedule for the Engine scheduler"


def _corpus(root):
    (root / "pkg").mkdir()
    methods = "\n".join(
        f"    def step_{i}(self, attempt):\n        '''Retry backoff step {i} with jitter.'''\n"
        f"        delay = attempt * {i + 1}\n        return delay + {i}\n" for i in range(30))
    (root / "pkg" / "engine.py").write_text(f"class Engine:\n    '''Scheduler with retry backoff.'''\n\n{methods}\n")
    for i in range(25):
        (root / "pkg" / f"mod{i}.py").write_text(
            f"def schedule_{i}(value):\n    '''retry schedule helper {i} with backoff and jitter'''\n"
            + "".join(f"    value = value + {j}\n" for j in range(12)) + "    return value\n")


@pytest.fixture()
def pack(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _corpus(src)
    out = tmp_path / "p.npk"
    compile_pack(src, out)
    return out


def test_map_lists_ranked_places_not_already_shown(pack):
    with PackSelector(str(pack), enable_cache=False) as selector:
        text_only = selector.select(QUERY, budget_tokens=750)
        mapped = selector.select(QUERY, budget_tokens=1000, map_share=0.25)
    assert [e.span for e in mapped.evidence] == [e.span for e in text_only.evidence]
    assert mapped.locations and mapped.map_tokens > 0
    assert mapped.total_tokens + mapped.map_tokens <= 1000
    shown = {e.span for e in mapped.evidence}
    assert not shown & {loc.span for loc in mapped.locations}
    assert sum(len(loc.line()) // 4 + 1 for loc in mapped.locations) == mapped.map_tokens
    # A large class is mapped as its members, not as one opaque block.
    assert any(loc.path == "pkg/engine.py" and loc.name.startswith("Engine.") for loc in mapped.locations) or \
        any(e.path == "pkg/engine.py" for e in mapped.evidence)
    result = mapped.as_dict(include_text=False)
    assert result["map_tokens"] == mapped.map_tokens and len(result["locations"]) == len(mapped.locations)


def test_without_map_share_the_result_is_unchanged(pack):
    with PackSelector(str(pack), enable_cache=False) as selector:
        plain = selector.select(QUERY, budget_tokens=1000)
    assert plain.locations == [] and plain.map_tokens == 0
    assert "locations" not in plain.as_dict() and "map_tokens" not in plain.as_dict()


@pytest.mark.parametrize("share", [-0.1, 1.0, 1.5, True, "0.2"])
def test_invalid_map_share_is_rejected(pack, share):
    with PackSelector(str(pack), enable_cache=False) as selector:
        with pytest.raises(ValueError):
            selector.select(QUERY, budget_tokens=1000, map_share=share)


def test_cli_map_share(pack):
    out = subprocess.run([sys.executable, "-m", "npk.cli", "query", str(pack), QUERY, "--budget", "1000",
                          "--map-share", "0.25"], capture_output=True, text=True, check=True).stdout
    result = json.loads(out)
    assert result["locations"] and result["map_tokens"] > 0
