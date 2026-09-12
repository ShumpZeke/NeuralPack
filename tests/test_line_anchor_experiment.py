"""Physical source and adversarial-size contracts for research boundaries."""
import pytest
from benchmarks.line_anchors import split_anchored
from npk.pack.compile import _source_lines
from benchmarks.boundary_retrieval import fixed_chars


@pytest.mark.parametrize('body',[
    'one\r\ntwo\rthree\n','alpha\vbeta\fnext\u2028still\u2029same\n',
    '\n'.join('duplicate line' for _ in range(1000)),
    'x'*8000+'\nsmall\n','\n\nname\n\nvalue\n\n',
])
@pytest.mark.parametrize('splitter',[split_anchored,fixed_chars])
def test_anchors_preserve_every_nonblank_source_line_and_span(body,splitter):
    lines=_source_lines(body);blocks=splitter(body,'text',max_chars=100)
    covered=set()
    for block in blocks:
        assert block.text=='\n'.join(lines[block.start_line-1:block.end_line])
        span=set(range(block.start_line,block.end_line+1))
        assert not span&covered;covered|=span
        if len(block.text)>100:
            assert block.start_line==block.end_line and len(lines[block.start_line-1])>100
    assert all(i in covered for i,line in enumerate(lines,1) if line.strip())


def test_one_long_line_cannot_be_claimed_to_meet_a_small_block_cap():
    blocks=split_anchored('literal = "'+'a'*5000+'"','text',max_chars=100)
    assert len(blocks)==1 and len(blocks[0].text)>100


def test_anchor_free_text_can_still_lose_every_block_after_one_blank_line():
    import zlib
    from collections import Counter
    lines=[f'unique {i:012d}' for i in range(2000) if zlib.crc32(f'unique {i:012d}'.encode())&31][:1000]
    assert len(lines)==1000 and all(len(line)==19 for line in lines)
    body='\n'.join(lines)
    old=split_anchored(body,'text',max_chars=199)
    new=split_anchored('\n'+body,'text',max_chars=199)
    assert all(len(b.text)<=199 for b in old+new)
    assert sum((Counter(b.text for b in old)&Counter(b.text for b in new)).values())==0
