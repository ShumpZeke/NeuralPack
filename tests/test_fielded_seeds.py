"""Metadata retrieval can find a body whose owner name is absent from the text."""
from types import SimpleNamespace
from benchmarks.fielded_seeds import build,rank


def test_owner_metadata_is_searchable_without_rewriting_evidence(tmp_path):
    blocks=[SimpleNamespace(id=1,name='RetryPolicy',path='client/retry.py',text='return delay * 2'),
            SimpleNamespace(id=2,name='Unrelated',path='other.py',text='return 7')]
    con=build(tmp_path/'fields.sqlite',blocks)
    try:
        assert rank(con,'retry policy')==[1]
        assert con.execute('SELECT body FROM fielded WHERE block_id=1').fetchone()[0]==blocks[0].text
        assert rank(con,'zzzz-unrepresented-evidence')==[]
    finally:con.close()
