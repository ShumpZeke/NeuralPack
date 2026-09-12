"""Experimental SQLite count cache beside an unchanged provider-neutral .npk.

Records contain source hashes, character cuts and counts, never source text,
model weights, credentials or provider state. Trusted receipts bind bytes;
loading without an external receipt recomputes every region before admission.
This is integrity/reuse research, not authentication of an unknown publisher.
"""
import hashlib
import re
import sqlite3
from pathlib import Path
import tokenizers
from benchmarks.compact_boundary_tokenizer import CompactBoundaryCount,encode_record,decode_record
from npk.pack.format import open_pack,load_blocks,read_manifest,require_supported,PackError
from npk.pack.integrity import require_clean_cache

VERSION='1'; ALGORITHM='delimited-ascii-words-count-v1'
MAX_BYTES=64*1024*1024
SCHEMA='''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE owners(file_id INTEGER PRIMARY KEY,digest BLOB NOT NULL);
CREATE TABLE records(text_sha TEXT PRIMARY KEY,chars INTEGER NOT NULL,prefix_end INTEGER,
                     suffix_start INTEGER,tokens INTEGER,split INTEGER);
CREATE TABLE blocks(block_id INTEGER PRIMARY KEY,file_id INTEGER NOT NULL REFERENCES owners(file_id) ON DELETE CASCADE,
                    text_sha TEXT NOT NULL REFERENCES records(text_sha));
CREATE INDEX blocks_file ON blocks(file_id);
CREATE INDEX blocks_text ON blocks(text_sha);'''
sha=lambda body:hashlib.sha256(body).hexdigest()


def identity(counter):
    return {'version':VERSION,'algorithm':ALGORITHM,'tokenizer_sha256':counter.sha256,
            'tokenizers_version':tokenizers.__version__}


