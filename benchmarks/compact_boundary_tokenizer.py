"""Count-only prepared regions; no persisted token IDs or generative state."""
from dataclasses import dataclass
import sys
from benchmarks.delimited_boundary_tokenizer import DelimitedBoundaryCount
from npk.pack.format import PackError


@dataclass(frozen=True,slots=True)
class CountRegion:
    prefix: str
    suffix: str
    tokens: int
    split: bool


@dataclass(frozen=True,slots=True)
class PreparedCountState:
    """Exact count state for appending prepared parts with a fixed separator."""
    finalized_tokens: int = 0
    pending: str = ''
    has_parts: bool = False
    total_tokens: int = 0


class PreparedCostGraph:
    """Single-threaded exact append costs over retained split regions.

    This is a benchmark partial-evaluation structure. Unsupported records return
    ``None`` so callers can preserve exact whole-text fallback. Short unsplit
    records become explicit unresolved-boundary states.
    """
    def __init__(self,counter,texts,separator='\n\n'):
        if not isinstance(counter,CompactBoundaryCount):
            raise TypeError('Expected a CompactBoundaryCount')
        if not isinstance(texts,(list,tuple)) or any(not isinstance(t,str) for t in texts):
            raise TypeError('Graph sources must be a list/tuple of strings')
        if not isinstance(separator,str):raise TypeError('Separator must be text')
        self.counter=counter;self.separator=separator;self._text_ids={};self._records=[]
        self._pending_text=[];self._pending_count=[];self._pending_ids={}
        self._split_states=[];self._transitions={};self.hits=self.misses=0
        for text in dict.fromkeys(texts):
            entry=counter._prepared.get(text)
            if entry is None or entry[0] is None:continue
            record=entry[0];rid=len(self._records);self._text_ids[text]=rid
            self._records.append(record)
            self._split_states.append(self._pending_state(record.suffix)
                                      if record.split else None)

    def _pending_state(self,text,known_count=None):
        found=self._pending_ids.get(text)
        if found is not None:return found
        state_id=len(self._pending_text);self._pending_ids[text]=state_id
        self._pending_text.append(text)
        self._pending_count.append(self.counter.count(text) if known_count is None else known_count)
        return state_id

    def _transition_input(self,last_id,rid):
        current=self._records[rid]
        old_pending='' if last_id is None else self._pending_text[last_id]
        edge=old_pending+(self.separator if last_id is not None else '')+current.prefix
        old_count=0 if last_id is None else self._pending_count[last_id]
        return edge,old_count

    def _store_transition(self,key,rid,edge_count,edge,old_count):
        current=self._records[rid]
        if current.split:
            new_state=self._split_states[rid]
            delta=-old_count+edge_count+current.tokens+self._pending_count[new_state]
        else:
            new_state=self._pending_state(edge,edge_count);delta=-old_count+edge_count
        self._transitions[key]=(delta,new_state)

    def extend(self,total,last_id,text):
        rid=self._text_ids.get(text)
        if rid is None:return None
        key=(-1 if last_id is None else last_id,rid)
        transition=self._transitions.get(key)
        if transition is None:
            edge,old_count=self._transition_input(last_id,rid)
            edge_count=self.counter.count(edge)
            self._store_transition(key,rid,edge_count,edge,old_count)
            transition=self._transitions[key];self.misses+=1
        else:self.hits+=1
        return total+transition[0],transition[1]

    def info(self):
        return {'supported_texts':len(self._text_ids),'transition_entries':len(self._transitions),
                'pending_states':len(self._pending_text),
                'transition_hits':self.hits,'transition_misses':self.misses}


