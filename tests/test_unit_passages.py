"""Attacks on the research assembler's source, budget and request boundaries."""
import importlib
from unittest.mock import patch
import pytest
from benchmarks.evidence_diagnostics import Piece
from benchmarks.unit_passages import coalesce,select
from benchmarks.boundary_retrieval import fixed_chars
from npk.pack import compile_pack


def pack(tmp_path):
    source=tmp_path/'source';source.mkdir()
    (source/'rules.rst').write_text('Retries are enabled.\n\nImportant exception:\nNever retry a paid operation.\n\nOther operations may retry.\n',encoding='utf-8')
    artifact=tmp_path/'test.npk';module=importlib.import_module('npk.pack.compile')
    def split(text,language,**kwargs):return fixed_chars(text,language,max_chars=35,**kwargs)
    with patch.object(module,'split_source',split):compile_pack(source,artifact)
    return artifact


def test_coalescing_preserves_observed_whitespace_and_refuses_conflicts():
    p=Piece('code.py',1,2,'value = "x"\n  ');q=Piece('code.py',2,3,'  \nnext = "a\vb"')
    result=coalesce([q,p]);assert result==[Piece('code.py',1,3,'value = "x"\n  \nnext = "a\vb"')]
    with pytest.raises(ValueError):coalesce([p,Piece('code.py',2,2,'different')])


def test_coalescing_never_invents_missing_lines():
    a=Piece('rules.rst',1,1,'Retry the operation.')
    b=Piece('rules.rst',3,3,'Never retry payment.')
    assert coalesce([a,b])==[a,b]


@pytest.mark.parametrize('mode',['seed','neighbor1','neighbor2','paragraph'])
def test_budget_query_system_and_cross_request_isolation(tmp_path,mode):
    artifact=pack(tmp_path);query='paid\n\nKeep this final condition.  ';system='Preserve literal\u2028instructions'
    with patch('socket.socket.connect',side_effect=AssertionError('Unexpected network')):
        first=select(artifact,query,80,mode=mode,system_prompt=system)
        tiny=select(artifact,'other',1,mode=mode,system_prompt='different')
        again=select(artifact,query,80,mode=mode,system_prompt=system)
    assert first.query==query and first.system_prompt==system
    assert first.context_text()==again.context_text() and first.pieces==again.pieces
    assert first.selected_tokens<=80 and not first.used_generative_llm
    assert tiny.status=='fallback_required' and tiny.selected_tokens==0
    assert tiny.query=='other' and tiny.system_prompt=='different'


def test_failed_seeds_do_not_expand_empty_context_or_claim_a_win(tmp_path,monkeypatch):
    artifact=pack(tmp_path)
    monkeypatch.setattr('benchmarks.unit_passages._lexical_channel',lambda *args:[])
    result=select(artifact,'paid',200,mode='neighbor2')
    assert not result.pieces and result.status=='fallback_required' and result.seed_count==0
    assert 'broader_seed_search' in result.notes and 'seed_failed_no_expansion' in result.notes


def test_neighbor_expansion_recovers_the_adjacent_exception(tmp_path):
    artifact=pack(tmp_path);result=select(artifact,'Important exception',150,mode='neighbor1')
    assert 'Never retry a paid operation.' in result.context_text()
    assert result.selected_tokens<=150 and result.risk=='uncalibrated'


@pytest.mark.parametrize('count',[0,1,3])
def test_public_adapter_accepts_any_number_of_budgeted_pieces(count):
    from types import SimpleNamespace
    from benchmarks.unit_eval import public_context
    evidence=[SimpleNamespace(path='rules.rst',span=f'rules.rst:{i*3+1}-{i*3+1}',
                              text=f'Clause {i}',name=None) for i in range(count)]
    pieces,context=public_context(SimpleNamespace(evidence=evidence),200)
    assert isinstance(pieces,list) and len(pieces)==count
    assert all(p.text in context for p in pieces)
    if not count:assert context==''
