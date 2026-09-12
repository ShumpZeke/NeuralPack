"""Single-threaded research adapter for retaining identical indexed blocks.

NOT a product API: temporarily patches compiler helpers inside this process.
Only deterministic, graph-free artifacts are admitted. Existing transactions,
source scanning and integrity sealing remain in the ordinary updater.
"""
from collections import defaultdict,deque
import importlib
from unittest.mock import patch
import uuid
from npk.pack.format import open_pack,read_manifest,PackError


def update_reused(pack,source):
    compiler=importlib.import_module('npk.pack.compile')
    with open_pack(pack) as con:
        manifest=read_manifest(con)
        if manifest['mode']!='deterministic' or manifest['dependency_index']!='0':
            raise PackError('Research block reuse only admits deterministic graph-free artifacts')
    original_scan=compiler.scan_source;original_drop=compiler._drop_file;original_write=compiler._write_file_blocks
    original_drop_lexical=getattr(compiler,'_drop_lexical',None)
    files={};pending={};metrics={'reused_blocks':0,'new_blocks':0}
    def scan(root):
        scanned=original_scan(root);files.update((s.path,s) for s in scanned);return scanned
    def drop_lexical(con,file_ids):
        # Files being replaced will be reused; only drop files removed from source.
        if original_drop_lexical is None or not file_ids:return
        removed=[fid for fid in file_ids if con.execute('SELECT path FROM files WHERE id=?',(fid,)).fetchone()['path'] not in files]
        if removed:original_drop_lexical(con,removed)
    def drop(con,file_id,*args,**kwargs):
        row=con.execute('SELECT path FROM files WHERE id=?',(file_id,)).fetchone();path=row['path']
        if path not in files:return original_drop(con,file_id,*args,**kwargs)
        # Keep the old file and its FK children alive until identical blocks
        # have moved to the new owner. This name exists only inside the write
        # transaction and is removed before sealing/commit.
        temporary='__npk_research_pending_'+uuid.uuid4().hex
        con.execute('UPDATE files SET path=? WHERE id=?',(temporary,file_id));pending[path]=file_id
    def write(con,file_id,src,python_members=False):
        # Check the admitted mode again inside the actual write transaction.
        now=read_manifest(con)
        if now['mode']!='deterministic' or now['dependency_index']!='0':
            raise PackError('Research block reuse configuration changed')
        if src.path not in pending:
            added,symbols,relations=original_write(con,file_id,src,python_members)
            metrics['new_blocks']+=added
            return added,symbols,relations
        old_id=pending.pop(src.path)
        old=defaultdict(deque)
        for r in con.execute('SELECT id,kind,name,text,path FROM blocks WHERE file_id=? ORDER BY ordinal,id',(old_id,)):
            old[(r['kind'],r['name'],r['text'])].append(r['id'])
        blocks=compiler.split_source(src.text,src.language,python_members=python_members)
        fresh=[];reused_symbols=0;reused_relations=0;reused=0
        for b in blocks:
            candidates=old.get((b.kind,b.name,b.text))
            if not candidates:fresh.append(b);continue
            block_id=candidates.popleft()
            con.execute('UPDATE blocks SET file_id=?,ordinal=?,start_line=?,end_line=?,tokens=? WHERE id=?',
                        (file_id,b.ordinal,b.start_line,b.end_line,compiler.estimate_tokens(b.text),block_id))
            # Format v8 uses external-content FTS5. A reused block may have
            # moved with a renamed file, so delete the old normalized posting
            # before replacing it while preserving the stable block identity.
            old_path = con.execute('SELECT path FROM blocks WHERE id=?',(block_id,)).fetchone()[0]
            con.execute(
                "INSERT INTO lexical(lexical,rowid,text,name,path) VALUES('delete',?,?,?,?)",
                (block_id, compiler.analyzed_text(b.text),
                 compiler.analyzed_text(b.name or ''), old_path),
            )
            con.execute(
                'INSERT INTO lexical(rowid,text,name,path) VALUES(?,?,?,?)',
                (block_id, compiler.analyzed_text(b.text),
                 compiler.analyzed_text(b.name or ''),
                 compiler.analyzed_text(src.path.rsplit('.',1)[0])),
            )
            reused+=1;reused_symbols+=len(b.symbols)
            reused_relations+=con.execute(
                'SELECT COUNT(*) FROM relations WHERE block_id=?',(block_id,)
            ).fetchone()[0]
        # Remaining old blocks are removed through the existing lexical/FK
        # cleanup path. Reused rows keep their lexical and symbol indexes.
        original_drop(con,old_id)
        def only_fresh(text,language,*,python_members=False):
            if text!=src.text or language!=src.language:raise ValueError('Unexpected nested source split')
            return fresh
        with patch.object(compiler,'split_source',only_fresh):
            added,symbols,relations=original_write(con,file_id,src,python_members)
        metrics['reused_blocks']+=reused;metrics['new_blocks']+=added
        return (added+reused, symbols+reused_symbols,
                relations+reused_relations)
    patches=[patch.object(compiler,'scan_source',scan),patch.object(compiler,'_drop_file',drop),patch.object(compiler,'_write_file_blocks',write)]
    if original_drop_lexical is not None:
        patches.append(patch.object(compiler,'_drop_lexical',drop_lexical))
    from contextlib import ExitStack
    with ExitStack() as stack:
        for p in patches:stack.enter_context(p)
        stats=compiler.update_pack(pack,source)
    if pending:raise RuntimeError('Research updater retained an unfinished file')
    return stats,metrics
