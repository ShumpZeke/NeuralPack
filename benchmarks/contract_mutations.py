"""Mutation tripwires run in disposable snapshots; never reset the worktree.

A mutant counts as killed only when pytest reports an assertion failure in the
specified test. Import errors, timeouts and collection failures are harness errors.
"""
from __future__ import annotations

import ast
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def mutate_function(source, name, statement):
    tree = ast.parse(source)
    functions = [node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(functions) != 1:
        raise ValueError(f"expected unique function: {name}")
    node = functions[0]
    first = node.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        first = node.body[1]
    lines = source.splitlines(keepends=True)
    lines.insert(first.lineno - 1, " " * first.col_offset + statement + "\n")
    return "".join(lines)


MUTANTS = [
    ("query_cache_serves_stale_root", "npk/pack/select.py", None, None,
     "tests/test_query_caching_and_ordering.py::test_update_invalidates_query_cache"),
    ("canonical_ordering_unsorted", "npk/pack/select.py", None, None,
     "tests/test_query_caching_and_ordering.py::test_selection_context_text_supports_canonical_ordering"),
    ("quick_update_reads_untouched_files", "npk/pack/compile.py", None, None,
     "tests/test_quick_update_fingerprint.py::test_quick_update_skips_reading_untouched_files"),
    ("write_file_blocks_drops_lexical_batch", "npk/pack/compile.py", None, None,
     "tests/test_batched_file_inserts.py::test_batched_insertion_preserves_all_blocks_lexical_and_symbols"),
    ("symbols_include_language_keywords", "npk/pack/compile.py", None, None,
     "tests/test_symbol_index_cleanliness.py::test_keywords_and_stopwords_are_not_indexed_as_references"),
    ("symbols_prose_references_unfiltered", "npk/pack/compile.py", None, None,
     "tests/test_symbol_index_cleanliness.py::test_prose_files_do_not_emit_bare_word_symbol_references"),
    ("trusted_schema_allowed", "npk/pack/format.py", None, None,
     "tests/test_runtime_hardening.py::test_connect_enforces_query_only_and_trusted_schema_defense"),
    ("query_only_disabled", "npk/pack/format.py", None, None,
     "tests/test_runtime_hardening.py::test_connect_enforces_query_only_and_trusted_schema_defense"),
    ("available_tokens_zeroed", "npk/pack/compile.py", "_available_tokens",
     "return 0",
     "tests/test_runtime_hardening.py::test_available_tokens_sql_aggregation_matches_python_loop_exactly"),
    ("selector_context_manager_unclosed", "npk/pack/select.py", "__exit__",
     "return None",
     "tests/test_runtime_hardening.py::test_pack_selector_context_manager_reuses_connection_and_releases_locks"),
    ("update_audit_quadratic_cross_join", "benchmarks/update_batch_eval.py", "logical_digest",
     "con.execute('SELECT count(*) FROM blocks b CROSS JOIN lexical l').fetchone()",
     "tests/test_update_batch_audit.py::test_logical_audit_has_a_linear_scale_work_budget"),
    ("batch_update_keeps_stale_postings", "npk/pack/compile.py", "_drop_lexical", "return None",
     "tests/test_update_batch.py::test_mixed_updates_keep_index_identity[1]"),
    ("source_view_discards_omission_metadata", "benchmarks/source_views.py", "omit_docstrings", "return View((), (), '')",
     "tests/test_source_views.py::test_partial_block_has_exact_surviving_spans_and_marked_omissions"),
    ("source_view_ignores_budget", "benchmarks/source_views.py", "pack_views", "budget = 1000000",
     "tests/test_source_views.py::test_exact_budget_includes_markers_and_all_separators"),
    ("source_view_loses_query", "benchmarks/source_views.py", "pack_views", "query = ''",
     "tests/test_source_views.py::test_exact_budget_includes_markers_and_all_separators"),
    ("record_usage_type_coercion", "benchmarks/answer_records.py", "json_identical", "return left == right",
     "tests/test_answer_record_provenance.py::test_reported_usage_cannot_coerce_raw_json_types"),
    ("record_replay_type_coercion", "benchmarks/answer_records.py", "json_identical", "return left == right",
     "tests/test_answer_record_provenance.py::test_replay_identity_preserves_json_types"),
    ("recovery_plan_type_coercion", "benchmarks/answer_records.py", "json_identical", "return left == right",
     "tests/test_answer_recovery.py::test_recovery_attacks_cannot_change_the_frozen_experiment[answer_type]"),
    ("complete_program_json_type_coercion", "benchmarks/complete_program_controls.py", "same_json", "return left == right",
     "tests/test_complete_program_controls.py::test_complete_study_rejects_tampering_before_execution[boolean_answer_as_number]"),
    ("complete_program_validation_bypass", "benchmarks/complete_program_controls.py", "validate", "return {}, {}, {}",
     "tests/test_complete_program_controls.py::test_complete_study_rejects_tampering_before_execution[query]"),
    ("complete_program_invented_oracle", "benchmarks/complete_program_controls.py", "run_program", "return None, '0'*64",
     "tests/test_complete_program_controls.py::test_complete_oracle_refuses_missing_global_instead_of_creating_an_answer"),
    ("reference_scope_shadowing_ignored", "benchmarks/reference_evidence.py", "referenced_globals",
     "return {s.get_name() for s in table.get_symbols() if s.is_referenced()}",
     "tests/test_reference_evidence.py::test_module_bindings_respect_local_shadowing_and_import_aliases"),
    ("reference_overload_last_pick", "benchmarks/reference_evidence.py", "", "",
     "tests/test_reference_evidence.py::test_overload_stubs_require_an_explicit_definition_line"),
    ("reference_unicode_physical_lines", "benchmarks/reference_evidence.py", "", "",
     "tests/test_reference_evidence.py::test_reference_source_preserves_physical_lines_and_unicode"),
    ("reference_empty_seed_success", "benchmarks/reference_evidence.py", "source_segments", "return [], []",
     "tests/test_reference_evidence.py::test_reference_empty_or_failed_seed_is_not_a_success"),
    ("reference_budget_bypass", "benchmarks/reference_evidence.py", "bounded_reference", "budget = 10**12",
     "tests/test_reference_evidence.py::test_reference_budget_counts_headers_and_the_whole_join"),
    ("reference_evidence_validation_bypass", "benchmarks/reference_evidence.py", "validate_reference", "return {}",
     "tests/test_reference_evidence.py::test_reference_validator_rejects_changed_evidence_or_experiment"),
    ("recovery_unknown_parent_attempt", "benchmarks/answer_recovery.py", "require_parent_ledger", "return None",
     "tests/test_answer_recovery.py::test_recovery_refuses_uncertain_or_unapproved_parent_outcomes[STARTED]"),
    ("recovery_arbitrary_failure_retry", "benchmarks/answer_recovery.py", "retry_eligible",
     "return result.get('transport_success') is False",
     "tests/test_answer_recovery.py::test_recovery_refuses_uncertain_or_unapproved_parent_outcomes[hidden_answer]"),
    ("recovery_lineage_bypass", "benchmarks/answer_recovery.py", "validate_recovery", "return {}",
     "tests/test_answer_recovery.py::test_recovery_attacks_cannot_change_the_frozen_experiment"),
    ("recovery_context_identity_bypass", "benchmarks/answer_recovery.py", "require_payload", "return None",
     "tests/test_answer_recovery.py::test_recovery_attacks_cannot_change_the_frozen_experiment[context]"),
    ("recovery_unbounded_execution", "benchmarks/answer_recovery.py", "require_bounded_execution", "return None",
     "tests/test_answer_recovery.py::test_recovery_execution_bounds_reject_unbounded_calls"),
    ("answer_missing_transport_complete", "benchmarks/library_answer_report.py", "", "",
     "tests/test_answer_recovery.py::test_report_distinguishes_terminal_attempts_from_missing_answers"),
    ("lazy_parent_identity_bypass", "benchmarks/lazy_count_index.py", "require_parent", "return None",
     "tests/test_lazy_count_index.py::test_lazy_selector_rejects_stale_cache_after_source_update"),
    ("lazy_hidden_source_compilation", "benchmarks/lazy_count_index.py", "_hydrate", "self.prepare(parts)",
     "tests/test_lazy_count_index.py::test_lazy_load_hydrates_only_requested_records_without_compilation"),
    ("lazy_hidden_all_record_scan", "benchmarks/lazy_count_index.py", "_hydrate",
     "self._index.execute('SELECT * FROM records').fetchall()",
     "tests/test_lazy_count_index.py::test_lazy_load_hydrates_only_requested_records_without_compilation"),
    ("lazy_same_length_record_alias", "benchmarks/lazy_count_index.py", "_lookup",
     "return self._index.execute('SELECT chars,prefix_end,suffix_start,tokens,split FROM records WHERE chars=? LIMIT 1',(len(text),)).fetchone()",
     "tests/test_lazy_count_index.py::test_lazy_source_hash_cannot_alias_same_length_text"),
    ("lazy_unknown_engine_reuse", "benchmarks/lazy_count_index.py", "count_parts", "self.lazy_enabled = True",
     "tests/test_lazy_count_index.py::test_lazy_unknown_engine_never_reuses_regions"),
    ("lazy_partial_hydration_on_error", "benchmarks/lazy_count_index.py", "_hydrate",
     "if parts: self._admit(parts[0],decode_record(parts[0],self._lookup(parts[0])))",
     "tests/test_lazy_count_index.py::test_lazy_record_error_does_not_partially_hydrate"),
    ("lean_metadata_guard_bypass", "benchmarks/lean_boundary_tokenizer.py", "_allows_boundaries", "return True",
     "tests/test_lean_boundary_tokenizer.py::test_lean_preserves_every_loaded_metadata_guard"),
    ("lean_hidden_vocabulary_roundtrip", "benchmarks/lean_boundary_tokenizer.py", "__init__",
     "FastCount.__init__(self, path, cache_bytes=cache_bytes); self._backend.to_str()",
     "tests/test_lean_boundary_tokenizer.py::test_lean_initializer_avoids_whole_vocab_roundtrip"),
    ("delimited_unicode_neighbor_guard_bypassed", "benchmarks/delimited_boundary_tokenizer.py", "safe_words",
     "return list(re.finditer('[A-Za-z]+', text))",
     "tests/test_delimited_boundary_tokenizer.py::test_adjacent_unicode_cannot_implicitly_widen_word_barrier_scope"),
    ("compact_independent_block_summing", "benchmarks/compact_boundary_tokenizer.py", "count_parts",
     "return sum(self.count(p) for p in parts)",
     "tests/test_compiled_count_index.py::test_compact_count_records_preserve_whole_join_and_memory_limit"),
    ("count_cache_receipt_bypassed", "benchmarks/compiled_count_index.py", "require_receipt", "return None",
     "tests/test_compiled_count_index.py::test_changed_bytes_cannot_reuse_a_trusted_old_receipt"),
    ("count_cache_self_declared_trust", "benchmarks/compiled_count_index.py", "load_index",
     "expected_digest = sha(Path(index).read_bytes())",
     "tests/test_compiled_count_index.py::test_load_without_receipt_recomputes_instead_of_trusting_self_declared_data"),
    ("count_cache_receipt_capture_race", "benchmarks/compiled_count_index.py", None, "",
     "tests/test_compiled_count_index.py::test_receipt_is_captured_before_competing_writer_can_change_committed_bytes"),
    ("count_cache_hidden_full_recompilation", "benchmarks/compiled_count_index.py", "update_index",
     "with open_pack(pack) as extra: [counter._segment(b.text) for b in load_blocks(extra)]",
     "tests/test_compiled_count_index.py::test_real_incremental_update_reuses_unchanged_blocks_and_matches_rebuild"),
    ("ascii_barriers_cut_inside_words", "benchmarks/ascii_boundary_tokenizer.py", "_segment",
     "from benchmarks.boundary_tokenizer import BoundaryCount; return BoundaryCount._segment(self, text)",
     "tests/test_ascii_boundary_tokenizer.py::test_ascii_word_barriers_preserve_full_ids_and_counts"),
    ("digit_barrier_widened_to_letters", "benchmarks/digit_boundary_tokenizer.py", "_segment",
     "return super()._segment(text)",
     "tests/test_digit_boundary_tokenizer.py::test_digit_boundaries_preserve_actual_joined_token_ids"),
    ("verified_zero_token_acceptance", "benchmarks/verified_boundary_tokenizer.py", "count_parts",
     "return 0",
     "tests/test_boundary_tokenizer.py::test_verified_counter_cannot_discard_all_nonempty_input"),
    ("verified_partition_gate_bypass", "benchmarks/verified_boundary_tokenizer.py", None, "",
     "tests/test_boundary_tokenizer.py::test_wrong_proposed_partition_triggers_upstream_fallback"),
    ("verified_compilation_on_query", "benchmarks/verified_boundary_tokenizer.py", "count_parts",
     "self.prepare(parts)",
     "tests/test_boundary_tokenizer.py::test_verified_counter_never_compiles_missing_query_parts"),
    ("boundary_naive_block_addition", "benchmarks/boundary_tokenizer.py", "count_parts",
     "return sum(self.count(p) for p in parts)",
     "tests/test_boundary_tokenizer.py::test_prepared_interiors_preserve_join_ids_and_counts"),
    ("boundary_compilation_on_query", "benchmarks/boundary_tokenizer.py", "count_parts",
     "self.prepare(parts)",
     "tests/test_boundary_tokenizer.py::test_unprepared_or_evicted_parts_use_full_encoder_without_compilation"),
    ("encoder_default_revision_unpinned", "npk/context/embedding.py", "_load", "self._revision = None",
     "tests/test_embedding_identity.py::test_default_revision_is_passed_to_both_loaders"),
    ("encoder_offline_flag_bypass", "npk/context/embedding.py", None, "",
     "tests/test_embedding_identity.py::test_runtime_loaders_are_explicitly_offline[0]"),
    ("length_normalization_ignored", "benchmarks/length_normalization.py", "rank",
     "length_normalization = 0.75",
     "tests/test_length_normalization.py::test_independent_parameter_bindings_and_parallel_isolation"),
    ("length_normalization_global_leak", "benchmarks/length_normalization.py", "rank",
     "scorer.candidates.__func__.__globals__['B'] = length_normalization; return scorer.candidates(plan, limit)",
     "tests/test_length_normalization.py::test_independent_parameter_bindings_and_parallel_isolation"),
    ("structural_intent_guard_bypassed", "benchmarks/structural_intent.py", "filter_relations",
     "return IntentDecision(tuple(relations), (), ())",
     "tests/test_structural_intent.py::test_conservative_guard_abstains_on_ambiguous_surface"),
    ("structural_intent_all_disabled", "benchmarks/structural_intent.py", "filter_relations",
     "return IntentDecision((), tuple(relations), ())",
     "tests/test_structural_intent.py::test_explicit_positive_relation_survives"),
    ("packing_rejection_counted_as_admission", "benchmarks/packing_challengers.py", "_was_admitted", "return True",
     "tests/test_packing_challengers.py::test_grouping_reacts_only_to_real_admissions[leaf]"),
    ("packing_admission_feedback_ignored", "benchmarks/packing_challengers.py", "_was_admitted", "return False",
     "tests/test_packing_challengers.py::test_grouping_reacts_only_to_real_admissions[file]"),
    ("body_fusion_channel_ignored", "benchmarks/packing_challengers.py", "fuse_body", "return list(strong)",
     "tests/test_packing_challengers.py::test_fusion_uses_both_channels_and_preserves_candidate_union"),
    ("answer_plan_locale_corruption", "benchmarks/prospective_eval.py", "_read_json",
     "return json.loads(path.read_text())",
     "tests/test_prospective_eval.py::test_utf8_plan_survives_a_windows_locale_default"),
    ("diagnostic_null_response_omission", "benchmarks/library_failure_analysis.py", "summarize",
     "rows = [row for row in rows if row.get('parsed') is not None]",
     "tests/test_library_failure_analysis.py::test_null_and_malformed_answers_are_responses_not_missing_transports"),
    ("provenance_identity_erased", "benchmarks/provenance_renderer.py", "render_item", "return item.text",
     "tests/test_provenance_renderer.py::test_identical_bodies_from_different_scopes_keep_distinct_identity"),
    ("provenance_header_count_ignored", "benchmarks/provenance_renderer.py", "_count",
     "return self.tokenizer.count('\\n\\n'.join(e.text for e in evidence))",
     "tests/test_provenance_renderer.py::test_public_counts_include_the_rendered_identity_for_every_cap[True]"),
    ("provenance_consumer_text_erased", "benchmarks/provenance_renderer.py", "context_text",
     "return separator.join(e.text for e in self.evidence)",
     "tests/test_provenance_renderer.py::test_public_counts_include_the_rendered_identity_for_every_cap[False]"),
    ("batch_prefetch_wrong_prefix", "benchmarks/batch_tokenizer.py", "_count_uncached",
     "if self._prefetched: return next(iter(self._prefetched.values()))",
     "tests/test_batch_tokenizer.py::test_prefetch_counts_whole_strings_and_never_reuses_a_different_prefix"),
    ("batch_candidate_order_changed", "benchmarks/batch_tokenizer.py", "_batch_order",
     "ordered_ids = list(reversed(ordered_ids))",
     "tests/test_batch_tokenizer.py::test_admission_order_matches_greedy_for_arbitrary_nonadditive_counts[8]"),
    ("piece_added_token_gate_bypass", "benchmarks/piece_tokenizer.py", "_needs_fallback", "return False",
     "tests/test_piece_tokenizer.py::test_added_token_is_a_counterexample_to_naive_piece_summing"),
    ("answer_ledger_snapshot_race", "benchmarks/library_answer_report.py", None, None,
     "tests/test_library_answer_report.py::test_changed_ledger_cannot_mix_old_counts_with_a_new_digest"),
    ("request_spacing_bypass", "benchmarks/request_pacing.py", "wait", "return None",
     "tests/test_prospective_eval.py::test_executor_spaces_dispatch_before_recording_a_new_attempt[False]"),
    ("retry_after_recording_bypass", "benchmarks/repository_eval.py", "retry_after_seconds", "return None",
     "tests/test_prospective_eval.py::test_rate_limit_hint_is_recorded_without_retrying_the_request"),
    ("explicit_literal_intent_erasure", "npk/pack/select.py", "_explicit_literals", "return []",
     "tests/test_literal_seed_contract.py::test_public_selector_retrieves_explicit_short_or_filtered_literal"),
    ("local_budget_assumes_additivity", "npk/pack/select.py", "_fits",
     "return sum(self.tokenizer.count(e.text) for e in evidence)+self.tokenizer.count(text)+len(evidence)*self.tokenizer.count('\\n\\n')<=budget",
     "tests/test_local_budget_experiment.py::test_additive_cost_can_discard_a_passage_that_fits_exactly"),
    ("local_token_cache_changes_text", "npk/pack/tokenizer.py", "count", "text = ''.join(text.split())",
     "tests/test_local_token_budget.py::test_count_cache_is_bounded_disabled_and_isolated_between_tokenizers"),
    ("local_token_cache_bound_bypass", "npk/pack/tokenizer.py", "__init__", "cache_bytes = 10**8",
     "tests/test_local_token_budget.py::test_count_cache_is_bounded_disabled_and_isolated_between_tokenizers"),
    ("local_tokenizer_keeps_truncation", "npk/pack/tokenizer.py", None, None,
     "tests/test_local_token_budget.py::test_tokenizer_disables_stored_truncation_and_padding"),
    ("local_tokenizer_keeps_padding", "npk/pack/tokenizer.py", None, None,
     "tests/test_local_token_budget.py::test_tokenizer_disables_stored_truncation_and_padding"),
    ("local_tokenizer_allows_dropout", "npk/pack/tokenizer.py", None, None,
     "tests/test_local_token_budget.py::test_stochastic_bpe_dropout_is_refused"),
    ("local_budget_uses_estimate", "npk/pack/select.py", "_fits",
     "return max(1,(sum(len(e.text) for e in evidence)+len(text)+2*len(evidence))//4)<=budget",
     "tests/test_local_token_budget.py::test_exact_budget_can_admit_a_passage_rejected_by_character_estimates"),
    ("local_budget_final_guard_bypass", "npk/pack/select.py", "_enforce_final_budget", "return None",
     "tests/test_local_token_budget.py::test_final_guard_handles_nonadditive_counts_after_edits"),
    ("rival_exact_cost_bypass", "benchmarks/rival_reproduction.py", "exact_pack",
     "budget = 10**12",
     "tests/test_rival_reproduction.py::test_exact_pack_counts_full_assembly_and_skips_oversized"),
    ("rival_broadening_erases_query", "benchmarks/rival_reproduction.py", "exact_pack",
     "query = ''",
     "tests/test_rival_reproduction.py::test_empty_primary_pool_widens_with_the_original_query"),
    ("rival_source_attribution_bypass", "benchmarks/rival_reproduction.py", "attributed_context",
     "return '\\n\\n'.join(item['text'] for item in items)",
     "tests/test_rival_reproduction.py::test_foreign_or_disjoint_span_does_not_get_source_credit"),
    ("isolated_rate_limit_pause_bypass", "benchmarks/prospective_eval.py", "transport_pause_reason",
     "return None",
     "tests/test_prospective_eval.py::test_one_rate_limit_pauses_even_when_its_batch_also_succeeds"),
    ("ast_unicode_separator_as_newline", "benchmarks/operation_seeds.py", "physical_lines",
     "return text.splitlines(keepends=True)",
     "tests/test_operation_seeds.py::test_unicode_line_separator_inside_a_string_is_not_a_python_newline"),
    ("focused_seed_broadening_bypass", "benchmarks/operation_seeds.py", "focused_lexical",
     "return _lexical_channel(con, view, limit), False",
     "tests/test_operation_seeds.py::test_empty_focused_seeds_retry_the_original_query"),
    ("ast_byte_offset_as_character_offset", "benchmarks/operation_seeds.py", "offset",
     "return sum(map(len, lines[:line-1])) + column",
     "tests/test_operation_seeds.py::test_static_names_use_byte_correct_literal_query_spans"),
    ("side_index_ownership_read_before_lock", "benchmarks/spelling_index.py", "ownership_snapshot",
     "return dict(con.execute('SELECT file_id,digest FROM owners'))",
     "tests/test_spelling_index.py::test_update_ownership_snapshot_is_taken_under_the_write_lock"),
    ("side_index_parent_guard_bypassed", "benchmarks/spelling_index.py", "require_parent", "return None",
     "tests/test_spelling_index.py::test_stale_index_is_rejected_until_updated"),
    ("side_index_update_skipped", "benchmarks/spelling_index.py", "update",
     "if not create: return {'files_changed': 1, 'files_reused': 1}",
     "tests/test_spelling_index.py::test_stale_index_is_rejected_until_updated"),
    ("normalized_control_discarded_search", "benchmarks/spelling_index_eval.py", "rank_method",
     "if method == 'normalized_index': _lexical_channel(con, query, limit)",
     "tests/test_spelling_index.py::test_normalized_control_does_not_execute_a_discarded_baseline"),
    ("camel_spelling_expansion_erased", "npk/pack/select.py", "_lexical_terms", "return _content_terms(query)",
     "tests/test_identifier_spelling.py::test_compiled_runtime_recovers_an_absent_camel_alias_without_a_model"),
    ("known_compound_vocabulary_guard_bypassed", "npk/pack/select.py", None, None,
     "tests/test_identifier_spelling.py::test_compiled_runtime_keeps_a_known_compound_and_its_components"),
    ("unit_evidence_reconstruction_bypass", "benchmarks/unit_answer_plan.py", "reconstruct", "return [], ''",
     "tests/test_unit_answer_evidence.py::test_live_gate_rejects_changed_evidence[source]"),
    ("build_source_erasure", "npk/pack/compile.py", "scan_source",
     "global EXCLUDED_DIRS; EXCLUDED_DIRS = EXCLUDED_DIRS | {'build'}",
     "tests/test_build_source_directory.py::test_build_named_source_is_indexed_updated_and_retrievable[doc/build/orm/session_basics.rst]"),
    ("compiled_corpus_substitution", "benchmarks/compiled_source_contract.py", "require_compiled_sources", "return None",
     "tests/test_build_source_directory.py::test_valid_artifact_cannot_substitute_for_expected_corpus[True]"),
    ("passage_neighbor_disabled", "benchmarks/unit_passages.py", "select", "mode = 'seed'",
     "tests/test_unit_passages.py::test_neighbor_expansion_recovers_the_adjacent_exception"),
    ("boundary_empty_payload", "benchmarks/line_anchors.py", "split_anchored", "return []",
     "tests/test_line_anchor_experiment.py::test_one_long_line_cannot_be_claimed_to_meet_a_small_block_cap"),
    ("reuse_duplicate_old_payload", "benchmarks/block_reuse.py", "only_fresh", "return blocks",
     "tests/test_block_reuse_experiment.py::test_reused_rows_match_fresh_spans_indexes_and_queries[prepend]"),
    ("source_archive_omission", "benchmarks/source_archive.py", "manifest_sources", "return {}",
     "tests/test_source_archive.py::test_manifest_files_cannot_be_dropped_by_extension"),
    ("target_comparison_context_bypass", "benchmarks/target_controls_report.py", "compare", "identical_context = False",
     "tests/test_target_control_comparisons.py::test_changed_inputs_cannot_be_counted_as_target_configuration_gains[context_sha256-changed-source]"),
    ("target_transport_missing_reward", "benchmarks/target_controls_report.py", "compare",
     "return {'wins':[r['task'] for r in right],'losses':[],'ties':[],'missing':[]}",
     "tests/test_target_control_comparisons.py::test_missing_answers_cannot_be_reported_as_losses_or_gains"),
    ("replay_counted_as_new_api", "benchmarks/answer_records.py", "counts",
     "return {'attempts':len(ledger),'replayed_records':0}",
     "tests/test_answer_record_provenance.py::test_exact_parent_attempts_are_reused_without_new_api_calls[True]"),
    ("replay_origin_bypass", "benchmarks/answer_records.py", "validate_origin", "return None",
     "tests/test_answer_record_provenance.py::test_replay_tampering_is_detected[answer]"),
    ("raw_usage_authority_bypass", "benchmarks/answer_records.py", "validate_response", "return None",
     "tests/test_answer_record_provenance.py::test_raw_provider_usage_is_the_token_count_authority[changed_summary]"),
    ("whitespace_semantics_erasure", "npk/planner.py", "plan_and_optimize",
     "messages = [dict(m, content=' '.join(m.get('content', '').split())) for m in messages]",
     "tests/test_message_transform_preservation.py::test_default_preserves_semantically_significant_repetition_and_spacing[distinct_string_literals]"),
    ("message_history_reordering", "npk/planner.py", "plan_and_optimize",
     "messages = sorted(messages, key=lambda m: m.get('role') != 'tool')",
     "tests/test_message_transform_preservation.py::test_default_preserves_semantically_significant_repetition_and_spacing[message_order_and_tool_metadata]"),
    ("message_envelope_gate_bypass", "npk/context/safety.py", "check_invariants",
     "return InvariantReport(ok=True)",
     "tests/test_message_transform_preservation.py::test_message_envelope_and_history_changes_are_rejected[tool_link]"),
    ("unmeasured_transform_claims_preservation", "npk/context/safety.py", "assess_risk",
     "context_unchanged = True",
     "tests/test_message_transform_preservation.py::test_missing_selection_measurements_do_not_imply_losslessness"),
    ("dependency_identity", "npk/context/graph_slicer.py", "compute_transitive_closure",
     "return set(seed_nodes)", "tests/test_safety_invariants.py::test_dependency_expansion_reaches_transitively_connected_block"),
    ("query_erasure", "npk/context/safety.py", "extract_query", "return ''",
     "tests/test_safety_invariants.py::test_planner_routes_the_current_question_to_retrieval"),
    ("fallback_bypass", "npk/planner.py", None, None,
     "tests/test_safety_invariants.py::test_planner_falls_back_when_a_stage_destroys_context"),
    ("budget_override", "npk/pack/select.py", "_select_once", "budget = max(budget, 10000)",
     "tests/test_compiled_contracts.py::test_escalation_does_not_override_explicit_budget"),
    ("missing_query_tripwire", "npk/pack/select.py", "select", "query = ''",
     "tests/test_compiled_contracts.py::test_default_query_never_loads_optional_channels"),
    ("integrity_bypass", "npk/pack/format.py", "compute_root_digest", "return '0'*64",
     "tests/test_pack_integrity.py::test_modified_contents_or_indexes_fail_verification[UPDATE manifest SET value='different-source' WHERE key='source_root']"),
    ("class_member_erasure", "npk/pack/compile.py", "_class_member_spans", "return []",
     "tests/test_python_members.py::test_nested_classes_decorators_and_context_keep_exact_source_spans"),
    ("encoder_identity_bypass", "npk/pack/format.py", "require_encoder_match", "return None",
     "tests/test_pack_encoder_contract.py::test_same_dimensions_do_not_make_different_encoders_compatible"),
    ("embedding_cache_alias", "npk/context/embedding.py", "_cache_key", "return '|NPKSEP|'.join(texts)",
     "tests/test_embedding_identity.py::test_text_separator_cannot_alias_a_different_batch"),
    ("unchanged_vector_reuse_bypass", "npk/pack/compile.py", "_embed_blocks", "reuse_vectors = False",
     "tests/test_embedding_reuse.py::test_one_changed_method_only_submits_its_new_text"),
    ("insertion_order_lexical_ties", "npk/pack/select.py", "_lexical_channel",
     "return [r['block_id'] for r in con.execute('SELECT rowid AS block_id FROM lexical WHERE lexical MATCH ? ORDER BY bm25(lexical) LIMIT ?', (' OR '.join(chr(34)+t+chr(34) for t in _content_terms(query)),limit))]",
     "tests/test_retrieval_order.py::test_equal_scores_use_source_order_after_an_update[lexical]"),
    ("incomplete_directory_scan", "npk/pack/compile.py", "_source_scan_error", "return None",
     "tests/test_source_scan_failures.py::test_incomplete_scan_preserves_prior_artifact[directory-update]"),
    ("dirty_journal_bypass", "npk/pack/integrity.py", "refresh_file_digests", "con.execute('DELETE FROM integrity_dirty')",
     "tests/test_pack_encoder_contract.py::test_weights_available_after_unembedded_compile_indexes_all_files"),
    ("cached_verification", "npk/pack/integrity.py", "compute_digest", "cached = True",
     "tests/test_incremental_integrity.py::test_full_verifier_does_not_trust_a_cleared_dirty_journal"),
    ("reader_snapshot_bypass", "npk/pack/format.py", "open_pack", "readonly = False",
     "tests/test_pack_snapshots.py::test_query_cannot_mix_old_candidate_ids_with_a_concurrently_committed_update"),
    ("schema_transaction_bypass", "npk/pack/compile.py", None, None,
     "tests/test_compile_transactions.py::test_all_schema_and_tracking_creation_share_the_build_transaction"),
    ("definition_channel_disabled", "npk/pack/select.py", "_definition_channel", "return []",
     "tests/test_definition_channel.py::test_named_definition_outranks_documentation_that_repeats_the_prose"),
    ("definition_ambiguity_cap_ignored", "npk/pack/select.py", "_definition_channel",
     "globals()['MAX_DEFINITION_AMBIGUITY'] = 10**9",
     "tests/test_definition_channel.py::test_ambiguous_names_cast_no_vote"),
    ("top_block_trim_disabled", "npk/pack/select.py", "_member_spans", "return []",
     "tests/test_top_block_trim.py::test_top_block_that_cannot_fit_emits_its_best_member"),
    ("test_mate_disabled", "npk/pack/select.py", "_test_mate", "return None",
     "tests/test_test_mate.py::test_mate_follows_top_implementation_block"),
    ("test_mate_deep_ranking_misread", "npk/pack/select.py", "_test_mate",
     "deep = list(reversed(deep)) if deep else deep",
     "tests/test_test_mate.py::test_reused_ranking_matches_a_dedicated_query"),
    ("test_mate_gate_ignored", "npk/pack/select.py", None, None,
     "tests/test_test_mate.py::test_default_mate_is_budget_gated"),
    ("test_mate_paths_never_refreshed", "npk/pack/select.py", "_place_test_mate",
     "self._test_paths_key = manifest.get('root_sha256', '')",
     "tests/test_test_mate.py::test_mate_sees_test_files_added_by_an_update"),
    ("credential_screen_bypass", "npk/pack/source_policy.py", "credential_kind", "return None",
     "tests/test_source_boundary.py::test_credential_shaped_source_is_never_published[nvidia-compile]"),
    ("credential_update_bypass", "npk/pack/source_policy.py", "credential_kind", "return None",
     "tests/test_source_boundary.py::test_credential_shaped_source_is_never_published[nvidia-update]"),
    ("indexed_unsupported_silently_skipped", "npk/pack/compile.py", "scan_source", "indexed = set()",
     "tests/test_source_scan_failures.py::test_invalid_utf8_cannot_silently_change_source_meaning"),
    ("unsupported_source_not_reported", "npk/pack/compile.py", "scan_source", "skipped = None",
     "tests/test_source_scan_failures.py::test_initial_compile_reports_and_skips_unindexable_source[nul]"),
    ("literal_artifact_uri_bypass", "npk/pack/format.py", None, None,
     "tests/test_pack_paths.py::test_artifact_path_is_literal_across_compile_query_update_and_verify"),
    ("missing_pack_creation", "npk/pack/format.py", "connect", "create = True",
     "tests/test_source_boundary.py::test_missing_pack_update_must_not_create_an_empty_artifact"),
    ("unicode_source_rewrite", "npk/pack/compile.py", "_source_lines", "return source.splitlines()",
     "tests/test_source_lines.py::test_compile_update_and_query_preserve_unicode_source_content"),
    ("source_span_verifier_bypass", "npk/pack/format.py", "_valid_block_span", "return True",
     "tests/test_source_lines.py::test_self_consistent_hashes_do_not_validate_an_impossible_source_span"),
    ("during_read_metadata_bypass", "npk/pack/source_policy.py", "stat_identity", "return None",
     "tests/test_source_boundary.py::test_same_size_change_during_read_cannot_publish_stale_text"),
    ("stored_type_verifier_bypass", "npk/pack/contracts.py", "require_stored_types", "return None",
     "tests/test_pack_storage_types.py::test_blob_block_text_returns_invalid_instead_of_crashing_verification"),
    ("manifest_type_bypass", "npk/pack/format.py", "read_manifest",
     "return {r['key']:r['value'] for r in con.execute('SELECT key,value FROM manifest')}",
     "tests/test_pack_storage_types.py::test_blob_manifest_is_rejected_before_query_or_verification"),
    ("update_manifest_bypass", "npk/pack/compile.py", None, None,
     "tests/test_pack_storage_types.py::test_blob_manifest_is_rejected_before_query_or_verification"),
    ("connection_setup_leak", "npk/pack/format.py", None, None,
     "tests/test_pack_storage_types.py::test_writable_setup_error_closes_connection_and_returns_product_error"),
    ("ambiguous_answer_acceptance", "benchmarks/repository_eval.py", "grade_answer",
     "return {'task_success':True,'parse_error':False,'parsed':json.loads(content)}",
     "tests/test_repository_eval.py::test_ambiguous_keys_and_non_json_constants_cannot_pass_strict_grading"),
    ("manifest_policy_bypass", "npk/pack/contracts.py", "require_manifest_values", "return None",
     "tests/test_pack_manifest_values.py::test_unknown_mode_cannot_silently_enter_a_product_operation"),
    ("manifest_content_bypass", "npk/pack/contracts.py", "require_content_metadata", "return None",
     "tests/test_pack_manifest_values.py::test_resealed_invalid_metadata_is_rejected[file_count-99]"),
    ("secret_scan_read_failure_bypass", "tests/test_secrets.py", "test_no_secrets_in_tracked_files", "return None",
     "tests/test_secret_scan_errors.py::test_scan_read_failures_are_visible_without_echoing_values"),
    ("audit_undefined_retention", "npk/auditor.py", "_retention", "return 100.0",
     "tests/test_auditor_contract.py::test_zero_baseline_cannot_report_full_retention[wrong]"),
    ("audit_duplicate_identity", "npk/auditor.py", "_by_id", "return {row['id']: row for row in rows}",
     "tests/test_auditor_contract.py::test_incomplete_or_ambiguous_evidence_is_rejected[duplicate_usage]"),
    ("audit_usage_validation_bypass", "npk/auditor.py", "_require_usage", "return None",
     "tests/test_auditor_contract.py::test_incomplete_or_ambiguous_evidence_is_rejected[negative_tokens]"),
    ("report_observation_bypass", "benchmarks/modern_seed_report.py", "audit_observations", "return len(rows)",
     "tests/test_seed_report_contract.py::test_report_rejects_observation_or_answer_forgery"),
    ("unknown_price_fallback", "npk/cost.py", "get_pricing", "return PRICING_TABLE['gpt-4o-mini']",
     "tests/test_pricing_provenance.py::test_unknown_or_mock_prices_are_absent"),
    ("price_provider_identity", "npk/cost.py", "get_pricing", "provider = 'openai'",
     "tests/test_pricing_provenance.py::test_provider_identity_precision_and_signed_savings"),
    ("price_count_validation", "npk/cost.py", "_require_counts", "return None",
     "tests/test_pricing_provenance.py::test_invalid_usage_is_rejected_even_without_a_price"),
    ("price_provenance_validation", "npk/cost.py", "__post_init__", "return None",
     "tests/test_pricing_provenance.py::test_placeholder_provenance_cannot_be_verified"),
    ("legacy_trace_cost_acceptance", "npk/telemetry.py", "analyze_traces",
     "return {'total_cost_saved_est': 99, 'total_tokens_avoided': 999, 'legacy_records': 0}",
     "tests/test_pricing_provenance.py::test_legacy_trace_cost_claims_are_not_accepted_as_evidence"),
    ("runtime_risk_threshold_inversion", "npk/runtime.py", "chat_completion", "self.quality_threshold = 1-self.quality_threshold",
     "tests/test_pricing_provenance.py::test_runtime_risk_limit_is_not_inverted"),
    ("legacy_default_encoder_probe", "npk/context/info_gain.py", "select", "self.enable_escalation = True",
     "tests/test_optional_client_encoders.py::test_default_client_does_not_probe_an_encoder[selector]"),
    ("client_encoder_optin_ignored", "npk/context/retrieval.py", "retrieve_relevant_context", "self.enable_escalation = False",
     "tests/test_optional_client_encoders.py::test_explicit_client_encoder_is_wired_and_isolated[client]"),
    ("legacy_seed_budget_override", "npk/context/info_gain.py", "select", "token_budget = max(token_budget, 10000)",
     "tests/test_legacy_budget_contract.py::test_oversized_seed_requires_fallback_instead_of_budget_override"),
    ("legacy_fallback_misclassified", "npk/context/retrieval.py", "_full_fallback",
     "return context_text, {'seed_failed': False, 'fallback_required': False, 'budget_exceeded': False}",
     "tests/test_legacy_budget_contract.py::test_dependency_join_overflow_requires_explicit_fallback"),
    ("legacy_selection_report_bypass", "benchmarks/legacy_seed_audit.py", "audit", "return len(rows)",
     "tests/test_legacy_seed_evidence.py::test_local_selection_report_rejects_tampering"),
    ("current_query_counted_as_evidence", "npk/context/safety.py", "_context_body",
     "return '\\n'.join(m.get('content', '') for m in messages if m.get('role') == 'user')",
     "tests/test_message_boundary_invariants.py::test_long_separate_query_does_not_hide_deleted_context"),
    ("long_query_prefix_erasure", "npk/context/safety.py", "extract_query",
     "return [m['content'] for m in messages if m.get('role') == 'user'][-1].split('\\n\\n')[-1]",
     "tests/test_message_boundary_invariants.py::test_mult_paragraph_query_keeps_earlier_constraints"),
]


def main():
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="experiments/results/contract-mutations.json")
    parser.add_argument("--mutant",action="append",choices=[m[0] for m in MUTANTS],
                        help="Run only named tripwires; omitted means the complete suite")
    args = parser.parse_args()
    # Benchmark mutants and their tests are executable evidence too. Capturing
    # only npk/ left those parts of the claimed mutation baseline unbound.
    source_hashes = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for directory in ("npk", "benchmarks", "tests")
                     for p in (repo / directory).rglob("*.py")}
    rows = []
    with tempfile.TemporaryDirectory(prefix="npk-mutations-") as tmp:
        root = Path(tmp).resolve()
        snapshot = root / "snapshot"
        for directory in ("npk", "tests", "benchmarks"):
            shutil.copytree(repo / directory, snapshot / directory,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name, relative, function, statement, test in MUTANTS:
            if args.mutant and name not in args.mutant:continue
            path = snapshot / relative
            original = path.read_bytes()
            source = original.decode("utf-8")
            if function:
                changed = mutate_function(source, function, statement)
            elif name == "encoder_offline_flag_bypass":
                tree = ast.parse(source)
                matches = [node for node in ast.walk(tree) if isinstance(node, ast.Dict)
                           and [k.value if isinstance(k, ast.Constant) else None for k in node.keys]
                           == ['local_files_only', 'trust_remote_code']]
                if len(matches) != 1: raise ValueError('offline loader options are no longer unique')
                assert isinstance(matches[0].values[0], ast.Constant) and matches[0].values[0].value is True
                matches[0].values[0] = ast.Constant(value=False)
                changed = ast.unparse(ast.fix_missing_locations(tree))+'\n'
            elif name == "test_mate_gate_ignored":
                target = "budget >= TEST_MATE_MIN_BUDGET if self.enable_test_mate is None"
                if source.count(target) != 1:
                    raise ValueError("test-mate budget gate is no longer unique")
                changed = source.replace(target, "True if self.enable_test_mate is None")
            elif name == "known_compound_vocabulary_guard_bypassed":
                target = "return whole or expanded"
                if source.count(target) != 1:
                    raise ValueError("known-compound guard is no longer unique")
                changed = source.replace(
                    target,
                    "return _rank_lexical_terms(con, terms[1:], limit)",
                )
            elif name == "count_cache_receipt_capture_race":
                tree = ast.parse(source)
                matches = [node for node in ast.walk(tree) if isinstance(node, ast.Expr)
                           and ast.unparse(node) == "con.execute('PRAGMA locking_mode=EXCLUSIVE')"]
                if len(matches) != 1: raise ValueError('receipt writer lock is no longer unique')
                target = matches[0]
                for node in ast.walk(tree):
                    for field,value in ast.iter_fields(node):
                        if isinstance(value,list) and target in value:
                            value[value.index(target)] = ast.Pass()
                changed = ast.unparse(ast.fix_missing_locations(tree))+'\n'
            elif name == "verified_partition_gate_bypass":
                tree = ast.parse(source)
                matches = [node for node in ast.walk(tree) if isinstance(node, ast.If)
                           and ast.unparse(node.test) == 'tuple(expected) != actual']
                if len(matches) != 1: raise ValueError('piece equality gate is no longer unique')
                matches[0].test = ast.Constant(value=False)
                changed = ast.unparse(ast.fix_missing_locations(tree))+'\n'
            elif name in ('reference_overload_last_pick', 'reference_unicode_physical_lines'):
                target, replacement = {
                    'reference_overload_last_pick': ('matches = found[name]', 'matches = found[name][-1:]'),
                    'reference_unicode_physical_lines': ("lines = source[path].split('\\n')", 'lines = source[path].splitlines()')
                }[name]
                if source.count(target) != 1: raise ValueError('reference source gate is no longer unique')
                changed = source.replace(target, replacement)
            elif name == "answer_missing_transport_complete":
                target = "answers_complete = complete and all(r['transport_success'] for r in results.values())"
                if source.count(target) != 1: raise ValueError('answer completeness gate is no longer unique')
                changed = source.replace(target, 'answers_complete = complete')
            elif name == "answer_ledger_snapshot_race":
                target = "assert (a.run/'ledger.json').read_bytes() == ledger_bytes, 'ledger changed during audit; wait for a quiescent batch'"
                if source.count(target) != 1: raise ValueError('ledger snapshot gate is no longer unique')
                changed = source.replace(target, 'pass  # MUTANT: allow a changing ledger')
            elif name in ("local_tokenizer_keeps_truncation", "local_tokenizer_keeps_padding", "local_tokenizer_allows_dropout"):
                target = {"local_tokenizer_keeps_truncation":"backend.no_truncation()",
                          "local_tokenizer_keeps_padding":"backend.no_padding()",
                          "local_tokenizer_allows_dropout":"if config['model'].get('dropout') not in (None, 0, 0.0):"}[name]
                if source.count(target)!=1: raise ValueError('tokenizer guard is no longer unique')
                changed = source.replace(target, 'if False:' if name.endswith('dropout') else 'pass')
            elif name=="schema_transaction_bypass":
                target='con.executescript("BEGIN;\\n" + SCHEMA)'
                if source.count(target)!=1:
                    raise ValueError("schema transaction is no longer unique")
                changed=source.replace(target,'con.executescript(SCHEMA)')
            elif name=="literal_artifact_uri_bypass":
                target='p.as_uri()+f"?mode={mode}"'
                if source.count(target)!=1:
                    raise ValueError("artifact URI construction is no longer unique")
                changed=source.replace(target,'f"file:{p}?mode={mode}"')
            elif name=="update_manifest_bypass":
                target='manifest = read_manifest(con)'
                if source.count(target)!=1:raise ValueError('update manifest call is no longer unique')
                changed=source.replace(target,"manifest = {r['key']:r['value'] for r in con.execute('SELECT key,value FROM manifest')}")
            elif name=="connection_setup_leak":
                tree=ast.parse(source)
                function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='connect')
                closes=[n for n in ast.walk(function) if isinstance(n,ast.Expr) and ast.unparse(n)=='con.close()']
                if len(closes)!=1:raise ValueError('setup cleanup is no longer unique')
                lines=source.splitlines(keepends=True);lines[closes[0].lineno-1]=' '*closes[0].col_offset+'pass  # MUTANT: leaked connection\n'
                changed=''.join(lines)
            elif name == "trusted_schema_allowed":
                target = 'con.execute("PRAGMA trusted_schema=OFF")'
                if source.count(target) != 1: raise ValueError('trusted_schema is not unique')
                changed = source.replace(target, 'con.execute("PRAGMA trusted_schema=ON")')
            elif name == "query_only_disabled":
                target = 'con.execute("PRAGMA query_only=ON")'
                if source.count(target) != 1: raise ValueError('query_only is not unique')
                changed = source.replace(target, 'con.execute("PRAGMA query_only=OFF")')
            elif name == "symbols_include_language_keywords":
                target = '    if block.name:\n        seen.setdefault(block.name, ("definition", True))'
                if source.count(target) != 1: raise ValueError('symbol definition anchor is not unique')
                replacement = target + (
                    '\n    for match in IDENT_RE.finditer(block.text):\n'
                    '        seen.setdefault(match.group(0), ("reference", False))'
                )
                changed = source.replace(target, replacement)
            elif name == "symbols_prose_references_unfiltered":
                target = '    if block.name:\n        seen.setdefault(block.name, ("definition", True))'
                if source.count(target) != 1: raise ValueError('symbol definition anchor is not unique')
                replacement = target + (
                    '\n    if language == "markdown":\n'
                    '        for match in IDENT_RE.finditer(block.text):\n'
                    '            seen.setdefault(match.group(0), ("reference", False))'
                )
                changed = source.replace(target, replacement)
            elif name == "query_cache_serves_stale_root":
                target = 'manifest.get("root_sha256", ""),'
                if source.count(target) != 1: raise ValueError('root_sha256 target is not unique')
                changed = source.replace(target, '"static_root",')
            elif name == "canonical_ordering_unsorted":
                target = 'ordered = sorted(self.evidence, key=_source_order)'
                if source.count(target) != 1: raise ValueError('canonical sort target is not unique')
                changed = source.replace(target, 'ordered = self.evidence')
            elif name == "quick_update_reads_untouched_files":
                target = 'known_files = {r["path"]: (r["sha256"], r["size"], r["mtime_ns"]) for r in existing_rows} if quick else None'
                if source.count(target) != 1: raise ValueError('known_files guard is not unique')
                changed = source.replace(target, 'known_files = None')
            elif name == "write_file_blocks_drops_lexical_batch":
                target = 'if lex_rows:\n        con.executemany(\n            "INSERT INTO lexical(rowid, text, name, path) VALUES(?,?,?,?)", lex_rows\n        )'
                if source.count(target) != 1: raise ValueError('lexical batch is not unique')
                changed = source.replace(target, 'pass')
            else:
                target = "if not report.ok:"
                if source.count(target) != 1:
                    raise ValueError("fallback gate is no longer unique")
                changed = source.replace(target, "if False:  # MUTANT: bypass invariant gate")
            path.write_text(changed, encoding="utf-8")
            junit = root / (name + ".xml")
            basetemp = root / "basetemp" / name
            basetemp.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join([str(snapshot), str(repo / '.venv/Lib/site-packages')])
            try:
                proc = subprocess.run([sys.executable, "-B", "-m", "pytest", test, "-q",
                                       "-p", "no:cacheprovider", f"--basetemp={basetemp}",
                                       f"--junitxml={junit}"],
                                      cwd=snapshot, env=env, capture_output=True, text=True, timeout=60)
                if not junit.exists():
                    raise RuntimeError(f"pytest did not produce a test result: stdout={proc.stdout} stderr={proc.stderr}")
                tree = ET.parse(junit)
                failures = tree.findall(".//testcase/failure")
                errors = tree.findall(".//testcase/error")
                assertions = failures and all("AssertionError" in (f.text or "") for f in failures)
                status = "KILLED" if proc.returncode == 1 and assertions and not errors else "HARNESS_ERROR" if proc.returncode != 0 else "SURVIVED"
                rows.append({"mutant": name, "status": status, "test": test,
                             "exit_code": proc.returncode, "failure_types": [f.attrib.get("type") for f in failures]})
                print(rows[-1], flush=True)
                if status == "HARNESS_ERROR":
                    print(proc.stdout[-2500:], flush=True)
            finally:
                path.write_bytes(original)
    for path, expected in source_hashes.items():
        if hashlib.sha256((repo / path).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"worktree changed during mutation run: {path}")
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"evidence_mode": "LOCAL", "source_hashes": source_hashes,
                                  "rows": rows}, indent=2), encoding="utf-8")
    if any(row["status"] != "KILLED" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
