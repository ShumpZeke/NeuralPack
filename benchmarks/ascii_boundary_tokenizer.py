"""Research: complete ASCII words as barriers for the pinned split expression.

PROVED UNDER ASSUMPTIONS: the inspected expression's letter alternatives stay
within a maximal ASCII letter run (plus at most one leading non-letter/number),
and other alternatives cannot consume letters. Keeping the complete first and
last runs therefore isolates the intervening pieces from LF-separated joins.
This depends on the pinned regex and deterministic per-piece model semantics.
Non-ASCII sources use the narrower numeric-barrier counter. No product default
or evidence-sufficiency claim follows from this tokenizer-specific argument.
"""
import re
from benchmarks.boundary_tokenizer import _Interior
from benchmarks.digit_boundary_tokenizer import DigitBoundaryCount


class AsciiBoundaryCount(DigitBoundaryCount):
    def _segment(self, text):
        if not text.isascii(): return super()._segment(text)
        if not self.boundary_enabled or self._added and self._added.search(text): return None
        words=list(re.finditer('[A-Za-z]+',text))
        if len(words)<2: return super()._segment(text)
        pieces=self._backend.pre_tokenizer.pre_tokenize_str(text)
        cursor=0; first=last=None
        for i,(_, (start,end)) in enumerate(pieces):
            if start!=cursor or end<start: return None
            cursor=end
            if end==words[0].end(): first=i
            if start<=words[-1].start()<end: last=i
        if cursor!=len(text) or first is None or last is None or first>=last:
            return super()._segment(text)
        prefix=text[:pieces[first][1][1]]; suffix=text[pieces[last][1][0]:]
        ids=tuple(token.id for piece,_ in pieces[first+1:last]
                  for token in self._backend.model.tokenize(piece))
        reconstructed=(self._backend.encode(prefix,add_special_tokens=False).ids+list(ids)
                       +self._backend.encode(suffix,add_special_tokens=False).ids)
        if reconstructed!=self._backend.encode(text,add_special_tokens=False).ids: return None
        return _Interior(prefix,suffix,ids,True)
