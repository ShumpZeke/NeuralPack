"""Synthetic plumbing assertions for the optional real-model benchmark."""
from types import SimpleNamespace

import pytest

torch=pytest.importorskip("torch")

from benchmarks.repository_rerank import LocalReranker


def test_reranker_preserves_query_and_sorts_ties_stably():
    instance=object.__new__(LocalReranker)
    calls=[]
    query="Keep \u03bb and exact spaces  intact"
    def tokenize(queries,passages,**kwargs):
        calls.append((queries,passages,kwargs))
        return {"input_ids":torch.tensor([[-2.0],[3.0],[3.0]])}
    instance.tokenizer=tokenize
    instance.model=lambda **encoded:SimpleNamespace(logits=encoded["input_ids"])
    blocks=[SimpleNamespace(text=t) for t in ("first","second","third")]
    selected,scores=instance.rank(query,blocks)
    assert selected==[blocks[1],blocks[2],blocks[0]]
    assert scores==[3.0,3.0,-2.0]
    assert calls[0][0]==[query]*3
    assert calls[0][2]["truncation"]=="only_second"
    assert calls[0][2]["max_length"]==512
    assert instance.rank(query,[])==([],[])
    assert len(calls)==1


@pytest.mark.parametrize("logits",[torch.tensor([[float("nan")]]),torch.tensor([[1.0],[2.0]])])
def test_reranker_rejects_invalid_scores(logits):
    instance=object.__new__(LocalReranker)
    instance.tokenizer=lambda *a,**k:{}
    instance.model=lambda **encoded:SimpleNamespace(logits=logits)
    with pytest.raises(RuntimeError,match="malformed"):
        instance.rank("query",[SimpleNamespace(text="passage")])
