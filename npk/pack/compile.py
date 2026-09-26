"""Compile a source tree into a .npk artifact. No generative model is involved.

This is where the expensive, reusable work happens, so that query time is cheap:
block splitting, symbol extraction, lexical indexing, and (optionally) embedding.

Incremental update is content-hash driven: a file whose SHA-256 is unchanged is
skipped entirely, and a changed file invalidates only its own blocks.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import tempfile
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import warnings

from .format import (
    COMPILE_MODES, MODE_DETERMINISTIC, MODE_SEMANTIC, PACK_FORMAT_VERSION,
    SCHEMA, PackError, compute_root_digest, connect,
)
from .integrity import install_tracking, refresh_file_digests, require_clean_cache, check_cached_base
from .search import analyzed_text
from .source_policy import SKIP_REASONS, check_source, credential_kind, safe_label, stat_identity

#: Directories and files never read into an artifact. Credential-bearing names
#: are excluded by name. Ordinary source still requires secret review.
#: "build" is intentionally eligible: real projects keep authored source there
#: (for example SQLAlchemy's doc/build). A generic name is not proof of generated data.
EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "dist", ".tox",
    ".idea", ".vscode", "secrets", ".aws", ".ssh", ".azure", ".gcloud",
})
EXCLUDED_FILE_RE = re.compile(
    r"(^\.env($|\.)|(^|[._-])secret|credential|(^|[._-])token(s)?\.json$|"
    r"\.(pem|key|p12|pfx|pyc|so|dll|dylib|bin|npk)$|^id_(rsa|ed25519))",
    re.IGNORECASE,
)

TEXT_SUFFIXES = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".rs": "rust",
    ".java": "java", ".rb": "ruby", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".hpp": "cpp", ".cs": "csharp", ".php": "php", ".sh": "shell",
    ".md": "markdown", ".rst": "rst", ".txt": "text", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini",
    ".cfg": "ini", ".sql": "sql", ".html": "html", ".css": "css",
}

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_BLOCK_TOKENS = 1200
# Format v8 keeps the symbol schema, but the compiler's derived symbol policy
# and external-content lexical maintenance are part of the update contract.
# Reference rows were measured to be noisy and unused by the default path;
# v8 stores definitions/constants and structural names only. Old packs remain
# readable only through the older build; update_pack requires a fresh compile.
COMPILER_VERSION = "8.0"


def estimate_tokens(text: str) -> int:
    """Cheap deterministic token estimate (~4 chars/token), no tokenizer needed.

    Provider adapters may supply an exact tokenizer; the artifact stays
    provider-independent by storing this neutral estimate.
    """
    return max(1, len(text) // 4)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CompileStats:
    files_scanned: int = 0
    files_indexed: int = 0
    files_skipped_unchanged: int = 0
    files_removed: int = 0
    blocks: int = 0
    symbols: int = 0
    relations: int = 0
    deps: int = 0
    embedded: int = 0
    seconds: float = 0.0
    mode: str = MODE_DETERMINISTIC
    embedding_model: Optional[str] = None
    embedding_status: str = "disabled"
    encoder_rows_requested: int = 0
    embedding_rows_reused: int = 0
    dependency_index: bool = False
    integrity_files_hashed: int = 0
    integrity_files_reused: int = 0
    #: Eligible-suffix files left out because their content is not indexable
    #: text (binary/NUL, non-UTF-8, oversized, credential-like, outside root).
    #: Each entry is {"path": redacted label, "reason": code}. Never silent.
    skipped_sources: List[Dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------------
# Block splitting
# ---------------------------------------------------------------------------

@dataclass
class RawBlock:
    ordinal: int
    kind: str
    name: Optional[str]
    start_line: int
    end_line: int
    text: str
    symbols: List[Tuple[str, str, bool]] = field(default_factory=list)  # (name, kind, is_def)
    imports: List[str] = field(default_factory=list)


def _class_member_spans(node: ast.ClassDef, qualified_name: str) -> List[Tuple[int,int,str,str]]:
    """Disjoint raw spans for methods and their remaining class-body context."""
    cursor = min([node.lineno] + [d.lineno for d in node.decorator_list])
    spans = []
    for member in node.body:
        if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = min([member.lineno] + [d.lineno for d in member.decorator_list])
        if start > cursor:
            spans.append((cursor,start-1,"class_context",qualified_name))
        name = qualified_name + "." + member.name
        if isinstance(member,ast.ClassDef):
            spans.extend(_class_member_spans(member,name))
        else:
            spans.append((start,member.end_lineno,"method",name))
        cursor = member.end_lineno + 1
    if cursor <= node.end_lineno:
        spans.append((cursor,node.end_lineno,"class_context",qualified_name))
    return spans


def _source_lines(source: str) -> List[str]:
    """Physical CR/LF lines. Unicode separators and form feeds are source data."""
    normalized=source.replace("\r\n","\n").replace("\r","\n")
    lines=normalized.split("\n")
    if lines and lines[-1]=="":lines.pop()  # Terminal newline is not another source line.
    return lines


# One-entry parse cache keyed by object identity: splitting and raise-site
# extraction receive the same ``str`` for a file, so it is parsed once. An
# identity check cannot return a tree for different text.
_LAST_PARSE: Tuple[Optional[str], Optional[ast.Module]] = (None, None)


def _parse_python(source: str) -> Optional[ast.Module]:
    """Parse a Python file, or return None when it does not parse.

    Repository code routinely contains deprecated escapes; the per-file
    SyntaxWarnings they raise are diagnostics about the source, not the build.
    """
    global _LAST_PARSE
    cached_source, cached_tree = _LAST_PARSE
    if cached_source is source:
        return cached_tree
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        try:
            tree: Optional[ast.Module] = ast.parse(source)
        except SyntaxError:
            tree = None
    _LAST_PARSE = (source, tree)
    return tree


def _split_python(source: str, *, python_members: bool = False) -> List[RawBlock]:
    """Split Python into top-level defs/classes plus a module-preamble block.

    Falls back to line-window splitting when the file does not parse, so a
    syntax error never costs us the whole file.
    """
    tree = _parse_python(source)
    if tree is None:
        return _split_lines(source)

    lines = _source_lines(source)
    blocks: List[RawBlock] = []
    spans: List[Tuple[int, int, str, str]] = []

    for node in tree.body:
        if python_members and isinstance(node, ast.ClassDef):
            spans.extend(_class_member_spans(node,node.name))
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            end = getattr(node, "end_lineno", start) or start
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            spans.append((start, end, kind, node.name))

    spans.sort()
    covered = {ln for s, e, _k, _n in spans for ln in range(s, e + 1)}
    preamble = [ln for ln in range(1, len(lines) + 1) if ln not in covered]

    ordinal = 0
    if preamble:
        # Contiguous runs of uncovered lines become "module" blocks (imports,
        # constants, __all__ -- exactly where config values live).
        run: List[int] = []
        for ln in preamble + [None]:  # sentinel flushes the last run
            if run and (ln is None or ln != run[-1] + 1):
                text = "\n".join(lines[run[0] - 1:run[-1]])
                if text.strip():
                    blocks.append(RawBlock(ordinal, "module", None, run[0], run[-1], text))
                    ordinal += 1
                run = []
            if ln is not None:
                run.append(ln)

    for start, end, kind, name in spans:
        text = "\n".join(lines[start - 1:end])
        blocks.append(RawBlock(ordinal, kind, name, start, end, text))
        ordinal += 1

    blocks.sort(key=lambda b: b.start_line)
    for i, b in enumerate(blocks):
        b.ordinal = i
    return [b for b in blocks if b.text.strip()] or _split_lines(source)


def _split_markdown(source: str) -> List[RawBlock]:
    lines = _source_lines(source)
    blocks: List[RawBlock] = []
    start = 1
    heading: Optional[str] = None
    buf: List[str] = []
    ordinal = 0

    def flush(end_line: int) -> None:
        nonlocal ordinal, buf, start, heading
        text = "\n".join(buf)
        if text.strip():
            blocks.append(RawBlock(ordinal, "section", heading, start, end_line, text))
            ordinal += 1
        buf = []

    for i, line in enumerate(lines, 1):
        if re.match(r"^#{1,6}\s+", line) and buf:
            flush(i - 1)
            start = i
            heading = line.lstrip("#").strip()
        elif re.match(r"^#{1,6}\s+", line):
            start = i
            heading = line.lstrip("#").strip()
        buf.append(line)
    flush(len(lines))
    return blocks or _split_lines(source)


RST_ADORNMENTS = frozenset('=-~^"#*+<')
RST_DIRECTIVE_RE = re.compile(r"^( *)\.\. (code-block|class)::\s*(.*?)\s*$")
BRACE_LANGUAGES = frozenset({
    "javascript", "typescript", "go", "rust", "java", "c", "cpp", "csharp", "php",
})


def _rst_adornment(line: str) -> Optional[str]:
    """Return the repeated RST adornment character for a column-zero run."""
    if len(line) < 3 or line != line.strip() or line[0] not in RST_ADORNMENTS:
        return None
    return line[0] if all(char == line[0] for char in line) else None


def _rst_title(line: str) -> Optional[str]:
    title = line.strip()
    if line != title or not title or title.startswith(".. "):
        return None
    return title if any(char.isalnum() for char in title) else None


def _rst_heading_events(lines: Sequence[str]) -> List[Tuple[int, int, str]]:
    """Return ``(start, header_end, heading_path)`` using RST's local style order."""
    headings: List[Tuple[int, int, str, Tuple[str, bool]]] = []
    index = 0
    while index < len(lines):
        overline = _rst_adornment(lines[index])
        if overline and index + 2 < len(lines):
            title = _rst_title(lines[index + 1])
            underline = _rst_adornment(lines[index + 2])
            if (title and underline == overline and len(lines[index]) >= len(title)
                    and len(lines[index + 2]) >= len(title)):
                headings.append((index, index + 2, title, (overline, True)))
                index += 3
                continue
        if index + 1 < len(lines):
            title = _rst_title(lines[index])
            underline = _rst_adornment(lines[index + 1])
            if title and underline and len(lines[index + 1]) >= len(title):
                headings.append((index, index + 1, title, (underline, False)))
                index += 2
                continue
        index += 1

    styles: List[Tuple[str, bool]] = []
    stack: List[str] = []
    events: List[Tuple[int, int, str]] = []
    for start, end, title, style in headings:
        if style not in styles:
            styles.append(style)
        level = styles.index(style)
        if level < len(stack):
            stack = stack[:level]
        # Malformed documents can revisit a deep style without its parents.
        # Keeping the available ancestry is safer than inventing missing names.
        stack.append(title)
        events.append((start, end, " > ".join(stack)))
    return events


