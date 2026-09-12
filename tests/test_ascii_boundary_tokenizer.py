"""Attacks for the restricted word-barrier proposal with a real tiny BPE."""
import random
from benchmarks.ascii_boundary_tokenizer import AsciiBoundaryCount
from tests.test_boundary_tokenizer import pipeline


def test_ascii_word_barriers_preserve_full_ids_and_counts(pipeline):
    codec,path=pipeline; counter=AsciiBoundaryCount(path)
    parts=['ABCdefG HIjKLm','alpha beta gamma /','///delta epsilon',
           '\nalpha   beta\r\n','first\x00last','word1mid2last','a\v\f\tb',
           'onlyONEword','_private_thing_','/\n/abc _def','A_bC_D',
           '界1 e\u0301 2界','first e\u0301 last','', ' ']
    counter.prepare(parts); prepared=counter.prepared_info()['compiled_parts']
    rng=random.Random(2925)
    for _ in range(300):
        selected=rng.choices(parts,k=rng.randrange(0,8))
        expected=codec.encode('\n\n'.join(selected),add_special_tokens=False).ids
        assert counter.differential_ids(selected)==expected
        assert counter.count_parts(selected)==len(expected)
    assert counter.prepared_info()['compiled_parts']==prepared
    # All camel-case subpieces of the first/last word remain at the boundary.
    rec,_=counter._prepared['ABCdefG HIjKLm']
    assert rec.prefix=='ABCdefG' and rec.suffix.strip()=='HIjKLm'
    assert not counter._prepared['onlyONEword'][0].split
    # A combining mark is outside this proof; numeric fallback keeps it uncut.
    assert not counter._prepared['first e\u0301 last'][0].split
