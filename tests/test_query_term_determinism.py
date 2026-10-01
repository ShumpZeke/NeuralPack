"""Query analysis must not depend on the process's string-hash seed."""
import os
import subprocess
import sys

CODE = """
import importlib
sel = importlib.import_module("npk.pack.select")
q = "Calls to `models.query.QuerySet` and `db.backends.base` and `core.mail.send` fail"
print(sel._lexical_terms(None, q), sel._whole_lexical_terms(q))
"""


def test_explicit_literal_order_is_independent_of_hash_seed():
    outputs = set()
    for seed in ("1", "2", "3", "4", "5", "6"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        outputs.add(subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True,
                                   check=True, env=env).stdout)
    assert len(outputs) == 1
    assert "'models.query.queryset', 'db.backends.base', 'core.mail.send'" in outputs.pop()


def test_long_queries_keep_the_first_distinct_terms_and_explicit_literals():
    import importlib
    import string
    sel = importlib.import_module("npk.pack.select")

    def word(i):   # letters only, so each word is exactly one analyzed term
        letters = ""
        for _ in range(3):
            i, r = divmod(i, 26)
            letters += string.ascii_lowercase[r]
        return "w" + letters

    words = [word(i) for i in range(sel.MAX_QUERY_TERMS + 88)]
    query = "Titleword\n" + " ".join(words) + " `models.query.QuerySet`"
    terms = sel._lexical_terms(None, query)
    literal = ["models", "query", "queryset", "models.query.queryset"]   # "set" (a camel part) is not a literal
    assert terms[:sel.MAX_QUERY_TERMS] == ["titleword", *words[:sel.MAX_QUERY_TERMS - 1]]
    assert terms[sel.MAX_QUERY_TERMS:] == literal
    short = "Titleword\n" + " ".join(words[:100])
    assert sel._lexical_terms(None, short) == ["titleword", *words[:100]]
