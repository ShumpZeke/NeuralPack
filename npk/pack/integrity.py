"""Version-8 integrity: cached file leaves for sealing, full reads for verification.

PROVED UNDER ASSUMPTIONS: if a valid base has current cached leaves and every
file-local write marks its affected files, refreshing those leaves reproduces
full recomputation. Persistent triggers cover the supported logical writes.
This is NOT sublinear verification of arbitrary externally modified bytes.
Verify an untrusted/restored artifact fully before accepting it as an update base.
"""
from __future__ import annotations

import hashlib
import sqlite3

from .format import PackError

LOCAL_TABLES=("files","provenance","blocks","symbols","relations","embeddings","assignments")
GLOBAL_TABLES=("manifest","deps","lexical_data","lexical_idx","lexical_docsize",
               "lexical_config","integrity_files","integrity_dirty")


def tracking_statements():
    """All SQL identifiers here are format constants, not artifact/user strings."""
    statements={}
    for table in LOCAL_TABLES:
        for event in ("insert","update","delete"):
            sides=("OLD","NEW") if event=="update" else ("OLD",) if event=="delete" else ("NEW",)
            body=[]
            for side in sides:
                if table=="files":selection=f"SELECT {side}.id"
                elif table in {"blocks","provenance"}:selection=f"SELECT {side}.file_id"
                else:selection=f"SELECT file_id FROM blocks WHERE id={side}.block_id"
                body.append("INSERT OR IGNORE INTO integrity_dirty(file_id) "+selection+";")
            # Capture the owner before FK cascades can remove its parent row.
            timing="BEFORE" if event=="delete" else "AFTER"
            name=f"npk_track_{table}_{event}"
            statements[name]=f"CREATE TRIGGER {name} {timing} {event.upper()} ON {table} BEGIN {' '.join(body)} END"
    return statements


def install_tracking(con):
    for sql in tracking_statements().values():
        con.execute(sql)


def validate_tracking(con):
    actual=dict(con.execute("SELECT name,sql FROM sqlite_schema WHERE type='trigger'"))
    expected=tracking_statements()
    if actual.keys()!=expected.keys():
        raise PackError("artifact has missing or unsupported integrity triggers; recompile")
    tables={r[0] for r in con.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    if tables!=set(LOCAL_TABLES)|set(GLOBAL_TABLES)|{"lexical"} or con.execute("SELECT 1 FROM sqlite_schema WHERE type='view' LIMIT 1").fetchone():
        raise PackError("artifact contains unsupported tables or views; recompile")
    for name,sql in expected.items():
        if actual.get(name)!=sql:
            raise PackError("artifact integrity tracking schema differs; recompile")


def framed(value):
    if value is None:tag,data=b"n",b""
    elif isinstance(value,bytes):tag,data=b"b",value
    elif isinstance(value,int):tag,data=b"i",str(value).encode("ascii")
    elif isinstance(value,str):tag,data=b"s",value.encode("utf-8")
    else:raise PackError("unexpected value type in artifact")
    return tag+len(data).to_bytes(8,"big")+data


def _feed_rows(digest,rows):
    for row in rows:
        digest.update(framed(len(row))+b"".join(framed(value) for value in row))


def _rows(con,table,where="",params=()):
    count=len(con.execute(f'SELECT * FROM "{table}" LIMIT 0').description)
    order=",".join(str(i+1) for i in range(count))
    return con.execute(f'SELECT * FROM "{table}" {where} ORDER BY {order}',params)


def file_digest(con,file_id):
    digest=hashlib.sha256(b"npk-integrity-v8-file\0")
    for table in LOCAL_TABLES:
        digest.update(framed(table))
        if table=="files":where="WHERE id=?"
        elif table in {"blocks","provenance"}:where="WHERE file_id=?"
        else:where="WHERE block_id IN (SELECT id FROM blocks WHERE file_id=?)"
        _feed_rows(digest,_rows(con,table,where,(file_id,)))
    return digest.digest()


def full_file_digests(con):
    ids=[r[0] for r in con.execute("SELECT id FROM files ORDER BY id")]
    return {file_id:file_digest(con,file_id) for file_id in ids}


def cached_file_digests(con):
    leaves=dict(con.execute("SELECT file_id,digest FROM integrity_files"))
    ids={r[0] for r in con.execute("SELECT id FROM files")}
    if leaves.keys()!=ids or any(not isinstance(value,bytes) or len(value)!=32 for value in leaves.values()):
        raise PackError("artifact has an incomplete or invalid file-integrity cache; recompile")
    return leaves


def root_from_leaves(con,leaves):
    digest=hashlib.sha256(b"npk-integrity-v8-root\0")
    _feed_rows(digest,con.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type,name"))
    for table in GLOBAL_TABLES:
        digest.update(framed(table))
        _feed_rows(digest,_rows(con,table,"WHERE key != 'root_sha256'" if table=="manifest" else ""))
    digest.update(framed("computed_file_leaves"))
    for file_id,value in sorted(leaves.items()):
        digest.update(framed(file_id)+framed(value))
    return digest.hexdigest()


def require_clean_cache(con):
    validate_tracking(con)
    if con.execute("SELECT 1 FROM integrity_dirty LIMIT 1").fetchone() is not None:
        raise PackError("artifact has unsealed file changes; verify or recompile before updating")
    return cached_file_digests(con)


def check_cached_base(con,recorded):
    """Detect altered cache/schema/global storage; not a replacement for verify."""
    leaves=require_clean_cache(con)
    if root_from_leaves(con,leaves)!=recorded:
        raise PackError("artifact cache or global integrity differs; verify or recompile before updating")


def refresh_file_digests(con):
    validate_tracking(con)
    ids={r[0] for r in con.execute("SELECT id FROM files")}
    dirty={r[0] for r in con.execute("SELECT file_id FROM integrity_dirty")}
    cached={r[0] for r in con.execute("SELECT file_id FROM integrity_files")}
    refresh=(dirty & ids)|(ids-cached)
    for file_id in sorted(refresh):
        con.execute("INSERT INTO integrity_files(file_id,digest) VALUES(?,?) ON CONFLICT(file_id) DO UPDATE SET digest=excluded.digest",
                    (file_id,file_digest(con,file_id)))
    # FK cascades normally remove these; explicit pruning also covers initial state.
    con.execute("DELETE FROM integrity_files WHERE file_id NOT IN (SELECT id FROM files)")
    con.execute("DELETE FROM integrity_dirty")
    return len(refresh),len(ids)-len(refresh)


def compute_digest(con,*,cached=False):
    validate_tracking(con)
    if cached:
        leaves=require_clean_cache(con)
    else:
        leaves=full_file_digests(con)
        if leaves!=cached_file_digests(con) or con.execute("SELECT 1 FROM integrity_dirty LIMIT 1").fetchone() is not None:
            raise PackError("artifact file-integrity cache differs from actual contents or has unsealed changes")
    return root_from_leaves(con,leaves)