def _append_source_block(blocks: List[RawBlock], lines: Sequence[str], start: int, end: int,
                         kind: str, name: Optional[str]) -> None:
    if start > end:
        return
    text = "\n".join(lines[start:end + 1])
    if text.strip():
        blocks.append(RawBlock(len(blocks), kind, name, start + 1, end + 1, text))


def _split_rst_segment(blocks: List[RawBlock], lines: Sequence[str], start: int, end: int,
                       name: Optional[str]) -> None:
    """Split named object/code directives while retaining their section ancestry."""
    cursor = start
    index = start
    while index <= end:
        match = RST_DIRECTIVE_RE.match(lines[index])
        # Nested directive-looking lines are usually literal/directive content.
        if match is None or match.group(1):
            index += 1
            continue
        directive_end = index
        probe = index + 1
        while probe <= end:
            line = lines[probe]
            if not line.strip() or len(line) - len(line.lstrip(" ")) > 0:
                directive_end = probe
                probe += 1
                continue
            break
        _append_source_block(blocks, lines, cursor, index - 1, "section", name)
        directive, argument = match.group(2), match.group(3).strip()
        label = directive + ((" " + argument) if argument else "")
        directive_name = " > ".join(part for part in (name, label) if part)
        _append_source_block(blocks, lines, index, directive_end, "directive", directive_name)
        cursor = probe
        index = probe
    _append_source_block(blocks, lines, cursor, end, "section", name)


def _split_rst(source: str) -> List[RawBlock]:
    lines = _source_lines(source)
    events = _rst_heading_events(lines)
    blocks: List[RawBlock] = []
    cursor = 0
    name: Optional[str] = None
    for start, _header_end, heading_path in events:
        _split_rst_segment(blocks, lines, cursor, start - 1, name)
        cursor = start
        name = heading_path
    _split_rst_segment(blocks, lines, cursor, len(lines) - 1, name)
    return blocks or _split_lines(source)


@dataclass(frozen=True)
class _BraceDefinition:
    start: int
    end: int
    depth: int
    kind: str
    name: str


