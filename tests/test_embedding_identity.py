"""Synthetic encoder plumbing attacks; these are not semantic quality tests."""
from types import SimpleNamespace

import pytest

from npk.context.embedding import LocalEmbeddingBackend


@pytest.fixture
def synthetic_encoders(monkeypatch):
    torch=pytest.importorskip("torch")
    transformers=pytest.importorskip("transformers")
    # Isolate the old process-global state when demonstrating the original bugs.
    for name,value in (("_model",None),("_tokenizer",None),("_load_attempted",False),("_cache",{})):
        if hasattr(LocalEmbeddingBackend,name):
            monkeypatch.setattr(LocalEmbeddingBackend,name,value)
    calls=[]
    class Tokenizer:
        def __call__(self,texts,*,max_length,**kwargs):
            values=[sum(map(ord,t[:max_length])) for t in texts]
            return {"input_ids":torch.tensor(values).reshape(-1,1),
                    "attention_mask":torch.ones(len(values),1)}
    class Model:
        def __init__(self,name):
            self.name=name
            self.config=SimpleNamespace(_commit_hash="1"*40)
        def eval(self):
            return self
        def __call__(self,input_ids,**kwargs):
            values=input_ids.float()
            hidden=torch.stack([values,torch.ones_like(values)],dim=2)
            if self.name.endswith("second"):
                hidden=hidden.flip(-1)
            return SimpleNamespace(last_hidden_state=hidden)
    def load(kind,name,**kwargs):
        calls.append({"kind":kind,"name":name,**kwargs})
        if name.endswith("missing"):
            raise OSError("synthetic weights unavailable")
        return Tokenizer() if kind=="tokenizer" else Model(name)
    monkeypatch.setattr(transformers.AutoTokenizer,"from_pretrained",lambda name,**kw:load("tokenizer",name,**kw))
    monkeypatch.setattr(transformers.AutoModel,"from_pretrained",lambda name,**kw:load("model",name,**kw))
    monkeypatch.delenv("NPK_ENABLE_EMBEDDINGS",raising=False)
    return calls


def test_text_separator_cannot_alias_a_different_batch(synthetic_encoders):
    backend=LocalEmbeddingBackend("synthetic/first")
    first=backend.embed_matrix(["alpha|NPKSEP|beta"])
    second=backend.embed_matrix(["alpha","beta"])
    assert len(first)==1
    assert len(second)==2


def test_encoders_and_truncation_settings_are_isolated(synthetic_encoders):
    first=LocalEmbeddingBackend("synthetic/first",max_length=1)
    longer=LocalEmbeddingBackend("synthetic/first",max_length=10)
    second=LocalEmbeddingBackend("synthetic/second",max_length=10)
    assert first.embed_query("alphabet") != longer.embed_query("alphabet")
    assert longer.embed_query("alphabet") != second.embed_query("alphabet")


def test_missing_encoder_cannot_borrow_another_models_weights(synthetic_encoders):
    assert LocalEmbeddingBackend("synthetic/first").available()
    assert not LocalEmbeddingBackend("synthetic/missing").available()


def test_failed_encoder_does_not_poison_another_encoder(synthetic_encoders):
    assert not LocalEmbeddingBackend("synthetic/missing").available()
    assert LocalEmbeddingBackend("synthetic/first").available()


@pytest.mark.parametrize('ambient_online_flag', ['0', '1'])
def test_runtime_loaders_are_explicitly_offline(synthetic_encoders, monkeypatch, ambient_online_flag):
    monkeypatch.setenv('HF_HUB_OFFLINE', ambient_online_flag)
    monkeypatch.setenv('TRANSFORMERS_OFFLINE', ambient_online_flag)
    assert LocalEmbeddingBackend("synthetic/first").available()
    assert synthetic_encoders
    assert all(c.get("local_files_only") is True for c in synthetic_encoders)
    assert all(c.get("trust_remote_code") is False for c in synthetic_encoders)
    assert all(c.get("use_safetensors") is True for c in synthetic_encoders if c["kind"]=="model")


def test_default_revision_is_passed_to_both_loaders(synthetic_encoders, monkeypatch):
    import transformers
    from npk.context.embedding import DEFAULT_MODEL_REVISION
    old = transformers.AutoModel.from_pretrained
    def default_cached_model(name, **kwargs):
        model = old(name, **kwargs)
        # A cache can coincidentally contain the desired revision even if the
        # caller forgot to request it. Check the actual arguments as well.
        model.config._commit_hash = DEFAULT_MODEL_REVISION
        return model
    monkeypatch.setattr(transformers.AutoModel, 'from_pretrained', default_cached_model)
    backend = LocalEmbeddingBackend()
    assert backend.available()
    assert backend.identity()['revision'] == DEFAULT_MODEL_REVISION
    assert len(synthetic_encoders) == 2
    assert all(c.get('revision') == DEFAULT_MODEL_REVISION for c in synthetic_encoders)


def test_wrong_loaded_revision_cannot_keep_requested_identity(synthetic_encoders):
    # The fixture returns revision 1...; the caller explicitly requested 2....
    backend = LocalEmbeddingBackend('synthetic/first', revision='2'*40)
    assert not backend.available()
    assert backend.identity() is None


def test_cache_is_bounded_by_tensor_bytes(synthetic_encoders,monkeypatch):
    monkeypatch.setattr(LocalEmbeddingBackend,"_CACHE_BUDGET_BYTES",1024,raising=False)
    backend=LocalEmbeddingBackend("synthetic/first")
    for prefix in ("first","second","third"):
        assert backend.embed_matrix([prefix+str(i) for i in range(100)]) is not None
    assert sum(t.numel()*t.element_size() for t in backend._cache.values()) <= 1024
