"""Source labels must survive rendering without escaping the token budget."""
from types import SimpleNamespace
import json
import pytest
from benchmarks.provenance_renderer import render_item, render, ProvenanceSelector
from npk.pack import LocalTokenizer, PackSelector, compile_pack
from npk.pack.format import PackError


def test_identical_bodies_from_different_scopes_keep_distinct_identity():
    body = '    def value(self):\n        return self.limit'
    a = SimpleNamespace(span='alpha.py:2-3', name='Alpha.value', text=body)
    b = SimpleNamespace(span='beta.py:2-3', name='Beta.value', text=body)
    assert a.text == b.text
    assert render_item(a) != render_item(b)
    assert 'Alpha.value' in render_item(a) and 'beta.py:2-3' in render_item(b)
    assert render_item(a).split('\n', 1)[1] == body


def test_untrusted_metadata_stays_on_one_escaped_json_line():
    span = 'folder\n# injected\u202e.py:1-2'; name = 'Q"\\\nvalue'
    item = SimpleNamespace(span=span, name=name, text='return 1')
    header, body = render_item(item).split('\n', 1)
    assert '\u202e' not in header and body == 'return 1'
    assert json.loads(header.removeprefix('# source ')) == [span, name]
    with pytest.raises(PackError): render_item(SimpleNamespace(span='a:1-2', name='a', text=' \n'))
    assert render([]) == ''


def compile_fixture(tmp_path):
    tokenizers = pytest.importorskip('tokenizers')
    backend = tokenizers.Tokenizer(tokenizers.models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
    backend.pre_tokenizer = tokenizers.pre_tokenizers.WhitespaceSplit()
    asset = tmp_path/'tokenizer.json'; asset.write_text(backend.to_str(), encoding='utf-8')
    source = tmp_path/'source'; source.mkdir()
    (source/'job.py').write_text('def probe():\n    return secret_dependency()\n\ndef secret_dependency():\n    return 42\n', encoding='utf-8')
    path = tmp_path/'project.npk'; compile_pack(source, path, build_deps=True)
    return backend, LocalTokenizer(asset), path


def test_headers_can_force_explicit_fallback_instead_of_a_budget_overrun(tmp_path):
    backend, counter, path = compile_fixture(tmp_path)
    plain = PackSelector(path, tokenizer=counter).select('`probe`', budget_tokens=100)
    cap = counter.count(plain.context_text())
    assert plain.evidence and counter.count(render(plain.evidence)) > cap
    result = ProvenanceSelector(path, tokenizer=counter).select('`probe`', budget_tokens=cap)
    assert result.seed_failed and not result.evidence and result.context_text() == ''
    assert result.as_dict()['status'] == 'fallback_required'


@pytest.mark.parametrize('graph', [False, True])
def test_public_counts_include_the_rendered_identity_for_every_cap(tmp_path, graph):
    backend, counter, path = compile_fixture(tmp_path)
    selector = ProvenanceSelector(path, tokenizer=counter, enable_dependency_expansion=graph)
    for budget in (1, 4, 8, 16, 64):
        selected = selector.select('`probe`', budget_tokens=budget)
        text = selected.context_text()
        assert selected.total_tokens == len(backend.encode(text, add_special_tokens=False).ids) <= budget
        assert selected.query == '`probe`' and not selected.used_generative_llm
        if selected.evidence:
            assert text.startswith('# source ') and selected.evidence[0].text in text
            assert 'source headers' in selected.as_dict()['token_accounting']
        if budget == 64:
            assert ('secret_dependency' in {e.name for e in selected.evidence}) is graph


def test_renderer_honors_the_frozen_research_seed_channel(tmp_path, monkeypatch):
    import importlib
    from npk.pack.format import open_pack, load_blocks
    _, counter, path = compile_fixture(tmp_path)
    with open_pack(path) as con:
        chosen = next(b.id for b in load_blocks(con) if b.name == 'secret_dependency')
    module = importlib.import_module('npk.pack.select')
    monkeypatch.setattr(module, '_lexical_channel', lambda *args: [chosen])
    result = ProvenanceSelector(path, tokenizer=counter).select('unrelated', budget_tokens=64, allow_escalation=False)
    assert [e.block_id for e in result.evidence] == [chosen]
