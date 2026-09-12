"""A valid artifact is not proof that the intended benchmark corpus was indexed."""
from npk.pack.format import open_pack


def require_compiled_sources(pack,manifest):
    expected={item['path']:item['sha256'] for item in manifest}
    if not expected or len(expected)!=len(manifest):raise ValueError('Empty or duplicate expected source manifest')
    with open_pack(pack) as con:
        actual={row['path']:row['sha256'] for row in con.execute('SELECT path,sha256 FROM files')}
        blocks=con.execute('SELECT COUNT(*) FROM blocks').fetchone()[0]
    if actual!=expected or not blocks:
        raise ValueError('Compiled corpus differs from the expected source manifest')
    return {'files':len(actual),'blocks':blocks}
