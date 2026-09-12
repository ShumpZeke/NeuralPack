# Cycle 32: language-aware symbol indexing and noise elimination

**STATUS: PROMOTED TO CORE RUNTIME. Evidence-verified storage and precision repair.**
Eliminated 51,616 noise rows (46.0% reduction in symbol rows) by filtering language keywords,
stopwords, and prose bare words from `symbols`. Reduced `.npk` artifact disk footprint by 21.1%
(from 13.86 MB to 10.94 MB) while preserving 100% of code definitions (4,376/4,376).
0 generative model calls.

---

## 1. Ground truth bottleneck & empirical discovery

Inspection of the SQLite schema and symbol tables on Click 8.5.0 revealed a massive storage
and index pollution defect:

1. **Severe Storage Waste**: The `symbols` table and its two b-tree indexes (`symbols_name` and
   `symbols_block`) consumed **6,537,216 bytes (47.2% of the entire 13.86 MB artifact)**.
2. **Extreme Reference Noise**: Of 112,259 symbol rows, only **4,376 (3.9%)** were definitions.
   **107,883 (96.1%)** were references.
3. **Keyword & Prose Infiltration**: `_extract_symbols` used `IDENT_RE = [A-Za-z_][A-Za-z0-9_]{2,}`
   across every block without language awareness. Consequently:
   - Python keywords were the most frequent "symbols" in the artifact: `def` (1,552 rows),
     `return` (896), `not` (929), `for` (860), `None` (717), `with` (702), `True` (598), `class` (575).
   - Prose files (`markdown`, `rst`, `text`, `toml`) contributed **35,657 bare-word references**
     for common English words (`the`, `and`, `that`, `from`, `value`).
   - When `_symbol_channel` ran during hybrid search for queries like `parameter`, changelog entries
     in `CHANGES.md` out-ranked actual source definitions in `src/click/core.py` because changelogs
     contained frequent repetitions of the word "parameter".

---

## 2. Implementation

In `npk/pack/compile.py`:
1. **Language-Aware Reference Extraction**: `_extract_symbols(block: RawBlock, language: str = "unknown")`
   now inspects file language.
2. **Keyword and Stopword Guard**: Python keywords (`keyword.iskeyword`) and stopwords (`STOPWORDS`)
   are excluded from reference symbols.
3. **Prose Noise Exclusion**: Non-code files (`markdown`, `rst`, `text`, `toml`) extract definitions
   (such as section headers or code block definitions) but skip emitting bare prose words as symbol references.
   FTS5 `lexical` remains the dedicated full-text search engine for prose.
4. **100% Definition Preservation**: All definitions (`DEF_RE`, `CONST_RE`, and `block.name`) continue
   to be indexed identically across all languages.

---

## 3. Measured evidence

Measured via `benchmarks/symbol_filter_eval.py` on Click 8.5.0:

| Metric | Baseline | Cleaned (Cycle 32) | Delta / Reduction |
|---|---:|---:|---:|
| Artifact size on disk | 13,860,864 B | 10,936,320 B | **-2,924,544 B (-21.1%)** |
| Total symbol rows | 112,259 | 60,643 | **-51,616 rows (-46.0%)** |
| Definitions preserved | 4,376 | 4,376 | **100.0% preserved** |
| Symbol table + index storage | 6,537,216 B | 3,612,672 B | **-2,924,544 B (-44.7%)** |
| Keyword references | 11,740 | 0 | **-100.0% eliminated** |
| Prose bare-word references | 35,657 | 0 | **-100.0% eliminated** |

### Retrieval Quality & Precision
- **Lexical Retrieval**: 20/20 checks across 10 query families and 2 budgets (512, 2048) remained 100% identical.
- **Hybrid Symbol Retrieval Precision**: Removing prose noise repaired false-positive ranking traps:
  - Query `parameter`: Previously returned 4 changelog fragments (`CHANGES.md:606-615`, `CHANGES.md:311-327`).
    Now directly retrieves the canonical definition in `src/click/core.py:169-205` (`class Parameter`).
  - Query `ExitStack`: Previously returned documentation fragments (`contextlib.rst`). Now retrieves the core
    implementation definitions in `cpython/Lib/contextlib.py:553-618`.

---

## 4. Verification Suite
- **Canonical test suite**: **1,159 passed, 22 symlink skips** (`cycle32-final-canonical-full.xml`).
- **Mutation testing**: **156/156 mutants assertion-killed** (`cycle32-final-canonical-mutations.json`).
- **Four new permanent regression tests** (`tests/test_symbol_index_cleanliness.py`):
  1. `test_keywords_and_stopwords_are_not_indexed_as_references`: Asserts language keywords and stopwords never enter `symbols` as references.
  2. `test_prose_files_do_not_emit_bare_word_symbol_references`: Asserts markdown/RST files emit 0 bare-word reference rows.
  3. `test_code_definitions_are_strictly_preserved`: Asserts 100% of function, class, and constant definitions survive.
  4. `test_incremental_update_maintains_clean_symbols`: Verifies incremental update preserves clean symbol invariants.
- **Two new mutation tripwires** in `benchmarks/contract_mutations.py`:
  - `symbols_include_language_keywords`: catches keyword guard bypass.
  - `symbols_prose_references_unfiltered`: catches prose reference guard bypass.
