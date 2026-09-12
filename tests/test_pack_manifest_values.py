"""A self-consistent hash does not make false counts or policies valid."""
import sqlite3
import pytest
from npk.pack import PackSelector, compile_pack, pack_stats, update_pack, verify
from npk.pack.format import PackError, compute_root_digest
from npk.pack.integrity import refresh_file_digests


@pytest.fixture
def artifact(tmp_path):
    source = tmp_path/'source'; source.mkdir()
    (source/'rules.py').write_text('RETRY_LIMIT = 7\n')
    path = tmp_path/'project.npk'; compile_pack(source, path)
    return source, path


def reseal(path, sql, parameters=()):
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        con.execute(sql, parameters)
        refresh_file_digests(con)
        root = compute_root_digest(con)
        con.execute("UPDATE manifest SET value=? WHERE key='root_sha256'", (root,))


@pytest.mark.parametrize('key,value', [
    ('mode', 'remote_magic'), ('file_count', '-1'), ('block_count', 'many'),
    ('available_tokens', '900000000'), ('embedding_dim', '-3'),
    ('dependency_index', 'yes'), ('python_members', '2'),
    ('file_count', '99'), ('block_count', '99'), ('embedding_status', 'perfect'),
    ('encoder_identity', '{broken'),
])
def test_resealed_invalid_metadata_is_rejected(artifact, key, value):
    _, path = artifact
    reseal(path, 'UPDATE manifest SET value=? WHERE key=?', (value, key))
    result = verify(path)
    assert result['ok'] is False, f'invalid {key} was accepted'
    assert result['errors']


@pytest.mark.parametrize('operation', ['query', 'stats', 'update'])
def test_unknown_mode_cannot_silently_enter_a_product_operation(artifact, operation):
    source, path = artifact
    reseal(path, "UPDATE manifest SET value='remote_magic' WHERE key='mode'")
    before = path.read_bytes()
    rejected = False
    try:
        if operation == 'query': PackSelector(path).select('RETRY_LIMIT')
        elif operation == 'stats': pack_stats(path)
        else: update_pack(path, source)
    except PackError as error:
        rejected = 'mode' in str(error)
    assert rejected, 'unknown mode was silently accepted'
    assert path.read_bytes() == before


def test_resealed_block_token_lie_is_rejected(artifact):
    _, path = artifact
    reseal(path, 'UPDATE blocks SET tokens=1')
    assert not verify(path)['ok']


def test_valid_empty_artifact_is_accepted(tmp_path):
    source = tmp_path/'empty'; source.mkdir(); path = tmp_path/'empty.npk'
    compile_pack(source, path)
    assert verify(path)['ok']
    assert PackSelector(path).select('missing').as_dict()['reduction_pct'] is None


def test_full_acceptance_does_not_load_an_encoder(artifact, monkeypatch):
    def forbidden(): raise AssertionError('full verification tried to load a model')
    monkeypatch.setattr('npk.context.embedding.get_backend', forbidden)
    assert verify(artifact[1])['ok']
