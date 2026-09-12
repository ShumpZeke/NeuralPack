"""Persistent-count attacks: real BPE, real .npk updates, and SQLite races."""
import hashlib
import sqlite3
from unittest.mock import patch
import pytest
from benchmarks.compact_boundary_tokenizer import CompactBoundaryCount,PreparedCountState,PreparedCostGraph
from benchmarks.compiled_count_index import update_index,load_index
from npk.pack import compile_pack,update_pack
from npk.pack.format import open_pack,load_blocks,PackError
from tests.test_boundary_tokenizer import pipeline

sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()


def inputs(tmp_path,pipeline):
    codec,asset=pipeline; source=tmp_path/'source'; source.mkdir()
    (source/'one.py').write_text("def retry_alpha():\n    return '界 e\u0301 😀'\n\n\ndef stable_beta():\n    return 2\n",encoding='utf-8')
    (source/'two.py').write_text("def stable_beta():\n    return 2\n\n\ndef fallback_gamma():\n    return 'gamma'\n",encoding='utf-8')
    pack=tmp_path/'source.npk'; compile_pack(source,pack); index=tmp_path/'counts.sqlite'
    compiled=update_index(pack,index,CompactBoundaryCount(asset),create=True)
    return codec,asset,source,pack,index,compiled


def bodies(pack):
    with open_pack(pack) as con: return [b.text for b in load_blocks(con)]


def test_compact_count_records_preserve_whole_join_and_memory_limit(pipeline):
    codec,asset=pipeline; counter=CompactBoundaryCount(asset,prepared_bytes=1200)
    parts=['first e\u0301界😀 last','alpha beta gamma','left middle right','some unknown text']
    counter.prepare(parts[:3]); before=counter.prepared_info()['compiled_parts']
    assert counter.count_parts(parts)==len(codec.encode('\n\n'.join(parts),add_special_tokens=False))
    assert counter.prepared_info()['compiled_parts']==before
    assert counter.prepared_info()['accounted_retained_bytes']<=1200


def test_incremental_prepared_state_matches_every_whole_join_prefix(pipeline):
    codec,asset=pipeline
    parts=['first e\u0301界😀 last','alpha beta gamma','left middle right','tail 42']
    counter=CompactBoundaryCount(asset);counter.prepare(parts)
    state=counter.initial_state()
    for index,text in enumerate(parts,1):
        prior=state
        state=counter.extend_state(state,text)
        assert state is not None and state.has_parts
        assert state.total_tokens==len(codec.encode(
            '\n\n'.join(parts[:index]),add_special_tokens=False))
        assert prior==PreparedCountState() if index==1 else prior.total_tokens>0
    # State is immutable and may branch for independent budget cells.
    branch=counter.extend_state(counter.initial_state(),parts[-1])
    assert branch.total_tokens==len(codec.encode(parts[-1],add_special_tokens=False))


def test_incremental_prepared_state_exposes_unsupported_fallback(pipeline):
    _,asset=pipeline;counter=CompactBoundaryCount(asset,prepared_bytes=0)
    counter.prepare(['not retained'])
    state=counter.initial_state()
    assert counter.extend_state(state,'not retained') is None and state==PreparedCountState()
    with pytest.raises(TypeError):counter.extend_state(None,'text')
    with pytest.raises(TypeError):counter.extend_state(state,b'bytes')


def test_prepared_cost_graph_matches_whole_join_and_rejects_unknown_text(pipeline):
    codec,asset=pipeline
    parts=['first alpha last',']','second beta tail',')','third gamma end']
    counter=CompactBoundaryCount(asset);counter.prepare(parts)
    graph=PreparedCostGraph(counter,parts);total=0;last=None
    for index,text in enumerate(parts,1):
        total,last=graph.extend(total,last,text)
        assert total==len(codec.encode('\n\n'.join(parts[:index]),add_special_tokens=False))
    assert graph.extend(total,last,'not prepared') is None
    again,last=graph.extend(0,None,parts[0])
    assert again==len(codec.encode(parts[0],add_special_tokens=False))
    assert graph.info()['supported_texts']==len(parts)


