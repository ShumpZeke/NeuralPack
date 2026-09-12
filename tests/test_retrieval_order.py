"""Source-identical artifacts must not rank ties by insertion/update history."""
import sys
from types import SimpleNamespace

import pytest

from npk.pack import PackSelector,compile_pack,update_pack


@pytest.mark.parametrize("channel",["lexical","hybrid","dense_numpy","dense_scalar"])
def test_equal_scores_use_source_order_after_an_update(tmp_path,monkeypatch,channel):
    identity={"version":1,"model_id":"synthetic/ties","revision":"3"*40,"max_length":256,
              "pooling":"mask_mean_l2_v1","document_char_limit":2000}
    encoder=SimpleNamespace(available=lambda:True,identity=lambda:identity,
                            embed_matrix=lambda texts:[[1.0,0.0] for _ in texts],
                            embed_query=lambda query:[1.0,0.0])
    monkeypatch.setattr("npk.context.embedding.get_backend",lambda:encoder)
    source=tmp_path/"source";source.mkdir()
    (source/"a.py").write_text("TOKEN = 7\n",encoding="utf-8")
    (source/"z.py").write_text("TOKEN = 7\n",encoding="utf-8")
    pack=tmp_path/"updated.npk";fresh=tmp_path/"fresh.npk"
    mode="semantic" if channel.startswith("dense") else "deterministic"
    compile_pack(source,pack,mode=mode)
    (source/"a.py").write_text("\nTOKEN = 7\n",encoding="utf-8")
    update_pack(pack,source)
    compile_pack(source,fresh,mode=mode)
    query="unmentioned_query" if channel.startswith("dense") else "TOKEN"
    retrieval="lexical" if channel=="lexical" else "hybrid"
    if channel=="dense_scalar":
        monkeypatch.setitem(sys.modules,"numpy",None)
    kwargs={"retrieval":retrieval,"candidate_limit":1}
    selected=PackSelector(pack,**kwargs).select(query,budget_tokens=20,allow_escalation=False)
    expected=PackSelector(fresh,**kwargs).select(query,budget_tokens=20,allow_escalation=False)
    assert [e.path for e in expected.evidence]==["a.py"]
    assert [e.path for e in selected.evidence]==[e.path for e in expected.evidence]