def _mask_brace_source(lines: Sequence[str], language: str) -> List[str]:
    """Blank comments and literals so their braces cannot create boundaries."""
    masked: List[str] = []
    block_comment = False
    quote: Optional[str] = None
    escaped = False
    for line in lines:
        out = list(line)
        index = 0
        while index < len(line):
            char = line[index]
            nxt = line[index + 1] if index + 1 < len(line) else ""
            if block_comment:
                out[index] = " "
                if char == "*" and nxt == "/":
                    out[index + 1] = " "
                    block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if quote is not None:
                out[index] = " "
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                index += 1
                continue
            if char == "/" and nxt == "/":
                out[index:] = " " * (len(line) - index)
                break
            if char == "/" and nxt == "*":
                out[index] = out[index + 1] = " "
                block_comment = True
                index += 2
                continue
            if language == "php" and char == "#":
                out[index:] = " " * (len(line) - index)
                break
            if char in "'\"`":
                quote = char
                escaped = False
                out[index] = " "
            index += 1
        # Ordinary quoted literals cannot cross a physical line. Backtick
        # templates can, and braces inside them remain data rather than syntax.
        if quote in ("'", '"'):
            quote = None
            escaped = False
        masked.append("".join(out))
    return masked


def _brace_layout(masked: Sequence[str]):
    depths: List[int] = []
    opens: List[Tuple[int, int, int]] = []
    pairs: Dict[Tuple[int, int], int] = {}
    stack: List[Tuple[int, int]] = []
    for line_number, line in enumerate(masked):
        depths.append(len(stack))
        for column, char in enumerate(line):
            if char == "{":
                opens.append((line_number, column, len(stack)))
                stack.append((line_number, column))
            elif char == "}" and stack:
                pairs[stack.pop()] = line_number
    return depths, opens, pairs


