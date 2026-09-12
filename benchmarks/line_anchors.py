"""Research line-content anchors, not FastCDC and not a shipped splitter.

CRC32 chooses non-security boundary hints. Exact payload comparison and the
existing SHA-256 artifact checks still determine reuse and integrity. Whole
physical lines are preserved; an oversized line remains oversized.
"""
import zlib
from npk.pack.compile import RawBlock,_source_lines,_extract_symbols,split_source


def split_anchored(text,language,*,python_members=False,max_chars=4800,min_chars=0):
    if language not in ('c','rst','text'):
        return split_source(text,language,python_members=python_members)
    if max_chars<=0 or min_chars<0 or min_chars>max_chars:
        raise ValueError('Invalid research chunk bounds')
    lines=_source_lines(text);blocks=[];start=0;size=0
    def emit(end):
        nonlocal start,size
        body='\n'.join(lines[start:end])
        if body.strip():
            block=RawBlock(len(blocks),'chunk',None,start+1,end,body)
            _extract_symbols(block);blocks.append(block)
        start=end;size=0
    for i,line in enumerate(lines):
        extra=len(line)+(1 if i>start else 0)
        if i>start and size+extra>max_chars:
            emit(i);extra=len(line)
        size+=extra
        # Empty lines cannot create new anchors. This is a cheap deterministic
        # line hash, with a declared 5-bit mask, not a semantic boundary parser.
        anchor=bool(line.strip()) and zlib.crc32(line.encode('utf-8'))&31==0
        if size>=max_chars or (size>=min_chars and anchor):emit(i+1)
    if start<len(lines):emit(len(lines))
    return blocks
