"""Compiled vectors must share a documented space across queries and updates."""
import importlib
import json
import math

import pytest

from npk.pack import PackSelector, compile_pack, update_pack, verify
from npk.pack.format import PackError, open_pack, read_manifest


class SyntheticEncoder:
    model_id="synthetic/first"
    ready=True
    max_length=256
    def available(self):
        return self.ready
    def identity(self):
        return {"version":1,"model_id":self.model_id,"revision":"1"*40,
                "max_length":self.max_length,"pooling":"mask_mean_l2_v1","document_char_limit":2000}
    def embed_matrix(self,texts):
        return [[1.0,0.0] for _ in texts]
    def embed_query(self,query):
        return [1.0,0.0]


@pytest.fixture
def source(tmp_path):
    root=tmp_path/"source"; root.mkdir()
    (root/"first.py").write_text("FIRST_LIMIT = 7\n",encoding="utf-8")
    (root/"second.py").write_text("SECOND_LIMIT = 9\n",encoding="utf-8")
    return root,tmp_path/"test.npk"


@pytest.fixture
def encoder(monkeypatch):
    backend=SyntheticEncoder()
    monkeypatch.setattr("npk.context.embedding.get_backend",lambda:backend)
    return backend


def test_compile_records_the_actual_encoder_contract(source,encoder):
    root,pack=source
    stats=compile_pack(root,pack,mode="semantic")
    assert stats.embedding_model==encoder.model_id
    with open_pack(pack) as con:
        manifest=read_manifest(con)
        assert json.loads(manifest["encoder_identity"])==encoder.identity()


def test_same_dimensions_do_not_make_different_encoders_compatible(source,encoder):
    root,pack=source
    compile_pack(root,pack,mode="semantic")
    encoder.model_id="synthetic/second"
    rejected=False
    try:
        PackSelector(pack,retrieval="hybrid").select("FIRST_LIMIT")
    except PackError as exc:
        rejected="encoder" in str(exc)
    assert rejected, "same-size vectors from a different encoder were accepted"
    assert "FIRST_LIMIT" in PackSelector(pack).select("FIRST_LIMIT").context_text()


def test_partial_update_rejects_new_encoder_settings_and_rolls_back(source,encoder):
    root,pack=source
    compile_pack(root,pack,mode="semantic")
    before=pack.read_bytes()
    (root/"first.py").write_text("FIRST_LIMIT = 17\n",encoding="utf-8")
    encoder.max_length=1
    with pytest.raises(PackError,match="encoder"):
        update_pack(pack,root)
    assert pack.read_bytes()==before
    assert verify(pack)["ok"]


def test_partial_update_with_missing_weights_is_atomic(source,encoder):
    root,pack=source
    compile_pack(root,pack,mode="semantic")
    before=pack.read_bytes()
    (root/"first.py").write_text("FIRST_LIMIT = 17\n",encoding="utf-8")
    encoder.ready=False
    with pytest.raises(PackError,match="encoder"):
        update_pack(pack,root)
    assert pack.read_bytes()==before


def test_weights_available_after_unembedded_compile_indexes_all_files(source,encoder):
    root,pack=source
    encoder.ready=False
    initial=compile_pack(root,pack,mode="semantic")
    assert initial.embedded==0 and initial.embedding_status=="unavailable"
    encoder.ready=True
    (root/"first.py").write_text("FIRST_LIMIT = 17\n",encoding="utf-8")
    updated=update_pack(pack,root)
    assert updated.embedding_status=="indexed"
    assert updated.integrity_files_hashed==2 and updated.integrity_files_reused==0
    with open_pack(pack) as con:
        assert con.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]==2
        manifest=read_manifest(con)
        assert int(manifest["embedding_dim"])==2
        assert json.loads(manifest["encoder_identity"])==encoder.identity()
    assert "embedding" in PackSelector(pack,retrieval="hybrid").select("FIRST_LIMIT").channels_used
    assert verify(pack)["ok"]


@pytest.mark.parametrize("vectors", [[[1.0,0.0]], [[1.0,0.0],[1.0]], [[1.0,0.0],[math.nan,0.0]]])
def test_malformed_vector_batch_cannot_publish_an_artifact(source,encoder,vectors):
    root,pack=source
    compile_pack(root,pack)
    before=pack.read_bytes()
    encoder.embed_matrix=lambda texts:vectors
    with pytest.raises(PackError,match="encoder"):
        compile_pack(root,pack,mode="semantic")
    assert pack.read_bytes()==before


def test_query_with_unavailable_encoder_explains_lexical_degradation(source,encoder):
    root,pack=source
    compile_pack(root,pack,mode="semantic")
    encoder.ready=False
    result=PackSelector(pack,retrieval="hybrid").select("FIRST_LIMIT")
    assert result.evidence and "embedding" not in result.channels_used
    assert any("unavailable" in note for note in result.notes)


def test_legacy_vectors_without_identity_require_explicit_recompile(source,encoder):
    root,pack=source
    compile_pack(root,pack,mode="semantic")
    import sqlite3
    with sqlite3.connect(pack) as con:
        con.execute("DELETE FROM manifest WHERE key='encoder_identity'")
    with pytest.raises(PackError,match="encoder"):
        PackSelector(pack,retrieval="hybrid").select("FIRST_LIMIT")
    assert PackSelector(pack).select("FIRST_LIMIT").evidence


def test_query_encoder_dimension_is_checked_even_if_model_id_matches(source,encoder):
    root,pack=source
    compile_pack(root,pack,mode="semantic")
    encoder.embed_query=lambda query:[1.0]
    with pytest.raises(PackError,match="encoder"):
        PackSelector(pack,retrieval="hybrid").select("FIRST_LIMIT")


def test_removing_all_semantic_source_resets_index_state(source,encoder):
    root,pack=source
    compile_pack(root,pack,mode="semantic")
    for path in root.glob("*.py"):
        path.unlink()
    assert update_pack(pack,root).embedding_status=="empty"
    with open_pack(pack) as con:
        assert read_manifest(con)["embedding_dim"]=="0"
    assert verify(pack)["ok"]
