"""M006: the product's shipped optional semantic mode, measured as shipped.

``compile_pack(mode="semantic")`` embeds every block with the local MiniLM
encoder at compile time; ``PackSelector(retrieval="hybrid")`` adds a cosine
channel over the whole index (gated by ``dense_floor``) and the symbol channel
to the RRF. E012/M004 measured prototypes (pool re-ranking); this arm measures
the feature a user can enable today.
"""
from __future__ import annotations

from ..arms import Arm, register

register(Arm("npk_hybrid", compile_options={"mode": "semantic"}, selector_options={"retrieval": "hybrid"}))
