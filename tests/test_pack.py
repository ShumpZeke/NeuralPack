"""Lossless, incremental and malformed-package checks, using tiny local fixtures."""

from contextlib import closing, redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from npk.cli import main
from npk.compiler import compile_pack, iter_chunks, update_pack
from npk.format import (
    Limits, PackError, diff_packs, inspect_pack, open_readonly, query_pack,
    read_file, root_digest, safe_relative_path, verify_pack,
)


class PackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="npk-test-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "nested").mkdir()
        self.data = {
            "manual.txt": b"Lumen record names custodian Ibis.\n" * 12,
            "nested/code.py": b"def combine(left, right):\n    return left + right\n",
            "binary.bin": bytes(range(256)) * 2,
            "empty.txt": b"",
        }
        for name, data in self.data.items():
            (self.source / name).write_bytes(data)
        self.pack = self.root / "context.npk"

    def tearDown(self):
        self.temporary.cleanup()

    def build(self, **kwargs):
        return compile_pack(self.source, self.pack, target_size=128, **kwargs)

    def mutate_db(self, sql, args=(), *, repair_root=False):
        connection = sqlite3.connect(self.pack)
        try:
            connection.execute(sql, args)
            if repair_root:
                connection.execute("UPDATE metadata SET value=? WHERE key='root_sha256'", (root_digest(connection),))
            connection.commit()
        finally:
            connection.close()

    def test_lossless_fixed_and_cdc_bytes_and_empty_files(self):
        for algorithm in ("fixed", "cdc"):
            pack = self.root / f"{algorithm}.npk"
            metrics = compile_pack(self.source, pack, chunking=algorithm, target_size=128)
            self.assertEqual(metrics["files_added"], len(self.data))
            self.assertEqual(metrics["source_bytes_read"], sum(map(len, self.data.values())))
            self.assertGreater(metrics["storage_bytes"], 0)
            self.assertTrue(verify_pack(pack)["verified"])
            for name, expected in self.data.items():
                self.assertEqual(read_file(pack, name), expected)

    def test_lexical_query_and_inspect_are_honest(self):
        self.build()
        rows = query_pack(self.pack, "Lumen Ibis")
        self.assertEqual([row["path"] for row in rows], ["manual.txt"])
        info = inspect_pack(self.pack)
        self.assertFalse(info["neural_state"])
        self.assertFalse(info["authenticated_provenance"])
        self.assertIn("lexical", info["representation"])
        self.assertEqual(info["lexical_files"], 3)
        self.assertEqual(query_pack(self.pack, "neverpresent"), [])

    def test_unchanged_update_preserves_index_rows(self):
        self.build()
        with closing(sqlite3.connect(self.pack)) as connection:
            before = connection.execute("SELECT rowid,path,content FROM lexical ORDER BY rowid").fetchall()
        metrics = update_pack(self.pack, self.source)
        with closing(sqlite3.connect(self.pack)) as connection:
            after = connection.execute("SELECT rowid,path,content FROM lexical ORDER BY rowid").fetchall()
        self.assertEqual(before, after)
        self.assertEqual(metrics["files_unchanged"], len(self.data))
        self.assertEqual(metrics["lexical_rows_changed"], 0)
        self.assertEqual(metrics["logical_rows_changed"], 0)
        self.assertEqual(metrics["chunks_new"], 0)
        self.assertEqual(metrics["source_bytes_read"], sum(map(len, self.data.values())))
        self.assertGreater(metrics["chunks_reused_from_previous_pack"], 0)

    def test_update_edit_append_delete_add_and_diff(self):
        self.build(chunking="fixed")
        before = self.root / "before.npk"
        shutil.copyfile(self.pack, before)
        (self.source / "manual.txt").write_bytes(self.data["manual.txt"] + b"New approved record.\n")
        (self.source / "nested/code.py").write_bytes(b"def combine(left, right):\n    return left - right\n")
        (self.source / "binary.bin").unlink()
        (self.source / "new.txt").write_text("Brand new chapter", encoding="utf-8")
        metrics = update_pack(self.pack, self.source)
        self.assertEqual(metrics["files_added"], 1)
        self.assertEqual(metrics["files_modified"], 2)
        self.assertEqual(metrics["files_deleted"], 1)
        self.assertEqual(metrics["files_unchanged"], 1)
        self.assertGreater(metrics["chunks_reused_from_previous_pack"], 0)
        self.assertEqual(read_file(self.pack, "manual.txt"), (self.source / "manual.txt").read_bytes())
        self.assertEqual(query_pack(self.pack, "approved")[0]["path"], "manual.txt")
        diff = diff_packs(before, self.pack)
        self.assertEqual(diff["added"], ["new.txt"])
        self.assertEqual(diff["deleted"], ["binary.bin"])
        self.assertEqual(diff["modified"], ["manual.txt", "nested/code.py"])
        self.assertTrue(verify_pack(self.pack)["verified"])

    def test_text_deletion_counts_actual_lexical_changes(self):
        self.build()
        (self.source / "manual.txt").unlink()
        result = update_pack(self.pack, self.source)
        self.assertEqual(result["lexical_rows_changed"], 1)
        self.assertEqual(query_pack(self.pack, "Lumen"), [])

    def test_repeated_chunks_are_stored_once(self):
        data = b"x" * 1024
        (self.source / "repeat-a.bin").write_bytes(data)
        (self.source / "repeat-b.bin").write_bytes(data)
        metrics = self.build(chunking="fixed")
        self.assertGreater(metrics["chunk_refs_reused"], 1)
        with closing(sqlite3.connect(self.pack)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM chunks WHERE hash=?", (hashlib.sha256(b"x" * 128).hexdigest(),)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_sensitive_and_tooling_names_excluded(self):
        for name in (".env", ".env.local", "credentials.json", "secrets.yaml", "private.pem"):
            (self.source / name).write_text("PRIVATE FIXTURE", encoding="utf-8")
        for name in (".git", ".venv"):
            (self.source / name).mkdir()
            (self.source / name / "hidden.txt").write_text("PRIVATE FIXTURE", encoding="utf-8")
        metrics = self.build()
        self.assertEqual(metrics["source_files_read"], len(self.data))
        self.assertIn(".env", metrics["excluded_paths"])
        self.assertIn(".git/", metrics["excluded_paths"])
        self.assertEqual(query_pack(self.pack, "PRIVATE"), [])

    def test_package_in_source_is_excluded_from_update(self):
        pack = self.source / "inside.npk"
        compile_pack(self.source, pack, target_size=128)
        metrics = update_pack(pack, self.source)
        self.assertEqual(metrics["source_files_read"], len(self.data))
        self.assertIn("inside.npk", metrics["excluded_paths"])

    def test_symlink_input_rejected_if_platform_allows_creation(self):
        link = self.source / "linked.txt"
        try:
            link.symlink_to(self.source / "manual.txt")
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        with self.assertRaises(PackError):
            self.build()

    def test_source_limits_and_no_partial_output(self):
        for limits in (
            replace(Limits(), max_files=1),
            replace(Limits(), max_file_bytes=100),
            replace(Limits(), max_source_bytes=100),
            replace(Limits(), max_chunks=1),
            replace(Limits(), max_container_bytes=100),
        ):
            with self.subTest(limits=limits), self.assertRaises((PackError, sqlite3.Error)):
                self.build(limits=limits)
            self.assertFalse(self.pack.exists())
        self.assertEqual(list(self.root.glob(".npk-build-*")), [])

    def test_existing_output_is_never_overwritten(self):
        self.pack.write_bytes(b"user-owned existing content")
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.pack.read_bytes(), b"user-owned existing content")

    def test_failed_update_keeps_original_pack(self):
        self.build()
        original_root = verify_pack(self.pack)["root_sha256"]
        (self.source / "manual.txt").write_bytes(b"over limit" * 1000)
        with self.assertRaises(PackError):
            update_pack(self.pack, self.source, limits=replace(Limits(), max_file_bytes=600))
        self.assertEqual(verify_pack(self.pack)["root_sha256"], original_root)
        self.assertEqual(read_file(self.pack, "manual.txt"), self.data["manual.txt"])

    def test_truncation_and_non_sqlite_rejected(self):
        self.build()
        raw = self.pack.read_bytes()
        for content in (b"not sqlite", raw[:100], raw[:len(raw)//2]):
            broken = self.root / "broken.npk"
            broken.write_bytes(content)
            with self.subTest(size=len(content)), self.assertRaises(PackError):
                verify_pack(broken)

    def test_schema_trigger_and_view_rejected(self):
        self.build()
        self.mutate_db("CREATE TRIGGER poison AFTER INSERT ON files BEGIN DELETE FROM chunks; END")
        with self.assertRaises(PackError):
            verify_pack(self.pack)
        with self.assertRaises(PackError):
            update_pack(self.pack, self.source)

    def test_chunk_corruption_rejected(self):
        self.build()
        self.mutate_db("UPDATE chunks SET data=zeroblob(size) WHERE hash=(SELECT hash FROM chunks LIMIT 1)")
        with self.assertRaises(PackError):
            verify_pack(self.pack)

    def test_changed_file_map_rejected_even_with_recomputed_root(self):
        self.build()
        self.mutate_db("UPDATE file_chunks SET ordinal=999 WHERE path='nested/code.py' AND ordinal=0", repair_root=True)
        with self.assertRaises(PackError):
            verify_pack(self.pack)

    def test_lexical_tampering_rejected_even_with_recomputed_root(self):
        self.build()
        self.mutate_db("UPDATE lexical SET content='changed facts' WHERE path='manual.txt'", repair_root=True)
        with self.assertRaises(PackError):
            verify_pack(self.pack)

    def test_metadata_version_and_unknown_fields_rejected(self):
        self.build()
        self.mutate_db("UPDATE metadata SET value='999' WHERE key='format_version'")
        with self.assertRaises(PackError):
            verify_pack(self.pack)

    def test_unknown_metadata_and_tampered_provenance_rejected(self):
        self.build()
        self.mutate_db("INSERT INTO metadata VALUES('executable_payload','unused')")
        with self.assertRaises(PackError):
            verify_pack(self.pack)

    def test_stored_path_traversal_rejected_with_recomputed_root(self):
        self.build()
        self.mutate_db("UPDATE files SET path='../escape.txt' WHERE path='empty.txt'", repair_root=True)
        with self.assertRaises(PackError):
            verify_pack(self.pack)

    def test_readonly_reader_cannot_write(self):
        self.build()
        with open_readonly(self.pack) as connection:
            with self.assertRaises(sqlite3.Error):
                connection.execute("DELETE FROM chunks")

    def test_missing_file_and_query_bounds(self):
        self.build()
        with self.assertRaises(KeyError):
            read_file(self.pack, "missing.txt")
        for query in ("", "a" * 4097):
            with self.assertRaises(ValueError):
                query_pack(self.pack, query)
        with self.assertRaises(ValueError):
            query_pack(self.pack, "Lumen", limit=0)
        # The characters cannot become SQL; the package still verifies.
        query_pack(self.pack, "Lumen'; DROP TABLE files; --")
        self.assertTrue(verify_pack(self.pack)["verified"])

    def test_cli_compile_verify_query_and_error(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["legacy-compile", str(self.source), str(self.pack), "--chunking", "fixed", "--target-size", "128"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["operation"], "compile")
        for arguments in (["legacy-verify", str(self.pack)], ["inspect", str(self.pack)], ["stats", str(self.pack)], ["legacy-query", str(self.pack), "Ibis"]):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(arguments), 0)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["legacy-verify", str(self.root / "missing.npk")]), 2)