def _brace_header(line: str, language: str, *, general: bool = False) -> Optional[Tuple[str, str]]:
    if not line.strip() or line.lstrip().startswith(("#", "//", "/*")):
        return None
    if language == "go":
        match = re.search(r"\btype\s+([A-Za-z_][A-Za-z0-9_]*)\s+(struct|interface)\b", line)
        if match:
            return match.group(2), match.group(1)
        match = re.search(r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if match:
            return "function", match.group(1)
    if language == "rust":
        match = re.search(r"\bimpl(?:\s*<[^>{}]*>)?\s+(?:[^{}]*\s+for\s+)?([A-Za-z_][A-Za-z0-9_:]*)", line)
        if match:
            return "impl", match.group(1).rsplit("::", 1)[-1]
        match = re.search(r"\bfn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if match:
            return "function", match.group(1)
    if language in {"javascript", "typescript", "php"}:
        match = re.search(r"\bfunction\s*[*&]?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if match:
            return "function", match.group(1)
    if language in {"javascript", "typescript"}:
        match = re.search(r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=.+=>", line)
        if match:
            return "function", match.group(1)

    match = re.search(
        r"\b(class|interface|struct|enum|trait|namespace|record|union)\s+([A-Za-z_][A-Za-z0-9_]*)",
        line,
    )
    if match:
        return match.group(1), match.group(2)
    if not general or "(" not in line:
        return None
    prefix = line[:line.find("(")].strip()
    if (not prefix or "=" in prefix or "->" in prefix or prefix.startswith((
            "return ", "throw ", "new ", "delete ", "typedef ", "using ", "case ", "@",
    ))):
        return None
    match = re.search(r"(~?[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*)\s*$", prefix)
    if match is None:
        return None
    name = match.group(1)
    if name.lower().lstrip("~") in {
        "if", "for", "foreach", "while", "switch", "catch", "with", "lock", "sizeof",
        "typeof", "alignof", "decltype", "assert", "synchronized",
    }:
        return None
    return "function", name.rsplit("::", 1)[-1]


def _definition_open(start: int, depth: int, masked: Sequence[str],
                     opens: Sequence[Tuple[int, int, int]],
                     pairs: Dict[Tuple[int, int], int]) -> Optional[Tuple[int, int]]:
    for line_number, column, open_depth in opens:
        if line_number < start:
            continue
        if line_number > start + 20:
            break
        if open_depth != depth or (line_number, column) not in pairs:
            continue
        header = "\n".join([*masked[start:line_number], masked[line_number][:column]])
        if ";" in header:
            return None
        return line_number, pairs[(line_number, column)]
    return None


def _split_braces(source: str, language: str) -> List[RawBlock]:
    lines = _source_lines(source)
    masked = _mask_brace_source(lines, language)
    depths, opens, pairs = _brace_layout(masked)
    definitions: List[_BraceDefinition] = []

    for index, line in enumerate(masked):
        header = _brace_header(line, language)
        if header is None:
            continue
        extent = _definition_open(index, depths[index], masked, opens, pairs)
        if extent is not None:
            definitions.append(_BraceDefinition(index, extent[1], depths[index], *header))

    type_kinds = {"class", "interface", "struct", "enum", "trait", "namespace", "record", "union", "impl"}
    for index, line in enumerate(masked):
        if any(item.start == index for item in definitions):
            continue
        inside_type = any(
            item.kind in type_kinds and item.start < index < item.end and depths[index] == item.depth + 1
            for item in definitions
        )
        top_level_c = language in {"c", "cpp"} and depths[index] == 0
        if not (inside_type or top_level_c):
            continue
        header = _brace_header(line, language, general=True)
        if header is None:
            continue
        extent = _definition_open(index, depths[index], masked, opens, pairs)
        if extent is not None:
            definitions.append(_BraceDefinition(index, extent[1], depths[index], *header))

    definitions = sorted(set(definitions), key=lambda item: (item.start, -item.end, item.name))
    if not definitions:
        return _split_lines(source)

    parents: Dict[_BraceDefinition, Optional[_BraceDefinition]] = {}
    for item in definitions:
        containers = [
            other for other in definitions
            if other.start < item.start and item.end < other.end
        ]
        parents[item] = min(containers, key=lambda other: other.end - other.start) if containers else None
    children = {
        item: sorted((child for child, parent in parents.items() if parent == item), key=lambda child: child.start)
        for item in definitions
    }
    roots = sorted((item for item, parent in parents.items() if parent is None), key=lambda item: item.start)
    blocks: List[RawBlock] = []

    def emit(item: _BraceDefinition, prefix: Optional[str] = None) -> None:
        qualified = f"{prefix}.{item.name}" if prefix else item.name
        direct = children[item]
        if not direct:
            _append_source_block(blocks, lines, item.start, item.end, item.kind, qualified)
            return
        cursor = item.start
        for child in direct:
            _append_source_block(blocks, lines, cursor, child.start - 1,
                                 item.kind + "_context", qualified)
            emit(child, qualified)
            cursor = child.end + 1
        _append_source_block(blocks, lines, cursor, item.end, item.kind + "_context", qualified)

    cursor = 0
    for root in roots:
        _append_source_block(blocks, lines, cursor, root.start - 1, "module", None)
        emit(root)
        cursor = root.end + 1
    _append_source_block(blocks, lines, cursor, len(lines) - 1, "module", None)
    for ordinal, block in enumerate(blocks):
        block.ordinal = ordinal
    return blocks or _split_lines(source)


def _split_lines(source: str, window: int = 60) -> List[RawBlock]:
    lines = _source_lines(source)
    blocks = []
    for i in range(0, len(lines), window):
        chunk = lines[i:i + window]
        text = "\n".join(chunk)
        if text.strip():
            blocks.append(RawBlock(len(blocks), "chunk", None, i + 1, i + len(chunk), text))
    return blocks


_STATEMENT_FIELDS = ("body", "orelse", "finalbody", "handlers", "cases")


def _statements(tree: ast.AST) -> Iterable[ast.AST]:
    """Every statement node (plus handler/case wrappers) in the tree.

    ``raise`` is a statement and cannot occur inside an expression, so this
    visits the same Raise nodes as ``ast.walk`` while skipping expression
    subtrees, which are most of a module's nodes.
    """
    stack: List[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        yield node
        for name in _STATEMENT_FIELDS:
            children = getattr(node, name, None)
            if children:
                stack.extend(children)


def _python_raise_sites(source: str) -> List[Tuple[int, int, str]]:
    """Return literal named raise sites in physical source coordinates."""
    tree = _parse_python(source)
    if tree is None:
        return []
    sites: List[Tuple[int, int, str]] = []
    for node in _statements(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        value = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if isinstance(value, ast.Name):
            name = value.id
        elif isinstance(value, ast.Attribute):
            name = value.attr
        else:
            continue
        sites.append((node.lineno, getattr(node, "end_lineno", node.lineno), name.lower()))
    return sites


IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
DEF_RE = re.compile(r"^\s*(?:def|class|function|fn|func|type|struct|interface)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
CONST_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]{2,})\s*[:=]", re.MULTILINE)
IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)


def _extract_symbols(block: RawBlock, language: str = "unknown") -> None:
    """Extract only high precision definition and structural-name rows.

    The FTS index already covers references in source text. A second table of
    every identifier occurrence made the optional symbol channel amplify
    repeated call-site and prose noise, while definitions and section names
    remained the useful exact lookup. Keeping this table definition-only also
    makes its size proportional to retrievable structure rather than corpus
    word frequency.
    """
    seen: Dict[str, Tuple[str, bool]] = {}
    for m in DEF_RE.finditer(block.text):
        seen[m.group(1)] = ("definition", True)
    for m in CONST_RE.finditer(block.text):
        seen.setdefault(m.group(1), ("constant", True))
    if block.name:
        seen.setdefault(block.name, ("definition", True))
    block.symbols = [(n, k, d) for n, (k, d) in seen.items()]
    block.imports = [m.group(1) or m.group(2) for m in IMPORT_RE.finditer(block.text)]



def split_source(text: str, language: str, *, python_members: bool = False) -> List[RawBlock]:
    # Independent turn splitting was discarded: it separated updates from the
    # facts and constraints they refer to. Keep source windows until an explicit
    # conversation-state representation earns promotion on answer-quality tests.
    if language == "python":
        blocks = _split_python(text, python_members=python_members)
    elif language == "markdown":
        blocks = _split_markdown(text)
    elif language == "rst":
        blocks = _split_rst(text)
    elif language in BRACE_LANGUAGES:
        blocks = _split_braces(text, language)
    else:
        blocks = _split_lines(text)

    # Cap oversized blocks so one huge function cannot dominate a budget.
    capped: List[RawBlock] = []
    for b in blocks:
        if estimate_tokens(b.text) <= MAX_BLOCK_TOKENS:
            capped.append(b)
            continue
        # Block text was joined from source lines; a final empty component is
        # an included blank line and must survive recapping with its span.
        lines = b.text.split("\n")
        window = max(20, len(lines) // (estimate_tokens(b.text) // MAX_BLOCK_TOKENS + 1))
        for i in range(0, len(lines), window):
            chunk_lines = lines[i:i + window]
            chunk = "\n".join(chunk_lines)
            if chunk.strip():
                capped.append(RawBlock(len(capped), b.kind, b.name,
                                       b.start_line + i, b.start_line + i + len(chunk_lines) - 1, chunk))
    for i, b in enumerate(capped):
        b.ordinal = i
        _extract_symbols(b, language=language)
    return capped


# ---------------------------------------------------------------------------
# Source scanning
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str
    sha256: str
    size: int
    language: str
    mtime_ns: int


def _source_scan_error(error: OSError) -> None:
    # Do not include opaque OS error text or file contents in diagnostics.
    raise PackError(f"incomplete source scan at {safe_label(error.filename or 'unknown path')} "
                    f"({type(error).__name__}); fix access and retry") from None


class UnsupportedSource(PackError):
    """A file's content is not indexable text. ``reason`` is a stable code."""

    def __init__(self, message: str, reason: str, label: str):
        super().__init__(message)
        self.reason = reason
        self.label = label


def scan_source(root: str | Path, *, known_files: Optional[Dict[str, Tuple[str, int, int]]] = None,
                indexed: Optional[set] = None, strict: bool = False,
                skipped: Optional[List[Dict[str, str]]] = None) -> List[SourceFile]:
    """Read every eligible source file under *root*.

    Content that is not indexable text (binary/NUL, non-UTF-8, over 2 MiB,
    credential-like, or a link resolving outside the root) is **skipped and
    reported** in *skipped* when that path has never been indexed. It still
    aborts the scan when the path is already indexed (a previously searchable
    file must not silently lose its evidence) or when *strict* is set. Read
    and access failures always abort: they are not evidence of absence.
    """
    root = Path(root).resolve()
    check_source(str(root),'source root path')
    if not root.is_dir():
        raise PackError(f"source root is not a directory: {root}")
    indexed = indexed or set()

    out: List[SourceFile] = []
    for dirpath, dirnames, filenames in os.walk(root,onerror=_source_scan_error):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if EXCLUDED_FILE_RE.search(fn):
                continue
            language = TEXT_SUFFIXES.get(Path(fn).suffix.lower())
            if language is None:
                continue
            full = Path(dirpath) / fn
            rel = full.relative_to(root).as_posix()
            try:
                source = _read_source(root, full, rel, language, known_files)
            except UnsupportedSource as unsupported:
                if strict or rel in indexed or skipped is None:
                    raise
                skipped.append({"path": unsupported.label, "reason": unsupported.reason})
                continue
            if source is not None:
                out.append(source)
    return out


def _read_source(root: Path, full: Path, rel: str, language: str,
                 known_files: Optional[Dict[str, Tuple[str, int, int]]]) -> Optional[SourceFile]:
    label = safe_label(rel)
    if credential_kind(rel) is not None:
        check_source(rel, 'source relative path')  # raises with a redacted message
    try:
        if not full.resolve().is_relative_to(root):
            raise UnsupportedSource(f"source path resolves outside the requested root: {label}",
                                    "outside_root", label)
        st = full.stat()
        if st.st_size > MAX_FILE_BYTES:
            raise UnsupportedSource(f"source exceeds size limit ({MAX_FILE_BYTES} bytes): {label}",
                                    "oversize", label)
        if st.st_size == 0:
            return None

        if known_files and rel in known_files:
            k_sha, k_size, k_mtime = known_files[rel]
            if st.st_size == k_size and st.st_mtime_ns == k_mtime and k_mtime != 0:
                return SourceFile(path=rel, text="", sha256=k_sha, size=k_size,
                                  language=language, mtime_ns=st.st_mtime_ns)

        raw = full.read_bytes()
        after = full.stat()
        if stat_identity(st)!=stat_identity(after) or len(raw)!=after.st_size:
            raise PackError(f"source changed during read: {label}; retry a stable checkout")
    except OSError as error:
        _source_scan_error(error)
    if len(raw) > MAX_FILE_BYTES:
        raise UnsupportedSource(f"source exceeds size limit ({MAX_FILE_BYTES} bytes): {label}",
                                "oversize", label)
    if b"\x00" in raw:
        raise UnsupportedSource(f"source contains NUL bytes: {label}; convert the input explicitly",
                                "nul", label)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise UnsupportedSource(f"source is not valid UTF-8: {label}; "
                                "convert its encoding explicitly before compiling",
                                "non_utf8", label) from None
    kind = credential_kind(text)
    if kind is not None:
        raise UnsupportedSource(f'source contains potential credential ({kind}): {label}; '
                                'remove it from the source or compile a reviewed source collection',
                                "credential", label)
    return SourceFile(path=rel, text=text, sha256=hashlib.sha256(raw).hexdigest(),
                      size=len(raw), language=language, mtime_ns=st.st_mtime_ns)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _pack_vector(vec: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vector(blob: bytes, dim: int) -> List[float]:
    return list(struct.unpack(f"<{dim}f", blob))


def _write_file_blocks(con: sqlite3.Connection, file_id: int, src: SourceFile,
                       python_members: bool = False) -> Tuple[int, int, int]:
    from .conflict import extract_assignments

    blocks = split_source(src.text, src.language, python_members=python_members)
    n_blocks = n_symbols = n_relations = 0
    lex_rows: List[Tuple[int, str, str, str]] = []
    sym_rows: List[Tuple[str, int, str, int]] = []
    relation_rows: List[Tuple[int, str, str]] = []
    assign_rows: List[Tuple[str, int, str]] = []
    path_field = analyzed_text(src.path.rsplit(".", 1)[0])
    raise_sites = _python_raise_sites(src.text) if src.language == "python" else []

    for b in blocks:
        text = b.text
        sha = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
        cur = con.execute(
            "INSERT INTO blocks(file_id, ordinal, kind, name, start_line, end_line, tokens, sha256, text, path)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (file_id, b.ordinal, b.kind, b.name, b.start_line, b.end_line,
             estimate_tokens(text), sha, text, path_field),
        )
        block_id = cur.lastrowid
        # Search fields are derived metadata. blocks.text remains the exact
        # evidence source and is the only text emitted to a caller.
        lex_rows.append((
            block_id,
            analyzed_text(text),
            analyzed_text(b.name or ""),
            path_field,
        ))
        if b.symbols:
            sym_rows.extend((n, block_id, k, int(d)) for n, k, d in b.symbols)
            n_symbols += len(b.symbols)

        raised = {
            name for start, end, name in raise_sites
            if b.start_line <= start and end <= b.end_line
        }
        if raised:
            relation_rows.extend((block_id, "raises", name) for name in sorted(raised))
            n_relations += len(raised)

        # Constant assignments feed query-time conflict resolution.
        pairs = extract_assignments(text)
        if pairs:
            assign_rows.extend((sym, block_id, vh) for sym, vh in pairs)
        n_blocks += 1

    if lex_rows:
        con.executemany(
            "INSERT INTO lexical(rowid, text, name, path) VALUES(?,?,?,?)", lex_rows
        )
    if sym_rows:
        con.executemany("INSERT INTO symbols(name, block_id, kind, is_def) VALUES(?,?,?,?)", sym_rows)
    if relation_rows:
        con.executemany(
            "INSERT INTO relations(block_id, kind, name) VALUES(?,?,?)", relation_rows
        )
    if assign_rows:
        con.executemany("INSERT OR IGNORE INTO assignments(symbol, block_id, value_hash) VALUES(?,?,?)", assign_rows)

    return n_blocks, n_symbols, n_relations


def _drop_lexical(con: sqlite3.Connection, file_ids: Sequence[int]) -> None:
    """Remove obsolete postings before replacement blocks are inserted.

    External-content FTS5 needs the exact indexed field values for a delete.
    The values are derived from only the affected blocks, then sent through one
    bounded ``executemany`` batch; there is no per-block SQL variable list and
    no scan of unrelated source text.
    """
    if not file_ids:
        return
    con.execute("CREATE TEMP TABLE npk_obsolete_files(file_id INTEGER PRIMARY KEY)")
    con.executemany("INSERT INTO npk_obsolete_files(file_id) VALUES(?)",
                    ((file_id,) for file_id in file_ids))
    rows = con.execute(
        "SELECT b.id,b.text,b.name,b.path FROM blocks b "
        "JOIN npk_obsolete_files o ON o.file_id=b.file_id ORDER BY b.id"
    ).fetchall()
    _delete_lexical_rows(con, rows)
    con.execute("DROP TABLE npk_obsolete_files")


def _drop_file(con: sqlite3.Connection, file_id: int, *, drop_lexical: bool = True) -> None:
    if drop_lexical:
        rows = con.execute(
            "SELECT id,text,name,path FROM blocks WHERE file_id=? ORDER BY id", (file_id,)
        ).fetchall()
        _delete_lexical_rows(con, rows)
    con.execute("DELETE FROM files WHERE id=?", (file_id,))  # cascades


def _delete_lexical_rows(con: sqlite3.Connection, rows: Iterable[sqlite3.Row]) -> None:
    """Apply source-aware external-content FTS deletes for existing blocks."""
    payload = [
        (row[0], analyzed_text(row[1]), analyzed_text(row[2] or ""), row[3])
        for row in rows
    ]
    if payload:
        con.executemany(
            "INSERT INTO lexical(lexical,rowid,text,name,path) VALUES('delete',?,?,?,?)",
            payload,
        )


def _build_deps(con: sqlite3.Connection) -> int:
    """Structural edges: a block referencing a symbol defined elsewhere.

    EXPERIMENTAL. Stored but not used by the default selector, because
    matched-budget benchmarks have not shown it improves selection.
    """
    defs: Dict[str, int] = {}
    for r in con.execute("SELECT name, block_id FROM symbols WHERE is_def=1"):
        defs.setdefault(r["name"], r["block_id"])

    edges = set()
    # Definition-only symbols are deliberately the persisted index. Build the
    # optional graph from transient lexical references instead of reintroducing
    # noisy reference rows solely to support this experimental feature.
    import keyword
    from .select import STOPWORDS
    for row in con.execute(
        "SELECT b.id, b.text, f.language FROM blocks b JOIN files f ON f.id=b.file_id"
    ):
        if row["language"] not in ("python", "unknown"):
            continue
        for match in IDENT_RE.finditer(row["text"]):
            name = match.group(0)
            if keyword.iskeyword(name) or name.lower() in STOPWORDS:
                continue
            target = defs.get(name)
            if target is not None and target != row["id"]:
                edges.add((row["id"], target, "symbol_ref"))
    if edges:
        con.executemany(
            "INSERT OR IGNORE INTO deps(src_block_id, dst_block_id, kind) VALUES(?,?,?)",
            list(edges),
        )
    return len(edges)


def _retain_changed_vectors(con: sqlite3.Connection, file_ids: Sequence[int]) -> None:
    """Transaction-local reuse candidates from files about to be replaced.

    SQL storage avoids retaining a Python copy of all affected vectors. Hashes
    locate candidates, but exact text must also match before a vector is reused.
    The table disappears with this connection; it is not part of the artifact.
    """
    con.execute("CREATE TEMP TABLE npk_reusable_vectors(sha256 TEXT, text TEXT COLLATE BINARY, "
                "dim INTEGER, vector BLOB, PRIMARY KEY(sha256,text))")
    for file_id in file_ids:
        con.execute("INSERT OR IGNORE INTO npk_reusable_vectors "
                    "SELECT b.sha256,b.text,e.dim,e.vector FROM blocks b "
                    "JOIN embeddings e ON e.block_id=b.id WHERE b.file_id=?",(file_id,))


def _embed_blocks(con: sqlite3.Connection, only_block_ids: Optional[List[int]] = None,
                  *, expected_manifest: Optional[Dict[str,str]] = None,
                  reuse_vectors: bool = False, stats: Optional[CompileStats] = None) -> Tuple[int, Optional[str], int, Optional[dict]]:
    """Populate the optional embedding index using a LOCAL encoder.

    This is a non-generative sentence encoder run on this machine. It is an
    optional accelerator: deterministic mode never calls it. Existing semantic
    indexes cannot be partially updated with missing or mismatched weights.
    """
    from ..context.embedding import DOCUMENT_CHAR_LIMIT, get_backend
    from .format import require_encoder_match, validate_encoder_identity

    backend = get_backend()
    if not backend.available():
        if expected_manifest is not None:
            raise PackError("local encoder unavailable; semantic update rolled back")
        return 0, None, 0, None
    identity = backend.identity()
    validate_encoder_identity(identity)
    if expected_manifest is not None:
        require_encoder_match(expected_manifest, identity)

    sql = "SELECT b.id,b.text FROM blocks b"
    if reuse_vectors:
        sql = ("SELECT b.id,b.text,r.dim,r.vector FROM blocks b LEFT JOIN npk_reusable_vectors r "
               "ON b.sha256=r.sha256 AND b.text=r.text COLLATE BINARY")
    params: tuple = ()
    if only_block_ids is not None:
        if not only_block_ids:
            return 0, identity["model_id"], 0, identity
        sql += f" WHERE b.id IN ({','.join('?' * len(only_block_ids))})"
        params = tuple(only_block_ids)
    rows = con.execute(sql, params).fetchall()
    if not rows:
        return 0, identity["model_id"], 0, identity

    pending=[]
    reused=[]
    dim=int(expected_manifest["embedding_dim"]) if expected_manifest is not None else 0
    for row in rows:
        if reuse_vectors and row["vector"] is not None:
            blob=row["vector"]
            if row["dim"]!=dim or len(blob)!=dim*4 or any(not math.isfinite(x) for x in unpack_vector(blob,dim)):
                raise PackError("stored encoder vector is malformed; update rolled back")
            reused.append((row["id"],dim,blob))
        else:
            pending.append(row)
    if stats is not None:
        stats.embedding_rows_reused += len(reused)
        stats.encoder_rows_requested += len(pending)
    if not pending:
        con.executemany("INSERT INTO embeddings(block_id,dim,vector) VALUES(?,?,?)",reused)
        return len(rows), identity["model_id"], dim, identity

    texts = [r["text"][:DOCUMENT_CHAR_LIMIT] for r in pending]
    vectors = backend.embed_matrix(texts)
    if vectors is None or len(vectors)!=len(pending) or not vectors[0]:
        raise PackError("encoder returned an incomplete vector batch")

    dim = len(vectors[0])
    if any(len(v)!=dim or any(type(x) not in (int,float) or not math.isfinite(x) for x in v) for v in vectors):
        raise PackError("encoder returned malformed or nonfinite vectors")
    if expected_manifest is not None and dim!=int(expected_manifest["embedding_dim"]):
        raise PackError("encoder vector dimension changed; recompile the artifact")
    con.executemany(
        "INSERT INTO embeddings(block_id, dim, vector) VALUES(?,?,?)"
        " ON CONFLICT(block_id) DO UPDATE SET dim=excluded.dim, vector=excluded.vector",
        reused+[(r["id"], dim, _pack_vector(v)) for r, v in zip(pending, vectors)],
    )
    return len(rows), identity["model_id"], dim, identity


def _set_manifest(con: sqlite3.Connection, values: Dict[str, Any]) -> None:
    con.executemany(
        "INSERT INTO manifest(key, value) VALUES(?,?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        [(k, str(v)) for k, v in values.items()],
    )


def _skipped_json(skipped: Sequence[Dict[str, str]]) -> str:
    return json.dumps(sorted(skipped, key=lambda item: (item["path"], item["reason"])),
                      sort_keys=True, separators=(",", ":"))


def _available_tokens(con: sqlite3.Connection) -> int:
    """Cache the exact neutral estimate at compile/update, including separators."""
    row = con.execute("SELECT count(*), coalesce(sum(length(text)), 0) FROM blocks").fetchone()
    count, chars = row[0], row[1]
    return max(1, (chars + max(0, count - 1) * 2) // 4) if count else 0


def _seal(con: sqlite3.Connection) -> Tuple[int,int]:
    # FTS5 buffers postings until synchronization. Its xSavepoint flushes them
    # within the existing transaction, so the digest sees post-commit index
    # bytes without committing source updates before their integrity metadata.
    # https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_main.c
    con.execute("SAVEPOINT npk_integrity_snapshot")
    counts=refresh_file_digests(con)
    _set_manifest(con, {"root_sha256": compute_root_digest(con,cached=True)})
    con.execute("RELEASE npk_integrity_snapshot")
    return counts


def compile_pack(
    source: str | Path,
    output: str | Path,
    *,
    mode: str = MODE_DETERMINISTIC,
    build_deps: bool = False,
    python_members: bool = False,
    strict: bool = False,
) -> CompileStats:
    """Build privately, then replace the artifact after a successful commit.

    Unindexable files are skipped and listed in ``stats.skipped_sources`` and
    the manifest; ``strict=True`` aborts on them instead.

    Failed compilation leaves an existing output untouched. Publication uses a
    same-filesystem rename; concurrent writers must be serialized by the caller.
    This is failure atomicity, not a guarantee against power loss.
    """
    out = Path(output).absolute()
    if type(build_deps) is not bool:
        raise ValueError("build_deps must be a boolean")
    if type(python_members) is not bool:
        raise ValueError("python_members must be a boolean")
    source_root = Path(source).resolve()
    if not source_root.is_dir():
        raise PackError(f"source root is not a directory: {source_root}")
    if out.is_symlink() or (out.resolve().is_relative_to(source_root)
                            and out.suffix.lower() in TEXT_SUFFIXES):
        raise PackError("output cannot overwrite a source file or symlink")
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    # The generated directory is an immediate child of the checked destination
    # parent. Its dot prefix excludes staging contents from source scanning.
    with tempfile.TemporaryDirectory(prefix=".npk-build-", dir=out.parent) as tmp:
        staging = Path(tmp).resolve()
        if staging.parent != out.parent.resolve():
            raise PackError("staging directory escaped output parent")
        staged_pack = staging / "artifact.npk"
        stats = _compile_unpublished(source_root, staged_pack, mode=mode, build_deps=build_deps,
                                     python_members=python_members, strict=strict)
        if any(Path(str(out) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise PackError("output has active SQLite sidecars; close readers/writers before recompiling")
        os.replace(staged_pack, out)
    stats.seconds = round(time.perf_counter() - started, 4)
    return stats


def _compile_unpublished(
    source: str | Path,
    output: str | Path,
    *,
    mode: str = MODE_DETERMINISTIC,
    build_deps: bool = False,
    python_members: bool = False,
    strict: bool = False,
) -> CompileStats:
    """Create an unpublished artifact owned by compile_pack's staging directory."""
    if mode not in COMPILE_MODES:
        raise PackError(f"unknown mode {mode!r}; expected one of {COMPILE_MODES}")

    started = time.perf_counter()
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)

    skipped: List[Dict[str, str]] = []
    files = scan_source(source, strict=strict, skipped=skipped)
    stats = CompileStats(files_scanned=len(files), mode=mode, dependency_index=build_deps,
                         skipped_sources=skipped)

    con = connect(out, readonly=False, create=True)
    try:
        # executescript does not create a transaction for DDL. Batch schema,
        # tracking and source writes instead of committing each CREATE.
        con.executescript("BEGIN;\n" + SCHEMA)
        install_tracking(con)
        now = _utc()
        for src in files:
            cur = con.execute(
                "INSERT INTO files(path, sha256, size, language, mtime_ns) VALUES(?,?,?,?,?)",
                (src.path, src.sha256, src.size, src.language, src.mtime_ns),
            )
            file_id = cur.lastrowid
            con.execute(
                "INSERT INTO provenance(file_id, source_uri, collected_utc) VALUES(?,?,?)",
                (file_id, src.path, now),
            )
            nb, ns, nr = _write_file_blocks(con, file_id, src, python_members)
            stats.blocks += nb
            stats.symbols += ns
            stats.relations += nr
            stats.files_indexed += 1

        if build_deps:
            stats.deps = _build_deps(con)

        embedding_model = None
        embedding_dim = 0
        encoder_identity = None
        if mode == MODE_SEMANTIC:
            stats.embedded, embedding_model, embedding_dim, encoder_identity = _embed_blocks(con,stats=stats)
            stats.embedding_model = embedding_model
            stats.embedding_status = "indexed" if stats.embedded else "empty" if encoder_identity else "unavailable"

        _set_manifest(con, {
            "format_version": PACK_FORMAT_VERSION,
            "compiler_version": COMPILER_VERSION,
            "mode": mode,
            "created_utc": now,
            "updated_utc": now,
            "source_root": str(Path(source).resolve()),
            "embedding_model": embedding_model or "",
            "embedding_dim": embedding_dim,
            "encoder_identity": json.dumps(encoder_identity,sort_keys=True) if encoder_identity else "",
            "embedding_status": stats.embedding_status,
            "dependency_index": int(build_deps),
            "python_members": int(python_members),
            "file_count": stats.files_indexed,
            "block_count": stats.blocks,
            "available_tokens": _available_tokens(con),
            "skipped_sources": _skipped_json(skipped),
        })
        stats.integrity_files_hashed,stats.integrity_files_reused=_seal(con)
        con.commit()
    finally:
        con.close()

    stats.seconds = round(time.perf_counter() - started, 4)
    return stats


def update_pack(pack: str | Path, source: str | Path, *, build_deps: Optional[bool] = None,
                quick: bool = False, strict: bool = False) -> CompileStats:
    """Incrementally refresh *pack* from *source*.

    Content-hash driven: unchanged files are skipped without being read into
    blocks, and a changed file invalidates only its own blocks.
    When *quick* is True, files whose mtime_ns and size match verified artifact
    records skip SHA-256 recomputation for faster developer iteration.
    """
    started = time.perf_counter()
    if build_deps is not None and type(build_deps) is not bool:
        raise ValueError("build_deps must be a boolean or None")
    if type(quick) is not bool:
        raise ValueError("quick must be a boolean")

    con = connect(pack, readonly=False)
    try:
        # Validate the base and write its replacement in the same transaction.
        # Readers may continue; another writer cannot change our accepted base.
        con.execute("BEGIN IMMEDIATE")
        from .format import read_manifest, require_supported
        manifest = read_manifest(con)
        require_supported(manifest)
        if manifest.get("compiler_version") != COMPILER_VERSION:
            raise PackError("compiler rules changed; recompile the artifact before updating")
        mode = manifest.get("mode", MODE_DETERMINISTIC)
        python_members = manifest.get("python_members", "0") == "1"
        previous_deps = manifest.get("dependency_index", "0") == "1"
        enabled_deps = previous_deps if build_deps is None else build_deps

        existing_rows = con.execute("SELECT id, path, sha256, size, mtime_ns FROM files").fetchall()
        existing = {r["path"]: (r["id"], r["sha256"]) for r in existing_rows}
        known_files = {r["path"]: (r["sha256"], r["size"], r["mtime_ns"]) for r in existing_rows} if quick else None

        skipped: List[Dict[str, str]] = []
        try:
            # An indexed file that stops being indexable aborts the update:
            # its evidence must not disappear silently.
            files = scan_source(source, known_files=known_files, indexed=set(existing),
                                strict=strict, skipped=skipped)
        except TypeError:
            files = scan_source(source)
        by_path = {f.path: f for f in files}

        stats = CompileStats(files_scanned=len(files), mode=mode, dependency_index=enabled_deps,
                             embedding_model=manifest.get("embedding_model") or None,
                             embedding_status=manifest.get("embedding_status","unknown" if mode==MODE_SEMANTIC else "disabled"),
                             skipped_sources=skipped)
        skipped_changed = manifest.get("skipped_sources", _skipped_json([])) != _skipped_json(skipped)

        obsolete_ids = [file_id for path,(file_id,sha) in existing.items()
                        if path not in by_path or by_path[path].sha256!=sha]
        has_replacements = any(path not in existing or existing[path][1]!=src.sha256 for path,src in by_path.items())
        require_clean_cache(con)
        if obsolete_ids or has_replacements or enabled_deps!=previous_deps:
            check_cached_base(con,manifest.get("root_sha256",""))
        reuse_vectors = (mode==MODE_SEMANTIC and int(manifest.get("embedding_dim") or 0)>0
                         and bool(obsolete_ids) and has_replacements)
        if reuse_vectors:
            _retain_changed_vectors(con,obsolete_ids)

        _drop_lexical(con, obsolete_ids)
        changed_block_ids: List[int] = []
        for path, src in by_path.items():
            prev = existing.get(path)
            if prev and prev[1] == src.sha256:
                stats.files_skipped_unchanged += 1
                continue
            if prev:
                _drop_file(con, prev[0], drop_lexical=False)
            cur = con.execute(
                "INSERT INTO files(path, sha256, size, language, mtime_ns) VALUES(?,?,?,?,?)",
                (src.path, src.sha256, src.size, src.language, src.mtime_ns),
            )
            file_id = cur.lastrowid
            con.execute(
                "INSERT INTO provenance(file_id, source_uri, collected_utc) VALUES(?,?,?)",
                (file_id, src.path, _utc()),
            )
            nb, ns, nr = _write_file_blocks(con, file_id, src, python_members)
            stats.blocks += nb
            stats.symbols += ns
            stats.relations += nr
            stats.files_indexed += 1
            changed_block_ids.extend(
                r["id"] for r in con.execute("SELECT id FROM blocks WHERE file_id=?", (file_id,))
            )

        for path, (file_id, _sha) in existing.items():
            if path not in by_path:
                _drop_file(con, file_id, drop_lexical=False)
                stats.files_removed += 1

        changed = stats.files_indexed or stats.files_removed
        policy_changed = enabled_deps != previous_deps
        if not changed and not policy_changed:
            if skipped_changed:
                # Only the report of unindexable files changed; record it.
                check_cached_base(con, manifest.get("root_sha256", ""))
                _set_manifest(con, {"updated_utc": _utc(), "skipped_sources": _skipped_json(skipped)})
                stats.integrity_files_hashed, stats.integrity_files_reused = _seal(con)
                con.commit()
            stats.seconds = round(time.perf_counter() - started, 4)
            return stats

        if changed or policy_changed:
            con.execute("DELETE FROM deps")
            if enabled_deps:
                stats.deps = _build_deps(con)

        if mode == MODE_SEMANTIC and changed_block_ids:
            had_index = int(manifest.get("embedding_dim") or 0)>0
            stats.embedded, model, dim, identity = _embed_blocks(
                con, changed_block_ids if had_index else None,
                expected_manifest=manifest if had_index else None,reuse_vectors=reuse_vectors,stats=stats)
            stats.embedding_model = model
            stats.embedding_status = "indexed" if stats.embedded else "empty" if identity else "unavailable"
            _set_manifest(con, {"embedding_model":model or "", "embedding_dim":dim,
                                "encoder_identity":json.dumps(identity,sort_keys=True) if identity else "",
                                "embedding_status":stats.embedding_status})

        totals = con.execute(
            "SELECT (SELECT COUNT(*) FROM files) f, (SELECT COUNT(*) FROM blocks) b"
        ).fetchone()
        if mode == MODE_SEMANTIC and totals["b"]==0:
            stats.embedding_model = None
            stats.embedding_status = "empty"
            _set_manifest(con,{"embedding_model":"", "embedding_dim":0,"encoder_identity":"",
                               "embedding_status":"empty"})
        _set_manifest(con, {
            "updated_utc": _utc(),
            "file_count": totals["f"],
            "block_count": totals["b"],
            "available_tokens": _available_tokens(con),
            "dependency_index": int(enabled_deps),
            "skipped_sources": _skipped_json(skipped),
        })
        stats.integrity_files_hashed,stats.integrity_files_reused=_seal(con)
        con.commit()
    finally:
        con.close()

    stats.seconds = round(time.perf_counter() - started, 4)
    return stats
