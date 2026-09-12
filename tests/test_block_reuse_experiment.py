"""The research adapter must preserve fresh-build behavior and rollback."""
import importlib
import pytest
from benchmarks.block_reuse import update_reused
from npk.pack import compile_pack,PackSelector,verify
from npk.pack.format import open_pack,load_blocks,PackError


def representation(pack):
    with open_pack(pack) as con:
        blocks=load_blocks(con)
        assert not con.execute("SELECT 1 FROM files WHERE path LIKE '__npk_research_pending_%'").fetchall()
        symbols=[tuple(r) for r in con.execute('SELECT f.path,b.ordinal,s.name,s.kind,s.is_def FROM symbols s JOIN blocks b ON b.id=s.block_id JOIN files f ON f.id=b.file_id ORDER BY f.path,b.ordinal,s.name,s.kind,s.is_def')]
    return [(b.path,b.ordinal,b.span,b.kind,b.name,b.text) for b in blocks],symbols


@pytest.mark.parametrize('edit',['change','prepend','duplicate','remove','rename'])
def test_reused_rows_match_fresh_spans_indexes_and_queries(tmp_path,edit):
    source=tmp_path/'source';source.mkdir();file=source/'worker.py'
    body='LIMIT = 7\ndef first():\n    return 11\ndef second():\n    return 22\n'
    file.write_text(body);pack=tmp_path/'base.npk';compile_pack(source,pack)
    with open_pack(pack) as con:old_id=con.execute("SELECT id FROM blocks WHERE name='second'").fetchone()[0]
    changes={'change':body.replace('return 11','return 111'),'prepend':'\n'+body,'duplicate':body+body,
             'remove':body[:body.index('def second')],'rename':body}
    file.write_text(changes[edit])
    if edit=='rename':file.rename(source/'renamed.py')
    stats,metrics=update_reused(pack,source);fresh=tmp_path/'fresh.npk';compile_pack(source,fresh)
    assert verify(pack)['ok'] and representation(pack)==representation(fresh)
    for query in ('LIMIT','first','second','return'):
        a=PackSelector(pack).select(query,budget_tokens=1000);b=PackSelector(fresh).select(query,budget_tokens=1000)
        assert a.context_text()==b.context_text() and a.total_tokens==b.total_tokens
    if edit in ('change','prepend'):
        with open_pack(pack) as con:assert con.execute("SELECT id FROM blocks WHERE name='second'").fetchone()[0]==old_id
        assert metrics['reused_blocks']>0


def test_failure_after_reuse_rolls_back_every_row_and_index(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir();file=source/'worker.py';file.write_text('def first():\n    return 1\n')
    pack=tmp_path/'base.npk';compile_pack(source,pack);before=pack.read_bytes()
    file.write_text('\n'+file.read_text())
    def fail(*args):raise RuntimeError('Synthetic sealing failure')
    monkeypatch.setattr(importlib.import_module('npk.pack.compile'),'_seal',fail)
    with pytest.raises(RuntimeError):update_reused(pack,source)
    assert pack.read_bytes()==before and verify(pack)['ok']


def test_research_scope_rejection_does_not_modify_artifact(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'worker.py').write_text('VALUE = 3\n')
    pack=tmp_path/'base.npk';compile_pack(source,pack,build_deps=True);before=pack.read_bytes()
    with pytest.raises(PackError):update_reused(pack,source)
    assert pack.read_bytes()==before


def test_repeated_updates_keep_tied_search_and_duplicate_occurrences(tmp_path):
    source=tmp_path/'source';source.mkdir();file=source/'worker.py'
    duplicate='def repeated():\n    return 22\n'
    other='def separate():\n    return 33\n'
    file.write_text(duplicate+duplicate+other)
    (source/'z_other.py').write_text('def unrelated():\n    return 44\n')
    pack=tmp_path/'base.npk';compile_pack(source,pack)
    # A smaller corpus and repeated source-order changes attack multiset reuse
    # and tie-breaking independently of row insertion order.
    for i,body in enumerate((other+duplicate+duplicate,duplicate,duplicate+other+duplicate)):
        file.write_text(body);update_reused(pack,source)
        fresh=tmp_path/f'fresh-{i}.npk';compile_pack(source,fresh)
        assert verify(pack)['ok'] and representation(pack)==representation(fresh)
        for query in ('return','repeated','separate','unrelated'):
            for budget in (8,16,100):
                a=PackSelector(pack).select(query,budget_tokens=budget)
                b=PackSelector(fresh).select(query,budget_tokens=budget)
                assert a.context_text()==b.context_text() and a.total_tokens==b.total_tokens
                assert [(e.path,e.span) for e in a.evidence]==[(e.path,e.span) for e in b.evidence]