class ChunkAndPathTests(unittest.TestCase):
    def test_chunks_are_deterministic_lossless_and_bounded(self):
        data = b"".join(hashlib.sha256(str(i).encode()).digest() for i in range(300))
        for method in ("fixed", "cdc"):
            chunks = list(iter_chunks(data, chunking=method, target_size=128))
            self.assertEqual(chunks, list(iter_chunks(data, chunking=method, target_size=128)))
            self.assertEqual(b"".join(chunks), data)
            self.assertTrue(all(0 < len(chunk) <= 256 for chunk in chunks))
        self.assertEqual(list(iter_chunks(b"", target_size=128)), [])

    def test_unsafe_paths_fail(self):
        for path in ("", "../escape", "/absolute", "C:/drive", "C:\\drive", "a/../b", "a//b", "./x", "a\x00b", "a\nb", "CON", "nul.txt", "dir/trailing."):
            with self.subTest(path=path), self.assertRaises(PackError):
                safe_relative_path(path)
        self.assertEqual(safe_relative_path("nested/safe-file.txt"), "nested/safe-file.txt")

    def test_invalid_chunk_settings_and_limits_fail(self):
        for size in (0, 63, 100, 2**21, True):
            with self.subTest(size=size), self.assertRaises(ValueError):
                list(iter_chunks(b"x", target_size=size))
        with self.assertRaises(ValueError):
            list(iter_chunks(b"x", chunking="semantic"))
        with self.assertRaises(ValueError):
            Limits(max_files=0)


if __name__ == "__main__":
    unittest.main()
