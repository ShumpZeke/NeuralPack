"""Independent update acceptance: compare postings, document lengths and responses.

Read-only artifacts, with temporary FTS5 vocabulary views. No benchmark timing
is collected during this audit. Search rowids are deliberately not source IDs.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def compare_indexes(actual, expected):
    with closing(sqlite3.connect(Path(actual).resolve().as_uri()+"?mode=ro", uri=True)) as con:
        con.execute("ATTACH DATABASE ? AS expected", (Path(expected).resolve().as_uri()+"?mode=ro",))
        con.execute("CREATE VIRTUAL TABLE temp.actual_terms USING fts5vocab(main,lexical,'instance')")
        con.execute("CREATE VIRTUAL TABLE temp.expected_terms USING fts5vocab(expected,lexical,'instance')")
        counts = []
        for schema, terms in (("main", "actual_terms"), ("expected", "expected_terms")):
            assert con.execute(f"SELECT count(*) FROM {schema}.lexical l LEFT JOIN {schema}.blocks b ON b.id=l.rowid WHERE b.id IS NULL").fetchone()[0] == 0, "orphan index document"
            assert con.execute(f"SELECT count(*) FROM {schema}.blocks WHERE id NOT IN (SELECT rowid FROM {schema}.lexical)").fetchone()[0] == 0, "missing index document"
            counts.append(con.execute(f"SELECT count(*) FROM {terms}").fetchone()[0])
            assert con.execute(f"SELECT count(*) FROM {terms} t LEFT JOIN {schema}.lexical l ON l.rowid=t.doc WHERE l.rowid IS NULL").fetchone()[0] == 0, "orphan index posting"
        assert counts[0] == counts[1], "posting count mismatch"
        selects = []
        for schema, terms in (("main", "actual_terms"), ("expected", "expected_terms")):
            selects.append(f"SELECT t.term,f.path,b.ordinal,t.col,t.offset FROM {terms} t JOIN {schema}.lexical l ON l.rowid=t.doc JOIN {schema}.blocks b ON b.id=l.rowid JOIN {schema}.files f ON f.id=b.file_id")
        for left, right in (selects, selects[::-1]):
            assert con.execute(left+" EXCEPT "+right+" LIMIT 1").fetchone() is None, "search positions mismatch"
        selects = []
        for schema in ("main", "expected"):
            selects.append(f"SELECT f.path,b.ordinal,d.sz FROM {schema}.lexical_docsize d JOIN {schema}.lexical l ON l.rowid=d.id JOIN {schema}.blocks b ON b.id=l.rowid JOIN {schema}.files f ON f.id=b.file_id")
        for left, right in (selects, selects[::-1]):
            assert con.execute(left+" EXCEPT "+right+" LIMIT 1").fetchone() is None, "search document lengths mismatch"
        # External-content FTS5 may retain tombstone pages after a delete or a
        # rebuild. Compare the logical postings and document lengths above;
        # raw lexical_data bytes are an implementation detail of segment
        # history and are not observable retrieval semantics.
        assert con.execute("SELECT * FROM lexical_config ORDER BY k").fetchall() == con.execute("SELECT * FROM expected.lexical_config ORDER BY k").fetchall(), "search configuration mismatch"
        return counts[0]


def normalized_response(path, query, budget):
    from npk.pack import PackSelector
    result = PackSelector(path).select(query, budget_tokens=budget).as_dict()
    result.pop("latency_ms")
    for evidence in result["evidence"]:
        evidence.pop("block_id")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    plan = json.loads((root/"plan.json").read_text())
    raw = json.loads((root/"results.json").read_text())
    digest = hashlib.sha256((root/"plan.json").read_bytes()).hexdigest()
    assert digest == raw["plan_sha256"] == (root/"plan.sha256").read_text()
    candidate = json.loads((root/"candidate.json").read_text())
    for arm, hashes in (("champion", plan["champion_hashes"]), ("candidate", candidate["hashes"])):
        for name, expected in hashes.items():
            assert hashlib.sha256((root/arm/name).read_bytes()).hexdigest() == expected
    rows = []
    for corpus in plan["corpora"]:
        for trial in range(plan["trials"]):
            for case in plan["cases"]:
                champion = root/"workers"/f"champion-{corpus}-{trial}"/f"{case}.npk"
                updated = root/"workers"/f"candidate-{corpus}-{trial}"/f"{case}.npk"
                fresh = updated.with_name(f"{case}-fresh.npk")
                postings = [compare_indexes(updated, reference) for reference in (champion, fresh)]
                assert postings[0] == postings[1]
                checks = 0
                for query in plan["queries"]:
                    for budget in plan["budgets"]:
                        responses = [normalized_response(path, query, budget) for path in (champion, updated, fresh)]
                        assert responses[0] == responses[1] == responses[2], "observable response changed"
                        checks += 1
                rows.append({"corpus": corpus, "trial": trial, "case": case,
                             "postings": postings[0], "three_way_response_checks": checks,
                             "artifacts": {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                           for p in (champion, updated, fresh)}})
                print({k: v for k, v in rows[-1].items() if k != "artifacts"}, flush=True)
    output = {"status": "PASS", "plan_sha256": digest,
              "audit_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "postings_checked": sum(row["postings"]*2 for row in rows),
              "three_way_response_checks": sum(row["three_way_response_checks"] for row in rows),
              "rows": rows, "generative_calls": 0}
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
