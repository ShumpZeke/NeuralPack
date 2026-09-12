"""Local baseline plumbing; synthetic tensors are not retrieval-quality evidence."""
import pytest
from benchmarks.qwen_encoder import last_token_pool,QwenEncoder


def test_pooling_uses_the_last_real_token_for_both_padding_sides():
    import torch
    hidden=torch.arange(24).reshape(3,4,2)
    mask=torch.tensor([[1,1,0,0],[0,0,1,1],[1,1,1,1]])
    assert torch.equal(last_token_pool(hidden,mask),torch.stack([hidden[0,1],hidden[1,3],hidden[2,3]]))
    with pytest.raises(ValueError):last_token_pool(hidden[:1],torch.zeros_like(mask[:1]))


def test_invalid_configuration_cannot_reach_model_loading():
    with pytest.raises(ValueError):QwenEncoder('missing-record.json',device='auto')
    with pytest.raises(ValueError):QwenEncoder('missing-record.json',max_length=0)
    with pytest.raises(ValueError):QwenEncoder('missing-record.json',batch_size=True)