def test_receipt_load_survives_restart_without_recompiling_or_network(tmp_path,pipeline,monkeypatch):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline)
    fresh=CompactBoundaryCount(asset)
    def forbidden(*args): raise AssertionError('Unexpected region compilation')
    monkeypatch.setattr(fresh,'_segment',forbidden)
    with patch('socket.socket.connect',side_effect=AssertionError('Unexpected network')):
        result=load_index(pack,index,fresh,expected_digest=compiled['receipt_sha256'])
        parts=bodies(pack)
        assert fresh.count_parts(parts)==len(codec.encode('\n\n'.join(parts),add_special_tokens=False))
    assert result['records_recompiled_for_verification']==0
    assert result['mode']=='receipt_verified' and fresh.compiled_parts==0
    with sqlite3.connect(index) as con:
        assert con.execute('SELECT COUNT(*) FROM records').fetchone()[0]<len(parts)
        # Source text is not embedded in this derived index.
        assert all('retry_alpha' not in line for line in con.iterdump())


def test_load_without_receipt_recomputes_instead_of_trusting_self_declared_data(tmp_path,pipeline):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline)
    fresh=CompactBoundaryCount(asset)
    checked=load_index(pack,index,fresh)
    assert checked['records_recompiled_for_verification']==checked['records_loaded']>0
    with sqlite3.connect(index) as con: con.execute('UPDATE records SET tokens=tokens+1 WHERE split=1')
    target=CompactBoundaryCount(asset); rejected=False
    try: load_index(pack,index,target)
    except PackError: rejected=True
    assert rejected and target.prepared_info()['entries']==0


def test_changed_bytes_cannot_reuse_a_trusted_old_receipt(tmp_path,pipeline):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline)
    with sqlite3.connect(index) as con: con.execute('UPDATE records SET tokens=tokens+1 WHERE split=1')
    fresh=CompactBoundaryCount(asset); rejected=False
    try: load_index(pack,index,fresh,expected_digest=compiled['receipt_sha256'])
    except PackError: rejected=True
    assert rejected and fresh.prepared_info()['entries']==0


def test_failed_external_verification_does_not_partially_hydrate(tmp_path,pipeline):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline)
    last=hashlib.sha256(bodies(pack)[-1].encode()).hexdigest()
    with sqlite3.connect(index) as con: con.execute('UPDATE records SET tokens=tokens+1 WHERE text_sha=?',(last,))
    fresh=CompactBoundaryCount(asset); rejected=False
    try: load_index(pack,index,fresh)
    except PackError: rejected=True
    assert rejected and fresh.prepared_info()['entries']==0


@pytest.mark.parametrize('sql',[
    "UPDATE metadata SET value='unknown' WHERE key='version'",
    "UPDATE metadata SET value='different-engine' WHERE key='tokenizers_version'",
    "UPDATE metadata SET value='different-algorithm' WHERE key='algorithm'",
    "UPDATE metadata SET value='different-tokenizer' WHERE key='tokenizer_sha256'",
    'UPDATE records SET prefix_end=-1 WHERE split=1',
    'DELETE FROM blocks WHERE block_id=(SELECT MIN(block_id) FROM blocks)',
    'CREATE VIEW unauthorized AS SELECT * FROM records',
])
def test_even_trusted_bytes_must_match_supported_identity_and_structure(tmp_path,pipeline,sql):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline)
    with sqlite3.connect(index) as con: con.execute(sql)
    fresh=CompactBoundaryCount(asset)
    with pytest.raises(PackError): load_index(pack,index,fresh,expected_digest=sha(index))
    assert fresh.prepared_info()['entries']==0


