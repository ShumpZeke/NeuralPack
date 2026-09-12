"""Experimental admission counter; public ranking and final checks unchanged."""
from benchmarks.boundary_tokenizer import BoundaryCount
from npk.pack import PackSelector


class BoundarySelector(PackSelector):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not isinstance(self.tokenizer, BoundaryCount):
            raise ValueError('An explicit prepared BoundaryCount is required')

    def _fits(self, evidence, text, budget, *, used_chars=None):
        return self.tokenizer.count_parts([e.text for e in evidence]+[text]) <= budget
