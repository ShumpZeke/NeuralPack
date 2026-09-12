"""Diagnostic source controls must be literal, bounded and isolated from oracles."""
import sys
import pytest
from benchmarks.evidence_diagnostics import (Piece,definitions,pieces_from_symbols,
    trace_called_symbols,render,fit_labeled,validate_pieces)
from npk.pack.compile import estimate_tokens


def test_called_source_control_does_not_capture_oracle_values_or_other_functions(tmp_path):
    path=tmp_path/'library.py'
    path.write_text('class Mode:\n    BASE = 7\n    @staticmethod\n    def compute(value):\n        return value + 7\n\ndef irrelevant():\n    return 99\n')
    module={};exec(compile(path.read_text(),str(path),'exec'),module)
    observed,unmapped,answer=trace_called_symbols(lambda:module['Mode'].compute(31009),{str(path):'library.py'})
    assert answer==31016 and observed=={('library.py','Mode.compute')} and not unmapped
    pieces=pieces_from_symbols(tmp_path,observed,include_class_context=True)
    validate_pieces(tmp_path,pieces);text=render(pieces,True)
    assert 'BASE = 7' in text and 'def compute' in text
    assert '31009' not in text and '31016' not in text and 'def irrelevant' not in text


def test_profile_is_restored_after_an_oracle_failure_and_requests_are_isolated(tmp_path):
    previous=sys.getprofile()
    def fail():raise RuntimeError('synthetic oracle failure')
    with pytest.raises(RuntimeError):trace_called_symbols(fail,{})
    assert sys.getprofile() is previous
    assert trace_called_symbols(lambda:7,{})== (set(),set(),7)


def test_labeled_and_raw_pair_keep_identical_source_within_the_same_budget(tmp_path):
    text='def example():\n    return 7';(tmp_path/'a.py').write_text(text)
    pieces=[Piece('a.py',1,2,text,('example',))]
    assert fit_labeled(pieces,estimate_tokens(text))==[]
    selected=fit_labeled(pieces,100)
    assert selected==pieces and estimate_tokens(render(selected,True))<=100
    assert render(selected,False)==text
    validate_pieces(tmp_path,selected)
    with pytest.raises(ValueError):validate_pieces(tmp_path,[Piece('a.py',1,2,'forged')])


def test_diagnostic_source_keeps_unicode_characters_and_deduplicates_overlap(tmp_path):
    (tmp_path/'a.py').write_text("class C:\n    def message(self):\n        return 'left\u2028right'\n",encoding='utf-8')
    pieces=pieces_from_symbols(tmp_path,[('a.py','C'),('a.py','C.message')],include_class_context=True)
    assert len(pieces)==1 and '\u2028' in pieces[0].text
    validate_pieces(tmp_path,pieces)


def test_click_option_control_does_not_claim_to_capture_external_library_calls():
    import click
    import difflib
    from pathlib import Path
    from benchmarks.identifier_tasks import no_option
    library=Path(click.__file__).resolve().parent
    registered={spelling:'src/click/'+p.name for p in library.glob('*.py')
                for spelling in (str(p),str(p).replace('\\','/'))}
    called,_,answer=trace_called_symbols(no_option,registered)
    assert ('src/click/exceptions.py','NoSuchOption.__init__') in called
    assert not any(name=='get_close_matches' for path,name in called)
    assert difflib.get_close_matches('--bad',['--good'])==[]
    assert difflib.get_close_matches('--bad',['--zoom','--alpha'])==[]
    assert len(set(answer.values()))==1 and answer['none']=="No such option '--bad'."


def test_identical_click_source_can_need_different_answers_with_external_behavior(monkeypatch):
    import click
    from pathlib import Path
    from benchmarks.identifier_tasks import no_option
    source=Path(click.__file__).resolve().with_name('exceptions.py');before=source.read_bytes()
    normal=no_option()
    # Construct an alternate environment, not an edit to installed library files.
    monkeypatch.setattr('difflib.get_close_matches',lambda word,possibilities:list(possibilities))
    alternate=no_option()
    assert source.read_bytes()==before
    assert normal['one']=="No such option '--bad'."
    assert alternate['one']=="No such option '--bad'. Did you mean '--good'?"
    assert normal!=alternate