def test_real_incremental_update_reuses_unchanged_blocks_and_matches_rebuild(tmp_path,pipeline):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline)
    file=source/'one.py'; file.write_text(file.read_text(encoding='utf-8').replace('retry_alpha','retry_changed'),encoding='utf-8')
    update_pack(pack,source); fresh=CompactBoundaryCount(asset); rejected=False
    try: load_index(pack,index,fresh,expected_digest=compiled['receipt_sha256'])
    except PackError: rejected=True
    assert rejected and fresh.prepared_info()['entries']==0
    with patch.object(fresh,'_segment',wraps=fresh._segment) as compiler:
        changed=update_index(pack,index,fresh,expected_digest=compiled['receipt_sha256'])
        assert compiler.call_count==1, 'Unchanged source blocks must not be secretly recompiled'
    assert changed['owners_changed']==1 and changed['owners_reused']==1
    assert changed['records_compiled']==1 and changed['changed_block_records_reused']>0
    rebuilt=tmp_path/'fresh.sqlite'; update_index(pack,rebuilt,CompactBoundaryCount(asset),create=True)
    with sqlite3.connect(index) as a,sqlite3.connect(rebuilt) as b:
        for table in ('metadata','owners','records','blocks'):
            assert sorted(a.execute('SELECT * FROM '+table))==sorted(b.execute('SELECT * FROM '+table))
    load_index(pack,index,fresh,expected_digest=changed['receipt_sha256'])
    parts=bodies(pack)
    assert fresh.count_parts(parts)==len(codec.encode('\n\n'.join(parts),add_special_tokens=False))


def test_deleting_file_preserves_shared_records_and_prunes_orphans(tmp_path,pipeline):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline)
    (source/'one.py').unlink(); update_pack(pack,source)
    changed=update_index(pack,index,CompactBoundaryCount(asset),expected_digest=compiled['receipt_sha256'])
    assert changed['owners_removed']==1 and changed['records_compiled']==0
    with sqlite3.connect(index) as con:
        assert con.execute('SELECT COUNT(*) FROM records').fetchone()[0]==2
    load_index(pack,index,CompactBoundaryCount(asset),expected_digest=changed['receipt_sha256'])


def test_failed_region_compilation_rolls_back_existing_index(tmp_path,pipeline,monkeypatch):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline); before=index.read_bytes()
    file=source/'one.py'; file.write_text(file.read_text(encoding='utf-8').replace('retry_alpha','retry_changed'),encoding='utf-8')
    update_pack(pack,source); counter=CompactBoundaryCount(asset)
    def failed(*args): raise RuntimeError('injected region failure')
    monkeypatch.setattr(counter,'_segment',failed)
    with pytest.raises(RuntimeError,match='injected'): update_index(pack,index,counter,expected_digest=compiled['receipt_sha256'])
    assert index.read_bytes()==before


def test_update_requires_matching_receipt_before_mutating(tmp_path,pipeline):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline); before=index.read_bytes()
    with pytest.raises(PackError): update_index(pack,index,CompactBoundaryCount(asset))
    assert index.read_bytes()==before


def test_storage_limit_cannot_publish_an_unreadable_update(tmp_path,pipeline,monkeypatch):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline); before=index.read_bytes()
    monkeypatch.setattr('benchmarks.compiled_count_index.MAX_BYTES',1)
    with pytest.raises(PackError): update_index(pack,index,CompactBoundaryCount(asset),expected_digest=compiled['receipt_sha256'])
    assert index.read_bytes()==before


def test_receipt_is_captured_before_competing_writer_can_change_committed_bytes(tmp_path,pipeline,monkeypatch):
    codec,asset,source,pack,index,compiled=inputs(tmp_path,pipeline)
    real_connect=sqlite3.connect; blocked=[]
    class Connection:
        def __init__(self,con,owned): self.con=con; self.owned=owned
        def __getattr__(self,name): return getattr(self.con,name)
        def commit(self):
            self.con.commit()
            if self.owned:
                other=real_connect(index,timeout=0)
                try:
                    other.execute("UPDATE metadata SET value='racing-writer' WHERE key='parent_root'"); other.commit()
                    blocked.append(False)
                except sqlite3.OperationalError:
                    blocked.append(True); other.rollback()
                finally: other.close()
    def connect(*args,**kwargs):
        con=real_connect(*args,**kwargs)
        return Connection(con,True) if str(args[0]).startswith(index.absolute().as_uri()) else con
    monkeypatch.setattr('benchmarks.compiled_count_index.sqlite3.connect',connect)
    result=update_index(pack,index,CompactBoundaryCount(asset),expected_digest=compiled['receipt_sha256'])
    assert blocked==[True], 'A competing writer changed the artifact before its receipt was captured'
    assert result['receipt_sha256']==sha(index)