class CompactBoundaryCount(DelimitedBoundaryCount):
    def _segment(self,text):
        original=super()._segment(text)
        if original is None: return None
        return CountRegion(original.prefix,original.suffix,len(original.ids),original.split)

    def _admit(self,text,record):
        # Called only under the counter lock after construction/validation.
        size=sys.getsizeof(text)+256
        if record is not None:
            size+=sys.getsizeof(record)+sys.getsizeof(record.prefix)+sys.getsizeof(record.suffix)+sys.getsizeof(record.tokens)
        if text in self._prepared:
            _,released=self._prepared.pop(text); self._prepared_retained-=released
        if size>self._prepared_limit: return
        while self._prepared and (self._prepared_retained+size>self._prepared_limit or len(self._prepared)>=16384):
            _,(_,released)=self._prepared.popitem(last=False); self._prepared_retained-=released
        self._prepared[text]=record,size; self._prepared_retained+=size

    def prepare(self,texts):
        if not isinstance(texts,(list,tuple)) or any(not isinstance(t,str) for t in texts):
            raise TypeError('Prepared sources must be a list/tuple of text blocks')
        with self._lock:
            for text in dict.fromkeys(texts):
                if text in self._prepared: continue
                record=self._segment(text); self.compiled_parts+=1
                if record is None: self.compile_rejections+=1
                self._admit(text,record)

    def count_parts(self,parts):
        if not isinstance(parts,(list,tuple)) or any(not isinstance(t,str) for t in parts):
            raise TypeError('Context parts must be a list/tuple of text blocks')
        with self._lock:
            entries=[self._prepared.get(text) for text in parts]
            if not self.boundary_enabled or any(e is None or e[0] is None for e in entries):
                self.fallback_calls+=1
                return self.count('\n\n'.join(parts))
            pending=''; tokens=0
            for i,(rec,_) in enumerate(entries):
                if i: pending+='\n\n'
                pending+=rec.prefix
                if rec.split:
                    tokens+=self.count(pending)+rec.tokens; pending=rec.suffix
            tokens+=self.count(pending); self.boundary_calls+=1
            if tokens==0 and any(text.strip() for text in parts):
                raise PackError('Local tokenizer discarded all non-whitespace input')
            return tokens

    def initial_state(self):
        return PreparedCountState()

    def extend_state(self,state,text,separator='\n\n',transition_cache=None):
        """Return the exact state after appending one prepared text.

        ``None`` means this part cannot use the compiled representation. The
        caller must use the ordinary whole-context counter and, if it accepts
        that part, continue in fallback mode. Rejected unsupported parts do not
        invalidate the prior state.
        """
        if not isinstance(state,PreparedCountState):
            raise TypeError('Expected a PreparedCountState')
        if not isinstance(text,str) or not isinstance(separator,str):
            raise TypeError('Prepared text and separator must be strings')
        with self._lock:
            entry=self._prepared.get(text)
            if not self.boundary_enabled or entry is None or entry[0] is None:
                return None
            record=entry[0]
            if record.split:
                edge_key=('edge',state.pending if state.has_parts else None,
                          separator,record.prefix)
                if transition_cache is not None and edge_key in transition_cache:
                    edge_tokens=transition_cache[edge_key]
                else:
                    edge=state.pending+(separator if state.has_parts else '')+record.prefix
                    edge_tokens=self.count(edge)
                    if transition_cache is not None:transition_cache[edge_key]=edge_tokens
                finalized=state.finalized_tokens+edge_tokens+record.tokens
                pending=record.suffix
                tail_key=('tail',pending)
                if transition_cache is not None and tail_key in transition_cache:
                    tail_tokens=transition_cache[tail_key]
                else:
                    tail_tokens=self.count(pending)
                    if transition_cache is not None:transition_cache[tail_key]=tail_tokens
                total=finalized+tail_tokens
            else:
                finalized=state.finalized_tokens
                pending=state.pending+(separator if state.has_parts else '')+record.prefix
                total=finalized+self.count(pending)
            if total==0 and (state.has_parts or text.strip()):
                raise PackError('Local tokenizer discarded all non-whitespace input')
            return PreparedCountState(finalized,pending,True,total)

    def differential_ids(self,parts):
        raise NotImplementedError('Count-only records do not store token IDs; audit count_parts against upstream')


def encode_record(text,record):
    if record is None: return (len(text),None,None,None,None)
    return (len(text),len(record.prefix),len(text)-len(record.suffix),record.tokens,int(record.split))


def decode_record(text,values):
    if len(values)!=5: raise PackError('Invalid compiled count record')
    chars,prefix_end,suffix_start,tokens,split=values
    if type(chars) is not int or chars!=len(text): raise PackError('Compiled count source length differs')
    if all(value is None for value in values[1:]): return None
    if (any(type(v) is not int for v in values[1:]) or not 0<=prefix_end<=suffix_start<=chars
        or tokens<0 or split not in (0,1)
        or (split==0 and (prefix_end!=chars or suffix_start!=chars or tokens!=0))):
        raise PackError('Invalid compiled count record')
    return CountRegion(text[:prefix_end],text[suffix_start:],tokens,bool(split))
