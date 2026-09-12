"""Changed-block reuse must agree with fresh compilation, never stale positions."""
import hashlib
import struct

import pytest

from npk.pack import compile_pack, update_pack, verify
from npk.pack.format import PackError, open_pack


class CountingEncoder:
    ready=True
    model_id="synthetic/reuse"
    max_length=256
    def __init__(self):
        self.batches=[]
    def available(self):
        return self.ready
    def identity(self):
        return {"version":1,"model_id":self.model_id,"revision":"2"*40,"max_length":self.max_length,
                "pooling":"mask_mean_l2_v1","document_char_limit":2000}
    def embed_matrix(self,texts):
        self.batches.append(list(texts))
        return [[v/255 for v in hashlib.sha256(t.encode()).digest()[:4]] for t in texts]


@pytest.fixture
def case(tmp_path,monkeypatch):
    encoder=CountingEncoder()
    monkeypatch.setattr("npk.context.embedding.get_backend",lambda:encoder)
    root=tmp_path/"source";root.mkdir()
    path=root/"worker.py"
    path.write_text("class Worker:\n    LIMIT = 3\n    def first(self):\n        return 7\n"
                    "    def second(self):\n        return 11\n",encoding="utf-8")
    pack=tmp_path/"project.npk"
    compile_pack(root,pack,mode="semantic",python_members=True)
    encoder.batches.clear()
    return root,path,pack,encoder


def rows(pack):
    with open_pack(pack) as con:
        return [tuple(r) for r in con.execute(
            "SELECT f.path,b.start_line,b.end_line,b.text,e.dim,e.vector FROM blocks b "
            "JOIN files f ON f.id=b.file_id JOIN embeddings e ON e.block_id=b.id "
            "ORDER BY f.path,b.ordinal")]


def assert_fresh_equivalence(root,pack):
    fresh=pack.with_name("fresh.npk")
    compile_pack(root,fresh,mode="semantic",python_members=True)
    assert rows(pack)==rows(fresh)
    assert verify(pack)["ok"]


def test_one_changed_method_only_submits_its_new_text(case):
    root,path,pack,encoder=case
    path.write_text(path.read_text().replace("return 7","return 71"),encoding="utf-8")
    stats=update_pack(pack,root)
    submitted=[t for batch in encoder.batches for t in batch]
    assert len(submitted)==1 and "return 71" in submitted[0]
    assert stats.encoder_rows_requested==1 and stats.embedding_rows_reused==2
    assert_fresh_equivalence(root,pack)


def test_span_shift_can_reuse_vectors_but_must_update_provenance(case):
    root,path,pack,encoder=case
    path.write_text("\n\n"+path.read_text(),encoding="utf-8")
    update_pack(pack,root)
    assert encoder.batches==[]
    assert rows(pack)[0][1]==3
    assert_fresh_equivalence(root,pack)


def test_rename_can_reuse_deleted_files_vectors(case):
    root,path,pack,encoder=case
    path.rename(root/"renamed.py")
    update_pack(pack,root)
    assert encoder.batches==[]
    assert {r[0] for r in rows(pack)}=={"renamed.py"}
    assert_fresh_equivalence(root,pack)


def test_duplicate_text_preserves_all_occurrences_and_spans(case):
    root,path,pack,encoder=case
    body=path.read_text()
    path.write_text(body+"\n"+body,encoding="utf-8")
    update_pack(pack,root)
    assert encoder.batches==[]
    assert len(rows(pack))==6
    assert_fresh_equivalence(root,pack)


def test_reuse_still_rejects_encoder_mismatch_and_rolls_back(case):
    root,path,pack,encoder=case
    before=pack.read_bytes()
    path.write_text("\n"+path.read_text(),encoding="utf-8")
    encoder.max_length=1
    with pytest.raises(PackError,match="encoder"):
        update_pack(pack,root)
    assert pack.read_bytes()==before


def test_failed_new_vector_batch_cannot_publish_reused_rows(case):
    root,path,pack,encoder=case
    before=pack.read_bytes()
    path.write_text(path.read_text().replace("return 7","return 71"),encoding="utf-8")
    encoder.embed_matrix=lambda texts:None
    with pytest.raises(PackError,match="encoder"):
        update_pack(pack,root)
    assert pack.read_bytes()==before


def test_same_hash_cannot_reuse_different_text(case,monkeypatch):
    root,path,pack,encoder=case
    # Simulate a hash collision consistently, without bypassing the new
    # rejection of externally edited/unsealed artifacts.
    import importlib
    from types import SimpleNamespace
    new_text="    def first(self):\n        return 71"
    with open_pack(pack) as con:
        old_text=con.execute("SELECT text FROM blocks WHERE name='Worker.first'").fetchone()[0]
    collision=SimpleNamespace(sha256=lambda data=b'':hashlib.sha256(old_text.encode() if data==new_text.encode() else data))
    monkeypatch.setattr(importlib.import_module('npk.pack.compile'),'hashlib',collision)
    monkeypatch.setattr(importlib.import_module('npk.pack.format'),'hashlib',collision)
    path.write_text(path.read_text().replace("return 7","return 71"),encoding="utf-8")
    update_pack(pack,root)
    submitted=[t for batch in encoder.batches for t in batch]
    assert new_text in submitted
    assert_fresh_equivalence(root,pack)


@pytest.mark.parametrize("payload", [b"bad",struct.pack("<4f",float("nan"),0,0,0)])
def test_corrupted_reusable_vector_fails_without_resealing_it(case,payload):
    root,path,pack,encoder=case
    import sqlite3
    with sqlite3.connect(pack) as con:
        con.execute("UPDATE embeddings SET vector=? WHERE block_id=(SELECT MIN(id) FROM blocks)",(payload,))
        # Make integrity metadata consistent to reach vector validation itself;
        # unsealed external writes are independently rejected at the update gate.
        from npk.pack.compile import _seal
        _seal(con)
    before=pack.read_bytes()
    path.write_text("\n"+path.read_text(),encoding="utf-8")
    with pytest.raises(PackError,match="vector"):
        update_pack(pack,root)
    assert pack.read_bytes()==before


def test_removal_only_does_not_copy_unused_vectors(case,monkeypatch):
    root,path,pack,encoder=case
    import importlib
    module=importlib.import_module("npk.pack.compile")
    def denied(*args):
        raise AssertionError("deletion-only update retained vectors it cannot reuse")
    monkeypatch.setattr(module,"_retain_changed_vectors",denied)
    path.unlink()
    assert update_pack(pack,root).embedding_status=="empty"
    assert encoder.batches==[]
    assert verify(pack)["ok"]