def schema_signature(con):
    return tuple(con.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name'))


def require_schema(con):
    expected=sqlite3.connect(':memory:')
    try:
        expected.executescript(SCHEMA)
        if schema_signature(con)!=schema_signature(expected): raise PackError('Unsupported compiled-count schema')
    finally: expected.close()


def require_identity(con,counter):
    require_schema(con)
    metadata=dict(con.execute('SELECT key,value FROM metadata'))
    if set(metadata)!=set(identity(counter))|{'parent_root'} or any(metadata.get(k)!=v for k,v in identity(counter).items()):
        raise PackError('Compiled-count tokenizer, engine or algorithm differs')
    return metadata


def require_receipt(body,expected_digest):
    if not isinstance(expected_digest,str) or not re.fullmatch('[0-9a-f]{64}',expected_digest) or sha(body)!=expected_digest:
        raise PackError('Compiled-count receipt does not match captured bytes')


def update_index(pack,index,counter,*,create=False,expected_digest=None):
    """Recompile changed-file blocks only; receipt required for existing caches.

    Caller must already accept the .npk base (fully verify external packs).
    Local writers serialize before checking the old receipt and ownership map.
    The entire small SQLite file is hashed; incremental compilation does not
    imply sublinear integrity checking or crash-proof cross-file transactions.
    """
    if not isinstance(counter,CompactBoundaryCount): raise TypeError('An explicit CompactBoundaryCount is required')
    index=Path(index).absolute()
    if create:
        index.touch(exist_ok=False)
    con=sqlite3.connect(index.as_uri()+'?mode=rw',uri=True)
    try:
        con.execute('PRAGMA trusted_schema=OFF'); con.execute('PRAGMA foreign_keys=ON')
        # Keep the writer lock through receipt capture after COMMIT. Otherwise
        # another update can replace the bytes described by these returned stats.
        con.execute('PRAGMA locking_mode=EXCLUSIVE')
        if create: con.executescript('BEGIN IMMEDIATE;\n'+SCHEMA)
        else:
            con.execute('BEGIN IMMEDIATE')
            require_receipt(index.read_bytes(),expected_digest)
            require_identity(con,counter)
        old=dict(con.execute('SELECT file_id,digest FROM owners'))
        with open_pack(pack) as parent:
            manifest=read_manifest(parent); require_supported(manifest); require_clean_cache(parent)
            current=dict(parent.execute('SELECT file_id,digest FROM integrity_files'))
            changed={i for i,digest in current.items() if old.get(i)!=digest}; removed=set(old)-set(current)
            obsolete=set()
            for file_id in sorted(changed|removed):
                obsolete.update(r[0] for r in con.execute('SELECT text_sha FROM blocks WHERE file_id=?',(file_id,)))
                con.execute('DELETE FROM owners WHERE file_id=?',(file_id,))
            compiled=reused=0; block_count=0
            for file_id in sorted(changed):
                con.execute('INSERT INTO owners VALUES(?,?)',(file_id,current[file_id]))
                ids=[r[0] for r in parent.execute('SELECT id FROM blocks WHERE file_id=? ORDER BY ordinal',(file_id,))]
                for block in load_blocks(parent,ids) if ids else []:
                    digest=sha(block.text.encode('utf-8')); block_count+=1
                    if con.execute('SELECT 1 FROM records WHERE text_sha=?',(digest,)).fetchone(): reused+=1
                    else:
                        record=counter._segment(block.text); compiled+=1
                        con.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',(digest,*encode_record(block.text,record)))
                    con.execute('INSERT INTO blocks VALUES(?,?,?)',(block.id,file_id,digest))
            for digest in obsolete:
                con.execute('DELETE FROM records WHERE text_sha=? AND NOT EXISTS(SELECT 1 FROM blocks WHERE text_sha=?)',(digest,digest))
            metadata={**identity(counter),'parent_root':manifest['root_sha256']}
            con.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',metadata.items())
            size=con.execute('PRAGMA page_count').fetchone()[0]*con.execute('PRAGMA page_size').fetchone()[0]
            if size>MAX_BYTES: raise PackError('Compiled-count cache exceeds its 64 MiB limit')
            con.commit()
        # .npk updates may replace a file's numeric ID while keeping its path.
        # These are ownership-row changes, not claims that source files vanished.
        return {'owners_changed':len(changed),'owners_removed':len(removed),'owners_reused':len(current)-len(changed),
                'changed_file_blocks':block_count,'records_compiled':compiled,'changed_block_records_reused':reused,
                'index_bytes':index.stat().st_size,'receipt_sha256':sha(index.read_bytes()),'parent_root':metadata['parent_root']}
    except BaseException:
        con.rollback(); raise
    finally: con.close()


def load_index(pack,index,counter,*,expected_digest=None):
    """Hydrate matching source records, verifying bytes or recomputing all cuts.

    SQLite reads from one captured byte snapshot, closing the hash/open race.
    Recomputed mode checks compilation rather than trusting a self-declared hash.
    A receipt must come from an independently trusted build/update, not from the
    same unknown cache. All checks complete before changing the in-memory cache.
    """
    if not isinstance(counter,CompactBoundaryCount): raise TypeError('An explicit CompactBoundaryCount is required')
    with Path(index).open('rb') as stream: body=stream.read(MAX_BYTES+1)
    if len(body)>MAX_BYTES: raise PackError('Compiled-count cache exceeds its 64 MiB limit')
    if expected_digest is not None: require_receipt(body,expected_digest)
    con=sqlite3.connect(':memory:')
    try:
        con.deserialize(body); con.execute('PRAGMA trusted_schema=OFF')
        metadata=require_identity(con,counter)
        if con.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise PackError('Compiled-count cache is corrupt')
        with open_pack(pack) as parent:
            manifest=read_manifest(parent); require_supported(manifest); require_clean_cache(parent)
            if metadata['parent_root']!=manifest['root_sha256']: raise PackError('Compiled-count cache is stale or belongs to another pack')
            owners=dict(parent.execute('SELECT file_id,digest FROM integrity_files'))
            if dict(con.execute('SELECT file_id,digest FROM owners'))!=owners: raise PackError('Compiled-count owners differ')
            blocks=load_blocks(parent)
        by_hash={}; expected_blocks={}
        for block in blocks:
            digest=sha(block.text.encode('utf-8')); by_hash[digest]=block.text
            expected_blocks[block.id]=(block.file_id,digest)
        actual_blocks={row[0]:row[1:] for row in con.execute('SELECT block_id,file_id,text_sha FROM blocks')}
        if actual_blocks!=expected_blocks: raise PackError('Compiled-count source blocks differ')
        stored={row[0]:row[1:] for row in con.execute('SELECT * FROM records')}
        if stored.keys()!=by_hash.keys(): raise PackError('Compiled-count source records differ')
        pending=[]; verified=0
        for digest,text in by_hash.items():
            record=decode_record(text,stored[digest])
            if expected_digest is None:
                actual=counter._segment(text); verified+=1
                if encode_record(text,actual)!=stored[digest]: raise PackError('Compiled-count record differs from local compilation')
            pending.append((text,record))
        with counter._lock:
            for text,record in pending: counter._admit(text,record)
        return {'mode':'receipt_verified' if expected_digest is not None else 'recompiled_verification',
                'records_loaded':len(pending),'records_recompiled_for_verification':verified,
                'receipt_sha256':sha(body),'parent_root':metadata['parent_root'],'prepared_info':counter.prepared_info()}
    except sqlite3.DatabaseError:
        raise PackError('Invalid compiled-count SQLite cache') from None
    finally: con.close()
