"""Runs every guard check, in the order the single-file suite ran them."""
from . import (
    ansi_tap_judge,
    api_client,
    build_ref_jobspec,
    callbacks,
    config_drift_parser,
    downloads,
    interface_checks,
    jobrun_checks,
    model_checks,
    poll_checks,
    ports,
    references,
    retention_checks,
    sources,
    state_cursor,
    worker_lock,
)


def main():
    """Run every check; check() exits 1 on the first failure (never 2)."""
    ansi_tap_judge.test_strip_ansi()
    ansi_tap_judge.test_tap_summary()
    ansi_tap_judge.test_job_error()
    ansi_tap_judge.test_lava_body_cap_and_boot_guard()
    jobrun_checks.test_build_command_validation()
    jobrun_checks.test_build_command_argv()
    model_checks.test_outcome_is_dict_shaped_for_old_readers()
    model_checks.test_job_run_matches_the_table_line()
    model_checks.test_jobs_runs_a_row_and_records_it()
    model_checks.test_job_run_refuses_an_unknown_delivery_and_files_its_source()
    model_checks.test_job_run_local_server_delivery()
    interface_checks.test_stack_argv_matches_the_entry_point()
    interface_checks.test_stack_status_reads_a_stopped_stack()
    interface_checks.test_dashboard_argv_and_banner()
    interface_checks.test_results_reads_the_ledger_and_its_report()
    interface_checks.test_interface_package_imports_nothing_from_scripts()
    interface_checks.test_interface_exports_its_public_names()
    jobrun_checks.test_run_node_never_raises_on_a_malformed_definition()
    poll_checks.test_iso_ago()
    callbacks.test_post_result_classification()
    downloads.test_download_complete_part_and_416()
    state_cursor.test_state_roundtrip()
    state_cursor.test_start_cursor()
    jobrun_checks.test_clamp_timeout()
    jobrun_checks.test_archive_console_log()
    poll_checks.test_handle_event_non_json()
    poll_checks.test_job_definition_failure_is_transient()
    callbacks.test_missing_callback_keeps_result_pending()
    callbacks.test_state_flushed_before_a_crash()
    poll_checks.test_poll_loop_persists_cursor_and_seen()
    state_cursor.test_seen_eviction()
    ports.test_port_probe()
    build_ref_jobspec.test_build_ref_and_jobspec()
    api_client.test_api_latest_prefix()
    api_client.test_api_all_nodes_pages()
    api_client.test_api_non_json_is_api_error()
    api_client.test_api_refuses_redirect()
    api_client.test_api_retries_a_dropped_connection()
    sources.test_table_source_subtracts_the_ledger()
    sources.test_newest_source_widens_the_window()
    sources.test_newest_source_reports_no_build()
    sources.test_get_source_unknown_name()
    references.test_no_repo_root_is_counted_with_dirname()
    references.test_layers_import_downward_only()
    retention_checks.test_retention_plan_and_prune()
    references.test_shell_scripts_reference_live_modules()
    config_drift_parser.test_config_drift_parser()
    worker_lock.test_worker_lock()
    print("\nALL GUARD CHECKS PASSED")
    return 0
