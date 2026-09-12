"""Corpus additions preserve literal source and do not execute documentation code."""
import hashlib
import io
import tarfile
import pytest
from benchmarks.api_source_corpus import source_members,inventory
from benchmarks.api_source_eval import uniform_source,region_counts
from benchmarks.evidence_diagnostics import Piece


def tar(entries):
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
        for name,body in entries:
            member=tarfile.TarInfo(name);member.size=len(body);archive.addfile(member,io.BytesIO(body))
    return buffer.getvalue()


def test_library_members_are_data_and_paths_do_not_flatten(tmp_path):
    destination=tmp_path/'executed.txt'
    body=('"""Source documentation."""\nfrom pathlib import Path\nPath('+repr(str(destination))+').write_text("executed")\n').encode()
    files=source_members(tar([('release/lib/sqlalchemy/orm/session.py',body),('release/lib/sqlalchemy/core/session.py',body),
                              ('release/tests/test_session.py',b'raise RuntimeError()')]))
    assert set(files)=={'sqlalchemy/lib/sqlalchemy/orm/session.py','sqlalchemy/lib/sqlalchemy/core/session.py'}
    assert all(value==body for value in files.values()) and not destination.exists()
    report=inventory(files)
    assert len(report['docstrings'])==2 and not destination.exists()


@pytest.mark.parametrize('name',['release/lib/sqlalchemy/../../escape.py','release/lib/sqlalchemy/bad:name.py','release/lib/sqlalchemy/bad\\name.py'])
def test_unsafe_library_paths_are_rejected(name):
    rejected=False
    try:source_members(tar([(name,b'x=1\n')]))
    except ValueError:rejected=True
    assert rejected, 'Source archive accepted an unsafe library path'


def test_duplicate_member_is_not_silently_replaced():
    rejected=False
    try:source_members(tar([('one/lib/sqlalchemy/a.py',b'x=1\n'),('two/lib/sqlalchemy/a.py',b'x=2\n')]))
    except ValueError:rejected=True
    assert rejected, 'Conflicting library members were silently overwritten'


def test_docstring_inventory_preserves_physical_unicode_source_spans():
    text='class A:\r\n    """caf\u00e9\u2028inline separator"""\r\n    def f(self):\r\n        """method doc"""\r\n        value = "not a docstring"\r\n'
    report=inventory({'a.py':text.encode(),'manual.rst':b'.. currentmodule:: package\n\n.. autoclass:: A\n    :members:\n'})
    docs=report['docstrings'];assert [d['name'] for d in docs]==['A','A.f']
    assert [d['span'] for d in docs]==[[2,2],[4,4]]
    literal='    """caf\u00e9\u2028inline separator"""'
    assert docs[0]['source_sha256']==hashlib.sha256(literal.encode()).hexdigest()
    assert report['autodoc_directives']==[{'path':'manual.rst','line':3,'kind':'autoclass','target':'A','currentmodule':'package'}]


def test_uniform_chunks_and_counts_keep_original_line_provenance():
    text='\n'.join(['alpha = 1']*650)+'\n'
    python=uniform_source(text,'python');manual=uniform_source(text,'rst')
    assert [(b.start_line,b.end_line,b.text) for b in python]==[(b.start_line,b.end_line,b.text) for b in manual]
    assert '\n'.join(b.text for b in python)+'\n'==text and max(len(b.text) for b in python)<=2048
    pieces=[Piece('a.py',1,3,'a\nb\nc'),Piece('a.py',3,4,'c\nd')]
    counts=region_counts(pieces,[{'path':'a.py','span':[2,3]},{'path':'a.py','span':[3,8]}])
    assert counts=={'selected_api_source_lines':4,'selected_api_docstring_lines':3}
