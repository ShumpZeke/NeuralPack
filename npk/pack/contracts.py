"""Stored-value type checks derived from the compiler's own schema.

SQLite column affinity permits BLOB values in TEXT columns. Integrity hashes
alone cannot certify those values as usable by the runtime. These checks run
during full artifact acceptance, not on each query or cached update.
"""
from contextlib import closing
from functools import lru_cache
import json
import re
import sqlite3


@lru_cache(maxsize=1)
def _value_queries():
    from .format import SCHEMA
    from .integrity import LOCAL_TABLES
    tables=(*LOCAL_TABLES,'manifest','deps','integrity_files','integrity_dirty')
    statements=[]
    # Names and types come from trusted compiler code, never artifact SQL.
    with closing(sqlite3.connect(':memory:')) as expected:
        expected.executescript(SCHEMA)
        for table in tables:
            conditions=[]
            for _,name,declared,notnull,_,primary in expected.execute(f'PRAGMA table_info("{table}")'):
                kind={'TEXT':'text','INTEGER':'integer','BLOB':'blob'}[declared]
                allowed=f"'{kind}'"+("" if notnull or primary else ",'null'")
                conditions.append(f'typeof("{name}") NOT IN ({allowed})')
            statements.append((table,f'SELECT 1 FROM "{table}" WHERE '+ ' OR '.join(conditions)+' LIMIT 1'))
    statements.append(('lexical',"SELECT 1 FROM lexical WHERE typeof(rowid)!='integer' LIMIT 1"))
    return tuple(statements)


def require_stored_types(con):
    from .format import PackError
    for table,query in _value_queries():
        if con.execute(query).fetchone() is not None:
            raise PackError(f'unsupported stored value type in artifact table {table}')


def require_manifest_values(manifest):
    """Constant-size policy/number validation shared by all product readers.

    Counts are claims until full verification compares them to stored content.
    Lexical use does not require a usable optional encoder identity.
    """
    from .format import COMPILE_MODES, PackError
    if manifest.get('mode') not in COMPILE_MODES:
        raise PackError('unsupported artifact mode; recompile')
    for key in ('file_count', 'block_count', 'available_tokens', 'embedding_dim'):
        value = manifest.get(key, '')
        if (not re.fullmatch(r'(0|[1-9][0-9]{0,18})', value)
                or int(value) > 2**63-1):
            raise PackError(f'invalid artifact {key}; expected a nonnegative integer')
    for key in ('dependency_index', 'python_members'):
        if manifest.get(key) not in ('0', '1'):
            raise PackError(f'unsupported artifact {key} policy; recompile')
    if manifest.get('embedding_status') not in ('disabled', 'unavailable', 'empty', 'indexed'):
        raise PackError('unsupported artifact embedding_status; recompile')


def require_content_metadata(con, manifest, counts):
    """Full acceptance checks known count/policy/encoder invariants, no model I/O."""
    from .format import PackError, validate_encoder_identity
    for key, actual in (('file_count', counts['files']), ('block_count', counts['blocks'])):
        if int(manifest[key]) != actual:
            raise PackError(f'artifact {key} does not match stored content')
    if manifest['dependency_index'] == '0' and counts['deps']:
        raise PackError('disabled dependency index contains edges')
    lexical = con.execute('SELECT COUNT(*) FROM lexical').fetchone()[0]
    if lexical != counts['blocks']:
        raise PackError('lexical index does not contain exactly one row per block')
    lexical_columns = [row[1] for row in con.execute('PRAGMA table_info(lexical)')]
    if lexical_columns != ['text', 'name', 'path']:
        raise PackError('artifact lexical schema is not the supported external-content index')
    lexical_sql = con.execute(
        "SELECT sql FROM sqlite_schema WHERE type='table' AND name='lexical'"
    ).fetchone()[0]
    if "content='blocks'" not in lexical_sql or "content_rowid='id'" not in lexical_sql:
        raise PackError('artifact lexical index is not bound to block content')
    if con.execute(
        'SELECT 1 FROM lexical l LEFT JOIN blocks b ON b.id=l.rowid '
        'WHERE b.id IS NULL LIMIT 1'
    ).fetchone() is not None:
        raise PackError('lexical index contains an orphan rowid')
    if con.execute(
        'SELECT 1 FROM blocks b LEFT JOIN lexical l ON l.rowid=b.id '
        'WHERE l.rowid IS NULL LIMIT 1'
    ).fetchone() is not None:
        raise PackError('lexical index is missing a block rowid')
    from .search import analyzed_text
    for row in con.execute(
        'SELECT b.path,f.path AS source_path FROM blocks b JOIN files f ON f.id=b.file_id'
    ):
        expected_path = analyzed_text(row['source_path'].rsplit('.', 1)[0])
        if row['path'] != expected_path:
            raise PackError('block lexical path metadata disagrees with its source file')
    if con.execute("SELECT 1 FROM relations WHERE kind!='raises' LIMIT 1").fetchone() is not None:
        raise PackError('artifact contains an unsupported structural relation')
    dim = int(manifest['embedding_dim'])
    status = manifest['embedding_status']
    model = manifest.get('embedding_model', '')
    try:
        identity = json.loads(manifest.get('encoder_identity') or 'null')
    except (ValueError, TypeError) as error:
        raise PackError('malformed artifact encoder identity') from error
    if identity is not None:
        validate_encoder_identity(identity)
        if identity['model_id'] != model:
            raise PackError('artifact encoder identity and model disagree')
    elif model:
        raise PackError('artifact model is missing its encoder identity')
    if manifest['mode'] == 'deterministic':
        if status != 'disabled' or dim or counts['embeddings'] or model or identity:
            raise PackError('deterministic artifact has incompatible embedding metadata')
    elif status == 'indexed':
        if not dim or not identity or counts['embeddings'] != counts['blocks'] or not counts['blocks']:
            raise PackError('indexed artifact has incomplete embedding metadata or rows')
    elif status in ('empty', 'unavailable'):
        if dim or counts['embeddings'] or (status == 'empty' and counts['blocks']):
            raise PackError('unindexed artifact has incompatible embedding metadata')
        if status == 'unavailable' and (model or identity):
            raise PackError('unavailable encoder has incompatible identity metadata')
    else:
        raise PackError('semantic artifact cannot disable its embedding state')
    if con.execute('SELECT 1 FROM embeddings WHERE dim!=? OR length(vector)!=4*dim LIMIT 1',
                   (dim,)).fetchone() is not None:
        raise PackError('stored embedding dimensions disagree with manifest')
