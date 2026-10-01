"""Long weighted lexical queries are scored one weight class at a time (E056)."""
import importlib
import random

from npk.pack import compile_pack, update_pack
from npk.pack.format import open_pack

selection = importlib.import_module("npk.pack.select")

FILLER = [f"absentword{i}" for i in range(140)]     # phrases that match nothing: force the split


def _single(con, terms, limit, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(selection, "LEXICAL_SPLIT_MIN_PHRASES", 10**9)
        return selection._rank_lexical_terms(con, terms, limit)


def _paths(con, ids):
    rows = dict(con.execute(
        "SELECT b.id, f.path FROM blocks b JOIN files f ON f.id=b.file_id "
        f"WHERE b.id IN ({','.join('?' * len(ids))})", ids).fetchall())
    return [rows[i] for i in ids]


def test_weights_decide_the_order(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "once.py").write_text("def once():\n    return 'alpha ' + 'gamma delta'\n")
    (src / "thrice.py").write_text("def thrice():\n    return 'beta beta beta'\n")
    for i in range(6):
        (src / f"other{i}.py").write_text(f"def other_{i}():\n    return {i}\n")
    compile_pack(src, tmp_path / "p.npk")
    terms = ["alpha"] * 3 + ["beta"] + FILLER            # alpha weighted x3 (a title term)
    with open_pack(tmp_path / "p.npk") as con:
        split = selection._rank_lexical_terms(con, terms, 60)
        assert split == _single(con, terms, 60, monkeypatch)
        assert _paths(con, split)[0] == "once.py"         # 3 x alpha outranks beta x3 once


def test_ties_are_ordered_by_path_across_the_limit(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    for name in "abcde":
        (src / f"{name}.py").write_text("def shared():\n    return 'kappa lambda'\n")
    compile_pack(src, tmp_path / "p.npk")
    # Re-indexing a.py gives its blocks the highest row ids: row order is no longer path order.
    (src / "a.py").write_text("def shared():\n    return 'kappa lambda'\n\n\ndef extra():\n    return 1\n")
    update_pack(tmp_path / "p.npk", src)
    terms = ["kappa", "lambda"] + FILLER
    with open_pack(tmp_path / "p.npk") as con:
        for limit in (1, 2, 4, 60):
            split = selection._rank_lexical_terms(con, terms, limit)
            assert split == _single(con, terms, limit, monkeypatch), limit
        assert _paths(con, selection._rank_lexical_terms(con, terms, 2)) == ["a.py", "b.py"]


def test_random_long_queries_rank_as_the_single_query(tmp_path, monkeypatch):
    rng = random.Random(56)
    vocab = [f"word{i}" for i in range(400)]
    src = tmp_path / "src"
    src.mkdir()
    for f in range(40):
        body = "\n\n\n".join(
            f"def f{f}_{k}():\n    return '{' '.join(rng.choices(vocab, k=rng.randint(3, 60)))}'"
            for k in range(rng.randint(1, 6)))
        (src / f"m{f:02d}.py").write_text(body + "\n")
    compile_pack(src, tmp_path / "p.npk")
    with open_pack(tmp_path / "p.npk") as con:
        for _ in range(5):
            distinct = rng.sample(vocab, 150)
            terms = [t for t in distinct for _ in range(rng.choice((1, 1, 2, 3, 5)))]
            assert len(terms) > selection.LEXICAL_SPLIT_MIN_PHRASES
            for limit in (5, 60, 1000):
                assert selection._rank_lexical_terms(con, terms, limit) == _single(con, terms, limit, monkeypatch)


def test_short_queries_keep_the_single_query(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.py").write_text("def x():\n    return 'alpha'\n")
    compile_pack(src, tmp_path / "p.npk")
    with open_pack(tmp_path / "p.npk") as con:
        calls = []
        con.set_trace_callback(calls.append)
        selection._rank_lexical_terms(con, ["alpha"] * 3, 5)
        con.set_trace_callback(None)
    assert sum("MATCH" in c for c in calls) == 1
