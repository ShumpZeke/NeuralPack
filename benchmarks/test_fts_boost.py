"""Test FTS5 query term boosting syntax."""
import sqlite3


def main():
    con = sqlite3.connect(':memory:')
    con.execute("CREATE VIRTUAL TABLE fts USING fts5(content)")
    con.execute("INSERT INTO fts VALUES(?)", ('retry timeout error',))
    con.execute("INSERT INTO fts VALUES(?)", ('timeout connection error',))

    # Test column weights vs term weights
    r1 = con.execute('SELECT rowid, bm25(fts) FROM fts WHERE fts MATCH ?', ('"retry" OR "timeout"',)).fetchall()
    # In FTS5, does '"retry"^2' or prefix syntax work?
    try:
        r2 = con.execute('SELECT rowid, bm25(fts) FROM fts WHERE fts MATCH ?', ('"retry" * 2 OR "timeout"',)).fetchall()
        print('r2 (* 2):', r2)
    except sqlite3.OperationalError as e:
        print('Syntax * 2 error:', e)

    print('r1:', r1)


if __name__ == '__main__':
    main()
