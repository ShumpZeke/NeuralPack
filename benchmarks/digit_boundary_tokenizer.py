"""Research challenger using numeric barriers in one pinned pre-tokenizer.

PROVED UNDER ASSUMPTIONS: a digit is a one-character match and no other
alternative in the inspected split expression can consume it. With no active
added token or normalization, its two edges isolate the model's piece input.
This statement depends on the pinned expression and per-piece BPE pipeline;
it is not a claim about arbitrary tokenizers or evidence sufficiency.
"""
from benchmarks.boundary_tokenizer import BoundaryCount, _Interior


class DigitBoundaryCount(BoundaryCount):
    def _segment(self, text):
        if not self.boundary_enabled or self._added and self._added.search(text): return None
        pieces = self._backend.pre_tokenizer.pre_tokenize_str(text)
        cursor = 0; anchors = []
        for i, (piece, (start, end)) in enumerate(pieces):
            if start != cursor or end < start: return None
            cursor = end
            # Deliberately narrower than Unicode isdigit(): these codepoints
            # have invariant membership in the inspected regex's number class.
            if end == start+1 and text[start:end] in '0123456789' and piece == text[start:end]:
                anchors.append(i)
        if cursor != len(text): return None
        if len(anchors) < 2: return _Interior(text, '', (), False)
        first, last = anchors[0], anchors[-1]
        prefix = text[:pieces[first][1][1]]; suffix = text[pieces[last][1][0]:]
        ids = tuple(token.id for piece, _ in pieces[first+1:last]
                    for token in self._backend.model.tokenize(piece))
        reconstructed = (self._backend.encode(prefix, add_special_tokens=False).ids + list(ids)
                         + self._backend.encode(suffix, add_special_tokens=False).ids)
        if reconstructed != self._backend.encode(text, add_special_tokens=False).ids: return None
        return _Interior(prefix, suffix, ids, True)
