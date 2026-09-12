"""Research selection over compiled units; no generative or raw-source access.

Every method can use this common, provenance-budgeted assembler. It is not the
shipped PackSelector and does not claim that local adjacency proves sufficiency.
"""
from dataclasses import dataclass,field
import time
from benchmarks.evidence_diagnostics import Piece,from_evidence,render
from npk.pack.compile import estimate_tokens
from npk.pack.format import open_pack,load_blocks,read_manifest,require_supported,PackError
from npk.pack.select import _lexical_channel,_symbol_channel,_embedding_channel,RRF_K


def coalesce(pieces):
    """Merge only observed consecutive source lines; never invent gap contents."""
    sources={}
    for p in pieces:
        lines=p.text.split('\n')
        if len(lines)!=p.end-p.start+1:raise ValueError('Invalid passage span')
        mapped=sources.setdefault(p.path,{})
        for number,line in enumerate(lines,p.start):
            if number in mapped and mapped[number]!=line:raise ValueError('Conflicting source lines')
            mapped[number]=line
    out=[]
    for path,mapped in sorted(sources.items()):
        run=[]
        def emit():
            if run:out.append(Piece(path,run[0],run[-1],'\n'.join(mapped[n] for n in run)))
        for number in sorted(mapped):
            if run and number!=run[-1]+1:emit();run=[]
            run.append(number)
        emit()
    return out


def paragraph(seed,neighbors):
    """Expand seed edges to nearby blank lines; unresolved edges are reported."""
    lines={}
    for b in neighbors:
        for i,line in enumerate(b.text.split('\n'),b.start_line):lines[i]=line
    start=seed.start_line;end=seed.end_line
    while start-1 in lines and lines[start-1].strip():start-=1
    while end+1 in lines and lines[end+1].strip():end+=1
    unresolved=(start-1 not in lines and start>1) or end+1 not in lines
    # Returned ranges contain only observed lines. Missing lines are not
    # guessed to be blank, including at a source-window edge.
    return Piece(seed.path,start,end,'\n'.join(lines[i] for i in range(start,end+1))),unresolved


@dataclass
class Result:
    query:str
    system_prompt:str|None
    pieces:list
    budget:int
    available_tokens:int
    status:str
    selected_tokens:int
    seed_count:int
    channels:list
    notes:list=field(default_factory=list)
    latency_ms:float=0
    risk:str='uncalibrated'
    used_generative_llm:bool=False
    def context_text(self):return render(self.pieces,True)


def select(pack,query,budget,*,mode='seed',ranking='lexical',system_prompt=None,limit=60):
    if type(budget) is not int or budget<=0:raise ValueError('Budget must be a positive integer')
    if mode not in ('seed','neighbor1','neighbor2','paragraph'):raise ValueError('Unknown passage policy')
    if ranking not in ('lexical','hybrid'):raise ValueError('Unknown ranking')
    start=time.perf_counter_ns();notes=[];selected=[];channels={};seeds=[]
    with open_pack(pack) as con:
        manifest=read_manifest(con);require_supported(manifest)
        def rank(count):
            found={};lex=_lexical_channel(con,query,count)
            if lex:found['lexical']=lex
            if ranking=='hybrid':
                if int(manifest['embedding_dim'])<=0:raise PackError('Hybrid control requires actual compiled embeddings')
                sym=_symbol_channel(con,query,count)
                if sym:found['symbol']=sym
                dense,top=_embedding_channel(con,query,count,manifest)
                if not dense:raise PackError('Hybrid control encoder is unavailable')
                # Match the current public hybrid selector's declared floor.
                if top is None or top>=.35:found['embedding']=dense
                else:notes.append('embedding_below_public_floor')
            scores={}
            for ids in found.values():
                for i,identity in enumerate(ids):scores[identity]=scores.get(identity,0)+1/(RRF_K+i)
            return sorted(scores,key=lambda identity:-scores[identity]),found
        ids,channels=rank(limit)
        if not ids:
            notes.append('broader_seed_search');ids,channels=rank(limit*4)
        blocks={b.id:b for b in load_blocks(con,ids)};seeds=[blocks[i] for i in ids if i in blocks]
        if not seeds:notes.append('seed_failed_no_expansion')
        for seed in seeds:
            seed_piece=from_evidence(seed);group=[seed_piece]
            if mode!='seed':
                radius={'neighbor1':1,'neighbor2':2,'paragraph':4}[mode]
                neighbor_ids=[r[0] for r in con.execute('SELECT id FROM blocks WHERE file_id=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal',
                             (seed.file_id,seed.ordinal-radius,seed.ordinal+radius))]
                neighbors=load_blocks(con,neighbor_ids)
                if mode=='paragraph':
                    part,unresolved=paragraph(seed,neighbors);group=[part]
                    if unresolved:notes.append('paragraph_boundary_unresolved')
                else:group=[from_evidence(b) for b in neighbors]
            expanded=coalesce([*selected,*group])
            if estimate_tokens(render(expanded,True))<=budget:selected=expanded
            else:
                if mode!='seed':notes.append('expanded_passage_did_not_fit')
                narrow=coalesce([*selected,seed_piece])
                if estimate_tokens(render(narrow,True))<=budget:selected=narrow
        available=int(manifest['available_tokens'])
    if not selected:notes.append('full_context_fallback_required')
    text=render(selected,True);tokens=estimate_tokens(text) if selected else 0
    assert tokens<=budget
    return Result(query,system_prompt,selected,budget,available,'selected' if selected else 'fallback_required',
                  tokens,len(seeds),sorted(channels),list(dict.fromkeys(notes)),(time.perf_counter_ns()-start)/1e6)
