"""Tripwires for actual-cost and source-attribution comparison controls."""
from types import SimpleNamespace

import pytest

from benchmarks import rival_reproduction as evaluation


class Utf8Counter:
    """Synthetic non-character cost oracle, independent of the pack estimate."""
    @staticmethod
    def count(text):
        return len(text.encode('utf-8'))


def block(bid, text, path='source.py', span='source.py:1-4'):
    return SimpleNamespace(id=bid, text=text, path=path, span=span)


def test_exact_pack_counts_full_assembly_and_skips_oversized(monkeypatch):
    values = [block(1, '漢字'), block(2, 'cat'), block(3, 'ab')]
    monkeypatch.setattr(evaluation, '_lexical_channel', lambda *args: [1, 2, 3])
    monkeypatch.setattr(evaluation, 'load_blocks', lambda con, ids: values)
    selected = evaluation.exact_pack(None, 'unchanged query', 7, Utf8Counter())
    assert [b['block_id'] for b in selected] == [1]
    assert Utf8Counter.count('\n\n'.join(b['text'] for b in selected)) <= 7
    selected = evaluation.exact_pack(None, 'unchanged query', 5, Utf8Counter())
    assert [b['block_id'] for b in selected] == [2]


def test_empty_primary_pool_widens_with_the_original_query(monkeypatch):
    calls = []
    def rank(con, query, limit):
        calls.append((query, limit))
        return [1] if limit == 60 else [1, 2]
    monkeypatch.setattr(evaluation, '_lexical_channel', rank)
    values = {1: block(1, 'x' * 100), 2: block(2, 'ok')}
    monkeypatch.setattr(evaluation, 'load_blocks', lambda con, ids: [values[i] for i in ids])
    selected = evaluation.exact_pack(None, ' Q\r\n漢字 ', 5, Utf8Counter())
    assert [b['block_id'] for b in selected] == [2]
    assert calls == [(' Q\r\n漢字 ', 60), (' Q\r\n漢字 ', 240)]


@pytest.mark.parametrize('path,span', [('other.py', 'other.py:10-20'),
                                     ('source.py', 'source.py:1-9'),
                                     ('source.py', 'source.py:21-30')])
def test_foreign_or_disjoint_span_does_not_get_source_credit(path, span):
    task = {'path': 'source.py', 'span': 'source.py:10-20'}
    items = [{'path': path, 'span': span, 'text': 'return expected'}]
    assert evaluation.retention(evaluation.attributed_context(items, task),
                                ['return expected'])['strict_hit'] is False


def test_empty_needles_and_empty_context_cannot_win():
    assert evaluation.retention('unrelated text', [])['strict_hit'] is False
    assert evaluation.retention('', ['return expected'])['strict_hit'] is False


def test_actual_bpe_count_control_handles_cjk_and_literal_special_tokens(monkeypatch):
    tiktoken = pytest.importorskip('tiktoken')
    encoding = tiktoken.get_encoding('cl100k_base')
    counter = SimpleNamespace(count=lambda text: len(encoding.encode_ordinary(text)))
    values = [block(1, '漢字語漢字語'), block(2, '<|endoftext|>'), block(3, 'ok')]
    monkeypatch.setattr(evaluation, '_lexical_channel', lambda *args: [1, 2, 3])
    monkeypatch.setattr(evaluation, 'load_blocks', lambda con, ids: values)
    for budget in range(1, 24):
        selected = evaluation.exact_pack(None, 'query', budget, counter)
        assert counter.count('\n\n'.join(b['text'] for b in selected)) <= budget
