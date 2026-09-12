"""Tests for probe integrity and strict evaluator failure modes, without a model."""

from dataclasses import asdict, replace
import json
import unittest

from benchmarks.corpus import (
    VARIANTS, Task, common_prefix_bytes, corpus_manifest, expected_response,
    make_tasks, render_prompt,
)
from benchmarks.quality import evaluate, summarize


class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = make_tasks()
        cls.by_id = {task.id: task for task in cls.tasks}

    def test_deterministic_manifest_and_changed_seed(self):
        self.assertEqual(corpus_manifest(self.tasks), corpus_manifest(make_tasks()))
        self.assertNotEqual(corpus_manifest(self.tasks)["sha256"], corpus_manifest(make_tasks(seed=1730))["sha256"])
        self.assertEqual(corpus_manifest(self.tasks)["task_count"], 28)
        self.assertTrue(all(task.metadata["synthetic"] for task in self.tasks))

    def test_complete_unique_categories_and_variants(self):
        self.assertEqual(len(self.tasks), len(self.by_id))
        for category in ("code", "document", "conversation", "mixed"):
            selected = [task for task in self.tasks if task.category == category]
            self.assertEqual([task.metadata["variant"] for task in selected], list(VARIANTS))

    def test_ground_truth_passes_and_wrong_answers_fail(self):
        for task in self.tasks:
            with self.subTest(task=task.id):
                self.assertTrue(evaluate(task, expected_response(task))["passed"])
                self.assertTrue(evaluate(task, " \n" + expected_response(task) + "\n")["passed"])
                self.assertFalse(evaluate(task, "WRONG")["passed"])
                self.assertFalse(evaluate(task, "The answer is " + expected_response(task))["passed"])

    def test_variant_relationships_are_real(self):
        for category in ("code", "document", "conversation", "mixed"):
            with self.subTest(category=category):
                base = self.by_id[f"{category}.base"].context
                repeat = self.by_id[f"{category}.exact_repeat"].context
                prefix = self.by_id[f"{category}.prefix_overlap"].context
                appended = self.by_id[f"{category}.append"].context
                deleted = self.by_id[f"{category}.delete"].context
                edited = self.by_id[f"{category}.local_edit"].context
                reordered = self.by_id[f"{category}.reorder"].context
                self.assertEqual(base, repeat)
                self.assertTrue(appended.startswith(base))
                self.assertGreater(len(appended), len(base))
                self.assertLess(len(deleted), len(base))
                self.assertNotEqual(edited, base)
                self.assertNotEqual(prefix, base)
                self.assertNotEqual(reordered, base)
                # Reorder changes source order without changing the block multiset.
                self.assertCountEqual(reordered.split("\n\n"), base.split("\n\n"))
                self.assertGreater(common_prefix_bytes(base, prefix), len(base.encode("utf-8")) // 2)
                for variant in VARIANTS:
                    task = self.by_id[f"{category}.{variant}"]
                    self.assertEqual(task.metadata["common_prefix_bytes_with_base"], common_prefix_bytes(base, task.context))

    def test_edit_and_delete_stale_answers_are_rejected(self):
        self.assertFalse(evaluate(self.by_id["code.local_edit"], '{"retries":3}')["passed"])
        self.assertFalse(evaluate(self.by_id["code.delete"], '{"retries":3}')["passed"])
        self.assertFalse(evaluate(self.by_id["document.local_edit"], "FORBIDDEN")["passed"])
        self.assertFalse(evaluate(self.by_id["document.delete"], "violet cedar")["passed"])
        self.assertFalse(evaluate(self.by_id["conversation.delete"], "APPROVED")["passed"])
        self.assertFalse(evaluate(self.by_id["mixed.delete"], expected_response(self.by_id["mixed.base"]))["passed"])

    def test_prefix_overlap_and_append_change_answer(self):
        for category in ("document", "conversation"):
            base = self.by_id[f"{category}.base"]
            appended = self.by_id[f"{category}.append"]
            self.assertNotEqual(base.expected, appended.expected)
            self.assertFalse(evaluate(appended, expected_response(base))["passed"])

    def test_padding_is_deterministic_and_retains_probes(self):
        small = make_tasks(padding_blocks=0)
        large = make_tasks(padding_blocks=9)
        self.assertEqual(len(small), len(large))
        # Isolated padding RNGs preserve the facts across length sweeps.
        for short, long in zip(small, large):
            self.assertEqual(short.id, long.id)
            self.assertEqual(short.expected, long.expected)
            self.assertLess(len(short.context), len(long.context))
            self.assertTrue(evaluate(short, expected_response(short))["passed"])
            self.assertTrue(evaluate(long, expected_response(long))["passed"])

    def test_required_quality_dimensions_are_present(self):
        skills = {skill for task in self.tasks for skill in task.metadata["skills"]}
        positions = {position for task in self.tasks for position in task.metadata["instruction_positions"]}
        self.assertTrue({"needle", "negation", "numeric_near_miss", "multi_hop", "tool_constraint", "untrusted_instruction", "format"} <= skills)
        self.assertTrue({"beginning", "middle", "end"} <= positions)
        self.assertTrue(any(len(task.metadata["instruction_positions"]) >= 3 for task in self.tasks))

    def test_render_does_not_append_expected_or_metadata(self):
        task = self.by_id["code.local_edit"]
        self.assertEqual(render_prompt(task), task.context + "\n\nQUESTION\n" + task.query + "\n\nANSWER\n")
        self.assertNotIn('"retries":4', render_prompt(task))
        self.assertEqual(Task(**asdict(task)), task)

    def test_common_prefix_uses_utf8_bytes(self):
        self.assertEqual(common_prefix_bytes("éa", "éb"), 2)
        self.assertEqual(common_prefix_bytes("abc", "abcde"), 3)
        self.assertEqual(common_prefix_bytes("", "a"), 0)

    def test_bad_generation_parameters_fail(self):
        for value in (-1, 10001, 0.1, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                make_tasks(padding_blocks=value)
        with self.assertRaises(TypeError):
            make_tasks(seed="1729")


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.task = Task("test", "mixed", "", "", {"count": 7, "enabled": False}, "json")

    def test_json_key_order_and_whitespace_allowed(self):
        result = evaluate(self.task, '\n{ "enabled": false, "count": 7 }\n')
        self.assertTrue(result["passed"])
        self.assertTrue(result["format_passed"])

    def test_json_strict_failures(self):
        failures = [
            '{"count":7,"count":7,"enabled":false}',
            '{"count":7,"enabled":false,"extra":0}',
            '{"count":7}',
            '{"count":7.0,"enabled":false}',
            '{"count":true,"enabled":false}',
            '{"count":"7","enabled":false}',
            '{"count":7,"enabled":0}',
            '{"count":NaN,"enabled":false}',
            '{"count":Infinity,"enabled":false}',
            '[{"count":7,"enabled":false}]',
            '```json\n{"count":7,"enabled":false}\n```',
            '{"count":7,"enabled":false} thanks',
            '{"count":7,"enabled":false}{"count":7,"enabled":false}',
            '',
        ]
        for response in failures:
            with self.subTest(response=response):
                self.assertFalse(evaluate(self.task, response)["passed"])

    def test_near_miss_is_valid_format_but_wrong_content(self):
        result = evaluate(self.task, '{"count":71,"enabled":false}')
        self.assertFalse(result["passed"])
        self.assertTrue(result["format_passed"])
        self.assertFalse(result["content_passed"])
        numeric = Task("numeric", "document", "", "", {"threshold": "0.072"}, "json")
        for response in ('{"threshold":"0.071"}', '{"threshold":0.072}', '{"threshold":"0.0720"}'):
            self.assertFalse(evaluate(numeric, response)["passed"])

    def test_tool_arguments_and_unlisted_tool_fail(self):
        task = Task("tool", "mixed", "", "", {"tool": "read_ticket", "arguments": {"ticket_id": "T-123"}}, "tool_call")
        for response in (
            '{"tool":"delete_ticket","arguments":{"ticket_id":"T-123"}}',
            '{"tool":"read_ticket","arguments":{"ticket_id":"T-123","force":true}}',
            '{"tool":"read_ticket","arguments":{"ticket_id":"T-123","ticket_id":"T-123"}}',
            '{"tool":"read_ticket","arguments":{"ticket_id":123}}',
            '{"tool":"read_ticket","arguments":{}}',
        ):
            self.assertFalse(evaluate(task, response)["passed"])
        self.assertTrue(evaluate(task, json.dumps(task.expected))["passed"])

    def test_empty_summary_and_error_types(self):
        self.assertIsNone(summarize([])["accuracy"])
        self.assertFalse(evaluate(self.task, None)["passed"])
        with self.assertRaises(ValueError):
            evaluate(replace(self.task, check_kind="contains"), "anything")

    def test_summary_keeps_category_counts(self):
        rows = [evaluate(self.task, expected_response(self.task)), evaluate(self.task, "wrong")]
        result = summarize(rows)
        self.assertEqual(result["accuracy"], 0.5)
        self.assertEqual(result["by_category"]["mixed"], {"total": 2, "passed": 1, "accuracy": 0.5})


if __name__ == "__main__":
    unittest.main()
