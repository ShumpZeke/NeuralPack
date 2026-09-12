"""Research: safely delimited ASCII words inside mixed-Unicode source.

PROVED UNDER ASSUMPTIONS: ASCII non-letter neighbors make an ASCII letter run
maximal for the pinned regex's letter branches. Keep the complete first/last
eligible runs and their actual leading prefix pieces. Unicode between those
barriers is fixed source input; it does not change the isolation argument.
The pinned regex, LF join, immutable pipeline and trusted prepared state remain
required. Other inputs use numeric barriers or the upstream encoder.
"""
import re
from benchmarks.boundary_tokenizer import _Interior
from benchmarks.digit_boundary_tokenizer import DigitBoundaryCount


def safe_words(text):
    return [word for word in re.finditer('[A-Za-z]+',text)
            if (word.start()==0 or text[word.start()-1].isascii())
            and (word.end()==len(text) or text[word.end()].isascii())]


class DelimitedBoundaryCount(DigitBoundaryCount):
    def _segment(self, text):
        if not self.boundary_enabled or self._added and self._added.search(text): return None
        words=safe_words(text)
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
