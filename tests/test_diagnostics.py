"""Synthetic, offline tests. No connector initialization or external services."""

import argparse
import ast
import copy
from contextlib import closing, redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from sec_connector import diagnostics as diag


ROOT = Path(__file__).resolve().parents[1]
TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("state", "downloads", "private"):
            (self.root / name).mkdir()
        self.args = argparse.Namespace(
            db=self.root / "state" / "state.db", downloads=self.root / "downloads",
            connection_id="fixture", scope=list(diag.SCOPES), config=self.root / "config.yaml",
            code_root=ROOT / "src" / "sec_connector", schema=ROOT / "config" / "schema.json",
            graph=False, out=self.root / "private" / "report.json",
        )
        self.schema = diag.load_json(self.args.schema)
        self.runtime = diag.runtime_info(self.args.code_root, self.schema)
        self.payload = {
            "id": "example0",
            "content": {"type": "text", "value": "PNC Market Capitalization (in billions) 76.4"},
            "properties": {"SectionTitle": "Peer group", "ChunkOrdinal": 1},
            "acl": [{"type": "everyone", "value": "everyone", "accessType": "grant"}],
        }
        self.args.config.write_text(
            f"azure:\n  tenant_id: {TENANT}\n  client_id: {CLIENT}\n"
            "  client_secret: SECRET_SENTINEL\n  connection_id: fixture\n", encoding="utf-8")
        with closing(sqlite3.connect(self.args.db)) as db:
            db.executescript("""
                CREATE TABLE destination(tenant_id, connection_id, version);
                CREATE TABLE filings(id, cik, accession_number, metadata, processing_options, state,
                                     inventory_complete, payloads_ready, sample_limit);
                CREATE TABLE documents(filing_id, filename, metadata, state);
                CREATE TABLE chunks(chunk_id, filing_id, filename, payload, state);
                CREATE TABLE delivered_items(chunk_id, filing_id, payload_hash);
                CREATE TABLE document_cache(filing_id, filename, fingerprint, payloads);
                CREATE TABLE reconciliation_candidates(filing_id, chunk_id);
                CREATE TABLE maintenance_operations(phase);
            """)
            db.execute("INSERT INTO destination VALUES (?,?,4)", (TENANT, "fixture"))
            for index, scope in enumerate(self.args.scope):
                cik, accession, filename = diag.parse_scope(scope)
                source = self.args.downloads / cik / accession.replace("-", "") / filename
                source.parent.mkdir(parents=True)
                source.write_text("synthetic source", encoding="utf-8")
                options = {"processing_version": self.runtime["processing_version"], "ocr_images": False,
                           "schema_hash": self.runtime["schema_stored_format_sha256"], "chunking": {"max_size": 8000}}
                metadata = {"cik": cik, "accession_number": accession}
                document = {"filename": filename}
                payload = copy.deepcopy(self.payload)
                payload["id"] = f"example{index}"
                fingerprint = hashlib.sha256(json.dumps({
                    "source": diag.file_digest(source), "filing": metadata, "document": document,
                    "options": options, "remaining": None,
                }, sort_keys=True).encode()).hexdigest()
                db.execute("INSERT INTO filings VALUES (?,?,?,?,?,'completed',1,1,NULL)",
                           (index, cik, accession, json.dumps(metadata), json.dumps(options)))
                db.execute("INSERT INTO documents VALUES (?,?,?,'parsed')", (index, filename, json.dumps(document)))
                db.execute("INSERT INTO chunks VALUES (?,?,?,?,'uploaded')",
                           (payload["id"], index, filename, json.dumps(payload)))
                db.execute("INSERT INTO delivered_items VALUES (?,?,?)",
                           (payload["id"], index, diag.payload_digest(payload)))
                db.execute("INSERT INTO document_cache VALUES (?,?,?,?)",
                           (index, filename, fingerprint, json.dumps([payload])))
            db.commit()

    def mutate(self, sql, params=()):
        with closing(sqlite3.connect(self.args.db)) as db:
            db.execute(sql, params)
            db.commit()

    def collect(self):
        report = {"report_version": diag.REPORT_VERSION, "kind": "collection"}
        with patch.object(diag.urllib.request, "build_opener", side_effect=AssertionError("network")):
            return diag.collect(self.args, report)

    def cli(self, extra=(), out=None):
        argv = ["collect", "--db", str(self.args.db), "--downloads", str(self.args.downloads),
                "--code-root", str(self.args.code_root), "--schema", str(self.args.schema),
                "--connection-id", self.args.connection_id, "--out", str(out or self.args.out), *extra]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return diag.main(argv)

    def test_readonly_connection_no_sidecars_no_mutations_explicit_close(self):
        before = {path.name: path.read_bytes() for path in self.args.db.parent.iterdir()}
        connect = sqlite3.connect
        opened, statements = [], []

        def open_readonly(database, **kwargs):
            self.assertIn("?mode=ro&immutable=1", database)
            self.assertTrue(kwargs["uri"])
            db = connect(database, **kwargs)
            db.set_trace_callback(statements.append)
            opened.append(db)
            return db

        with patch.object(diag.sqlite3, "connect", side_effect=open_readonly):
            report = self.collect()
        self.assertFalse(report["findings"])
        self.assertEqual(report["status"], "complete")
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.args.db.parent.iterdir()})
        self.assertTrue(any(sql == "PRAGMA query_only=ON" for sql in statements))
        self.assertFalse(any(sql.split()[0] in {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"} for sql in statements))
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")

    def test_missing_database_is_not_created(self):
        self.args.db = self.args.db.with_name("missing.db")
        self.assertEqual(self.cli(), 2)
        self.assertFalse(self.args.db.exists())

    def test_journals_rejected_without_open(self):
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                path = Path(str(self.args.db) + suffix)
                path.write_bytes(b"synthetic")
                with patch.object(diag.sqlite3, "connect", side_effect=AssertionError("must not open")):
                    with self.assertRaisesRegex(diag.DiagnosticError, "journal_present"):
                        diag.read_local(self.args, self.runtime)
                path.unlink()

    def test_committed_wal_data_rejected_before_evidence_or_authentication(self):
        with closing(sqlite3.connect(self.args.db)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("UPDATE filings SET state='failed' WHERE id=0")
            writer.commit()
            self.assertGreater(Path(str(self.args.db) + "-wal").stat().st_size, 0)
            self.assertEqual(writer.execute("SELECT state FROM filings WHERE id=0").fetchone()[0], "failed")
            # Demonstrate the stale view immutable mode would expose if the guard
            # were removed: the committed failure exists only in the WAL.
            with closing(sqlite3.connect(self.args.db.as_uri() + "?mode=ro&immutable=1", uri=True)) as stale:
                self.assertEqual(stale.execute("SELECT state FROM filings WHERE id=0").fetchone()[0], "completed")
            before = {path.name: path.read_bytes() for path in self.args.db.parent.iterdir()}
            with patch.object(diag.sqlite3, "connect", side_effect=AssertionError("must not open")), \
                    patch.object(diag, "authenticate", side_effect=AssertionError("must not authenticate")):
                self.assertEqual(self.cli(["--graph", "--config", str(self.args.config)]), 2)
            report = diag.load_json(self.args.out)
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["error"], "journal_present_stop_writer_and_use_operator_managed_snapshot")
            self.assertNotIn("local", report)
            self.assertNotIn("graph", report)
            self.assertEqual(before, {path.name: path.read_bytes() for path in self.args.db.parent.iterdir()})

    def test_journal_appearing_during_read_discards_local_evidence(self):
        inspect = diag.inspect_document
        journal = Path(str(self.args.db) + "-journal")

        def inspect_with_journal(*args):
            result = inspect(*args)
            journal.write_bytes(b"synthetic concurrent journal")
            return result

        with patch.object(diag, "inspect_document", side_effect=inspect_with_journal):
            self.assertEqual(self.cli(), 2)
        report = diag.load_json(self.args.out)
        self.assertEqual(report["error"], "journal_present_stop_writer_and_use_operator_managed_snapshot")
        self.assertNotIn("local", report)

    def test_versions_and_schema_rejected_without_migration(self):
        for version in (1, 2, 5, 999):
            self.mutate("UPDATE destination SET version=?", (version,))
            before = self.args.db.read_bytes()
            with self.assertRaisesRegex(diag.DiagnosticError, "state_version"):
                self.collect()
            self.assertEqual(before, self.args.db.read_bytes())
        self.mutate("UPDATE destination SET version=3")
        self.assertFalse(self.collect()["findings"])
        self.mutate("ALTER TABLE chunks RENAME COLUMN payload TO unsupported")
        with self.assertRaisesRegex(diag.DiagnosticError, "unsupported_database_schema"):
            self.collect()

    def test_terminal_and_unknown_maintenance_phases(self):
        for phase in ("completed", "rolled_back"):
            self.mutate("INSERT INTO maintenance_operations VALUES (?)", (phase,))
        self.assertFalse(self.collect()["findings"])
        self.mutate("INSERT INTO maintenance_operations VALUES ('verified')")
        self.mutate("INSERT INTO maintenance_operations VALUES ('SECRET_SENTINEL')")
        report = self.collect()
        self.assertEqual(report["local"]["nonterminal_maintenance_phases"], ["unknown", "verified"])
        self.assertTrue(report["findings"])
        self.assertNotIn("SECRET_SENTINEL", json.dumps(report))

    def test_wrong_database_destination_stops_before_auth(self):
        self.args.connection_id = "Fixture"
        with patch.object(diag, "authenticate", side_effect=AssertionError("auth")):
            self.assertEqual(self.cli(["--graph", "--config", str(self.args.config)]), 2)
        report = diag.load_json(self.args.out)
        self.assertEqual(report["error"], "database_destination_mismatch_no_authentication")

    def test_wrong_config_destination_stops_before_auth_and_retains_local(self):
        self.args.config.write_text(self.args.config.read_text().replace("fixture", "wrong"), encoding="utf-8")
        with patch.object(diag, "authenticate", side_effect=AssertionError("auth")):
            self.assertEqual(self.cli(["--graph", "--config", str(self.args.config)]), 2)
        report = diag.load_json(self.args.out)
        self.assertIn("local", report)
        self.assertEqual(report["error"], "config_destination_mismatch_no_authentication")
        self.assertNotIn("SECRET_SENTINEL", json.dumps(report))

    def test_config_environment_missing_malformed_identity_and_yaml(self):
        original = self.args.config.read_text(encoding="utf-8")
        self.args.config.write_text(original.replace("SECRET_SENTINEL", "${DIAGNOSTIC_MISSING_SECRET}"),
                                    encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True), patch.object(diag, "authenticate", side_effect=AssertionError("auth")):
            with self.assertRaisesRegex(diag.DiagnosticError, "missing_graph_environment"):
                diag.remote_report(self.args, {}, TENANT, self.schema)
        self.args.config.write_text(original.replace(CLIENT, "invalid-client"), encoding="utf-8")
        with self.assertRaisesRegex(diag.DiagnosticError, "invalid_azure_identity"):
            diag.graph_credentials(self.args.config, TENANT, "fixture")
        self.args.config.write_text("azure: [", encoding="utf-8")
        with self.assertRaisesRegex(diag.DiagnosticError, "invalid_graph_configuration"):
            diag.graph_credentials(self.args.config, TENANT, "fixture")

    def test_source_cache_settings_delivery_and_markers(self):
        original = self.collect()
        cik, accession, filename = diag.parse_scope(diag.SCOPES[0])
        (self.args.downloads / cik / accession.replace("-", "") / filename).write_text("changed", encoding="utf-8")
        payload = copy.deepcopy(self.payload)
        payload["content"]["value"] += " [rotated text] ![chart](missing.gif)"
        self.mutate("UPDATE chunks SET payload=? WHERE chunk_id='example0'", (json.dumps(payload),))
        report = self.collect()
        document = report["local"]["documents"][0]
        self.assertFalse(document["source_fingerprint_matches"])
        self.assertFalse(document["cache_payloads_match"])
        self.assertFalse(document["items"][0]["delivered_hash_matches"])
        self.assertEqual(document["items"][0]["evidence"]["missing_image_markers"], 1)
        diff = diag.compare_reports(original, report)
        self.assertTrue(diff["categories"]["input"]["changed"])
        self.assertTrue(diff["categories"]["payload"]["changed"])
        self.assertTrue(diff["categories"]["delivery"]["changed"])
        self.assertFalse(diff["categories"]["runtime"]["changed"])

    def test_sample_and_missing_documents_are_findings_not_pass(self):
        self.mutate("UPDATE filings SET sample_limit=5, state='sampled' WHERE id=0")
        self.mutate("DELETE FROM documents WHERE filing_id=1")
        report = self.collect()
        self.assertTrue(report["findings"])
        self.assertIsNone(report["local"]["documents"][0]["source_fingerprint_matches"])
        self.assertIn("document_not_found", report["local"]["documents"][1]["issues"])

    def test_missing_filing_and_corrupt_payload_are_explicit(self):
        self.mutate("DELETE FROM filings WHERE id=0")
        self.assertIn("filing_not_found", self.collect()["local"]["documents"][0]["issues"])
        self.mutate("UPDATE chunks SET payload='[]' WHERE filing_id=1")
        self.assertEqual(self.cli(), 2)
        self.assertEqual(diag.load_json(self.args.out)["error"], "invalid_stored_payload")

    def test_missing_processing_options_do_not_claim_runtime_match(self):
        self.mutate("UPDATE filings SET processing_options='{}'")
        doc = self.collect()["local"]["documents"][0]
        self.assertIsNone(doc["stored_version_matches_runtime"])
        self.assertIsNone(doc["stored_schema_matches_runtime"])
        self.assertIn("stored_runtime_drift_or_unknown", doc["issues"])

    def test_stale_deliveries_and_unparsed_inventory_are_findings(self):
        self.mutate("INSERT INTO delivered_items VALUES ('old-id',0,?)", (diag.digest("old"),))
        self.mutate("UPDATE documents SET state='failed' WHERE filing_id=0")
        doc = self.collect()["local"]["documents"][0]
        self.assertEqual(doc["stale_delivered_count"], 1)
        self.assertIn("filing_not_fully_reconciled", doc["issues"])
        self.assertIn("document_inventory_not_fully_parsed", doc["issues"])

    def test_payload_id_corruption_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload["id"] = "wrong"
        self.mutate("UPDATE chunks SET payload=? WHERE chunk_id='example0'", (json.dumps(payload),))
        with self.assertRaisesRegex(diag.DiagnosticError, "invalid_stored_payload"):
            self.collect()

    def test_redaction_provenance_errors_and_raw_payloads(self):
        distribution = unittest.mock.Mock(version="1.0")
        distribution.read_text.return_value = '{"url":"file:///PRIVATE_PATH/SECRET_SENTINEL"}'
        with patch.object(diag.importlib.metadata, "distribution", return_value=distribution):
            report = self.collect()
        text = json.dumps(report)
        for forbidden in ("SECRET_SENTINEL", "PRIVATE_PATH", str(self.root), "Peer group", "in billions"):
            self.assertNotIn(forbidden, text)
        with patch.object(diag, "runtime_info", side_effect=OSError("SECRET_SENTINEL")):
            self.assertEqual(self.cli(), 2)
        self.assertNotIn("SECRET_SENTINEL", self.args.out.read_text())

    def test_optional_runtime_modules_detect_backend_and_maintenance_drift(self):
        root = self.root / "synthetic-code"
        root.mkdir()
        for source in self.args.code_root.glob("*.py"):
            (root / source.name).write_bytes(source.read_bytes())
        backend = root / "ocr_engine.py"
        backend.write_text('OCR_ARGS = ["--psm", "7"]\n', encoding="utf-8")
        before = diag.runtime_info(root, self.schema)
        backend.write_text('OCR_ARGS = ["--psm", "6"]\n', encoding="utf-8")
        after = diag.runtime_info(root, self.schema)
        self.assertNotEqual(before, after)
        self.assertNotEqual(before["code_sha256"]["ocr_engine.py"], after["code_sha256"]["ocr_engine.py"])
        report = self.collect()
        changed = copy.deepcopy(report)
        report["runtime"], changed["runtime"] = before, after
        self.assertTrue(diag.compare_reports(report, changed)["categories"]["runtime"]["changed"])
        for name in ("maintenance.py", "maintenance_ocr.py"):
            module = root / name
            module.write_text("PLAN_FORMAT = 3\n", encoding="utf-8")
            before = diag.runtime_info(root, self.schema)
            module.write_text("PLAN_FORMAT = 4\n", encoding="utf-8")
            after = diag.runtime_info(root, self.schema)
            self.assertNotEqual(before["code_sha256"][name], after["code_sha256"][name])

    def test_older_runtime_tree_reports_missing_optional_modules(self):
        root = self.root / "old-code"
        root.mkdir()
        (root / "pipeline.py").write_text("PROCESSING_VERSION = 3\n", encoding="utf-8")
        runtime = diag.runtime_info(root, self.schema)
        self.assertEqual(runtime["processing_version"], 3)
        for name in ("ocr_engine.py", "maintenance.py", "maintenance_ocr.py"):
            self.assertIn(name, runtime["code_sha256"])
            self.assertIsNone(runtime["code_sha256"][name])
        with patch.object(diag.urllib.request, "build_opener", side_effect=AssertionError("network")):
            local, _, _ = diag.read_local(self.args, runtime)
        self.assertEqual(len(local["documents"]), 2)
        self.assertFalse(local["documents"][0]["stored_version_matches_runtime"])

    def test_output_rejected_before_any_input_or_auth(self):
        for out in (self.args.db, self.args.config, self.args.schema,
                    self.args.downloads / "new.json", self.args.db.parent / "new.json"):
            with self.subTest(out=out), patch.object(diag, "collect", side_effect=AssertionError("input")):
                self.assertEqual(self.cli(out=out), 2)
        self.args.out.write_text("untouched", encoding="utf-8")
        self.assertEqual(self.cli(), 2)
        self.assertEqual(self.args.out.read_text(), "untouched")

    def test_output_conflicting_with_missing_input_and_exclusive_creation(self):
        self.args.db = self.args.out
        self.assertEqual(self.cli(), 2)
        self.assertFalse(self.args.db.exists())
        args = argparse.Namespace(out=self.root / "private" / "race.json")
        with diag.reserve_output(args) as stream:
            stream.write("{}")
        with self.assertRaises(diag.DiagnosticError):
            diag.reserve_output(args)
        if os.name != "nt":
            self.assertEqual(args.out.stat().st_mode & 0o777, 0o600)

    def test_write_close_and_interruption_errors_are_redacted(self):
        stream = unittest.mock.MagicMock()
        stream.__enter__.return_value = stream
        stream.fileno.return_value = 1
        stream.__exit__.side_effect = OSError("SECRET_SENTINEL")
        with patch.object(diag, "reserve_output", return_value=stream), patch.object(diag.os, "fsync"):
            self.assertEqual(self.cli(), 2)
        with patch.object(diag, "collect", side_effect=KeyboardInterrupt):
            self.assertEqual(self.cli(), 2)
        self.assertEqual(diag.load_json(self.args.out)["error"], "interrupted")

    def test_exact_scope_validation(self):
        for scope in ("713676:0001193125-25-052937:x.htm", "0000713676:0001193125-25-052937:../x.htm",
                      "0000713676:0001193125-25-052937:x.pdf"):
            with self.assertRaises(diag.DiagnosticError):
                diag.parse_scope(scope)
        self.assertEqual(self.cli(["--scope", diag.SCOPES[0], "--scope", diag.SCOPES[0]]), 2)

    def test_single_scope_does_not_scan_other_filing_payload(self):
        self.mutate("UPDATE chunks SET payload='not json' WHERE filing_id=1")
        self.args.scope = [diag.SCOPES[0]]
        self.assertFalse(self.collect()["findings"])

    def test_schema_equivalent_order_and_flags_but_real_drift(self):
        schema = {"baseType": "microsoft.graph.externalItem", "properties": [
            {"name": "A", "type": "String", "labels": ["title", "url"], "aliases": ["a", "b"]},
            {"name": "B", "type": "Boolean"},
        ]}
        equivalent = copy.deepcopy(schema)
        equivalent["properties"].reverse()
        equivalent["properties"][1]["labels"].reverse()
        equivalent["properties"][1]["aliases"].reverse()
        equivalent["properties"][1]["isQueryable"] = False
        self.assertEqual(diag.normalize_schema(schema), diag.normalize_schema(equivalent))
        equivalent["properties"][1]["isRefinable"] = True
        self.assertNotEqual(diag.normalize_schema(schema), diag.normalize_schema(equivalent))
        schema["properties"].append(schema["properties"][0])
        with self.assertRaises(diag.DiagnosticError):
            diag.normalize_schema(schema)

    def test_item_acl_order_extra_properties_and_substantive_changes(self):
        expected = copy.deepcopy(self.payload)
        expected["acl"].append({"type": "group", "value": "group", "accessType": "grant"})
        actual = copy.deepcopy(expected)
        actual["acl"].reverse()
        actual["properties"]["serviceAdded"] = True
        result = diag.compare_remote(expected, actual)
        self.assertTrue(result["acl_matches"])
        self.assertTrue(result["expected_properties_match"])
        self.assertEqual(result["extra_property_names"], ["serviceAdded"])
        actual["content"]["value"] = "different"
        self.assertFalse(diag.compare_remote(expected, actual)["content_matches"])

    def test_remote_property_type_drift_is_reported(self):
        for expected, actual in (
            (1, True), (0, False), (1, 1.0), ("1", 1),
            ({"nested": [1, {"flag": False}]}, {"nested": [True, {"flag": 0}]}),
            ([{"count": 1}], [{"count": 1.0}]),
        ):
            with self.subTest(expected=expected, actual=actual):
                payload = copy.deepcopy(self.payload)
                payload["properties"]["ChunkOrdinal"] = expected
                receipts = self.receipts()
                receipts[2]["data"] = copy.deepcopy(payload)
                receipts[2]["data"]["properties"]["ChunkOrdinal"] = actual
                report = self.remote(receipts, {"example0": payload})
                self.assertFalse(report["items"][0]["expected_properties_match"])
                self.assertIn("remote_item_drift", report["issues"])

    def test_canonical_remote_content_acl_and_object_order(self):
        expected = copy.deepcopy(self.payload)
        expected["properties"]["nested"] = {"b": [1, True, None], "a": {"count": 2}}
        expected["acl"].append({"type": "group", "value": "group", "accessType": "grant"})
        actual = copy.deepcopy(expected)
        actual["properties"]["nested"] = {"a": {"count": 2}, "b": [1, True, None]}
        actual["acl"].reverse()
        result = diag.compare_remote(expected, actual)
        self.assertTrue(result["expected_properties_match"])
        self.assertTrue(result["acl_matches"])
        # Unknown nested fields must retain types too; only ACL entry order is irrelevant.
        expected["acl"][0]["extension"] = {"count": 1}
        actual["acl"][1]["extension"] = {"count": True}
        self.assertFalse(diag.compare_remote(expected, actual)["acl_matches"])
        expected["content"]["extension"] = {"value": 1}
        actual["content"]["extension"] = {"value": True}
        self.assertFalse(diag.compare_remote(expected, actual)["content_matches"])

    def remote(self, receipts, selected=None):
        if selected is None:
            selected = {"example0": self.payload}
        with patch.object(diag, "authenticate", return_value="FAKE_TOKEN"), \
                patch.object(diag, "graph_get", side_effect=receipts) as get:
            report = diag.remote_report(self.args, selected, TENANT, self.schema)
        self.assertTrue(all(call.args[0].startswith("/external/connections/fixture") for call in get.call_args_list))
        return report

    def receipts(self):
        return [{"status": 200, "data": {"id": "fixture", "state": "ready"}},
                {"status": 200, "data": copy.deepcopy(self.schema)},
                {"status": 200, "data": copy.deepcopy(self.payload)}]

    def test_graph_receipts_and_schema_fingerprint(self):
        report = self.remote(self.receipts())
        self.assertEqual(report["status"], "complete")
        self.assertTrue(report["schema"]["matches_selected_schema"])
        receipts = self.receipts()
        receipts[1]["data"]["properties"].reverse()
        self.assertEqual(report, self.remote(receipts))
        receipts = self.receipts()
        receipts[1]["data"]["properties"][0]["isRefinable"] = True
        self.assertIn("remote_schema_drift", self.remote(receipts)["issues"])

    def test_graph_partial_http_and_shape_errors_are_not_pass(self):
        for status in (403, 404, 302, 429, 500, None):
            receipts = self.receipts()
            receipts[2] = {"status": status, "error": "http_error"}
            report = self.remote(receipts)
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["items"][0]["status"], status)
        receipts = self.receipts()
        receipts[0] = {"status": 403, "error": "http_error"}
        report = self.remote(receipts)
        self.assertEqual(report["connection"]["status"], 403)
        self.assertFalse(report["items"])
        receipts = self.receipts()
        receipts[2]["data"] = {"properties": None}
        self.assertEqual(self.remote(receipts)["status"], "incomplete")

    def test_graph_empty_truncated_and_missing_scope_samples(self):
        self.assertEqual(self.remote(self.receipts()[:2], {})["status"], "incomplete")
        selected = {}
        for index in range(diag.MAX_ITEMS + 1):
            payload = copy.deepcopy(self.payload)
            payload["id"] = str(index)
            selected[payload["id"]] = payload
        receipts = self.receipts()[:2] + [
            {"status": 200, "data": selected[key]} for key in sorted(selected)[:diag.MAX_ITEMS]]
        report = self.remote(receipts, selected)
        self.assertTrue(report["truncated"])
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(len(report["items"]), diag.MAX_ITEMS)
        self.args.graph = True
        self.mutate("DELETE FROM filings WHERE id=1")
        with patch.object(diag, "authenticate", return_value="FAKE_TOKEN"), \
                patch.object(diag, "graph_get", side_effect=self.receipts()):
            report = diag.collect(self.args, {})
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("scope_without_evidence_candidates", report["graph"]["issues"])

    def test_graph_http_get_only_redirect_disabled_retry_bounded(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"id":"example0"}'
        with patch.object(diag.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = response
            self.assertEqual(diag.graph_get("/external/connections/fixture", "FAKE_TOKEN")["status"], 200)
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.data)
            self.assertIs(build.call_args.args[0], diag.NoRedirect)
            self.assertIsNone(diag.NoRedirect().redirect_request(request, None, 302, "", {}, "https://elsewhere"))
        with patch.object(diag.urllib.request, "build_opener") as build, patch.object(diag.time, "sleep"):
            build.return_value.open.side_effect = [
                urllib.error.HTTPError("redacted", 429, "SECRET_SENTINEL", {"Retry-After": "0"}, io.BytesIO())
                for _ in range(3)]
            receipt = diag.graph_get("/external/connections/fixture", "FAKE_TOKEN")
            self.assertEqual(build.return_value.open.call_count, 3)
            self.assertEqual(receipt["status"], 429)
            self.assertNotIn("SECRET_SENTINEL", json.dumps(receipt))

    def test_graph_transport_invalid_json_and_oversized_response(self):
        for failure in (urllib.error.URLError("SECRET_SENTINEL"), TimeoutError("SECRET_SENTINEL")):
            with patch.object(diag.urllib.request, "build_opener") as build:
                build.return_value.open.side_effect = failure
                self.assertEqual(diag.graph_get("/external/connections/fixture", "token")["error"], "transport_error")
        with patch.object(diag.urllib.request, "build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.status = 200
            for content, expected in ((b"bad", "invalid_response_json"), (b"[]", "invalid_response_shape")):
                response.read.return_value = content
                self.assertEqual(diag.graph_get("/external/connections/fixture", "token")["error"], expected)
            response.read.return_value = b"12345"
            with patch.object(diag, "MAX_RESPONSE_BYTES", 4):
                self.assertEqual(diag.graph_get("/external/connections/fixture", "token")["error"], "response_too_large")

    def test_compare_reordered_reports_settings_runtime_and_delivery_drift(self):
        before = self.collect()
        after = copy.deepcopy(before)
        after["created_at"] = "another time"
        after["local"]["documents"].reverse()
        self.assertFalse(diag.compare_reports(before, after)["differences"])
        after["runtime"]["processing_version"] += 1
        after["local"]["documents"][0]["options_sha256"] = diag.digest({"changed": True})
        after["local"]["documents"][0]["items"][0]["delivered_hash_matches"] = False
        result = diag.compare_reports(before, after)
        for category in ("runtime", "settings", "delivery"):
            self.assertTrue(result["categories"][category]["changed"])
        self.assertFalse(result["categories"]["payload"]["changed"])

    def test_compare_partial_error_unsupported_and_duplicate_reports(self):
        before = self.collect()
        after = copy.deepcopy(before)
        after["status"] = "incomplete"
        self.assertEqual(diag.compare_reports(before, after)["status"], "incomplete")
        after["report_version"] = 999
        with self.assertRaises(diag.DiagnosticError):
            diag.compare_reports(before, after)
        after = copy.deepcopy(before)
        after["local"]["documents"].append(after["local"]["documents"][0])
        with self.assertRaises(diag.DiagnosticError):
            diag.compare_reports(before, after)
        with self.assertRaises(diag.DiagnosticError):
            diag.compare_reports(before, {"kind": "collection", "error": "incomplete"})

    def test_compare_inconsistent_graph_summary_cannot_mask_partial_receipts(self):
        before = self.collect()
        after = copy.deepcopy(before)
        after["graph"] = {"status": "complete", "items": [], "truncated": False,
                          "candidate_count": 2, "selected_count": 2}
        self.assertEqual(diag.compare_reports(after, after)["status"], "incomplete")
        after = copy.deepcopy(before)
        after["error"] = "interrupted"
        self.assertEqual(diag.compare_reports(after, after)["status"], "incomplete")

    def test_cli_offline_comparison_and_findings_exit_codes(self):
        self.assertEqual(self.cli(), 0)
        second = self.args.out.with_name("second.json")
        self.assertEqual(self.cli(out=second), 0)
        comparison = self.args.out.with_name("comparison.json")
        argv = ["compare", "--before", str(self.args.out), "--after", str(second), "--out", str(comparison)]
        with patch.object(diag, "authenticate", side_effect=AssertionError("auth")), redirect_stdout(io.StringIO()):
            self.assertEqual(diag.main(argv), 0)
        self.assertFalse(diag.load_json(comparison)["differences"])
        self.mutate("UPDATE chunks SET state='failed'")
        findings = self.args.out.with_name("findings.json")
        self.assertEqual(self.cli(out=findings), 1)
        argv[2], argv[4], argv[6] = str(findings), str(findings), str(comparison.with_name("same-findings.json"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(diag.main(argv), 1)

    def test_standalone_runs_stdlib_only_no_connector_imports(self):
        script = ROOT / "src" / "sec_connector" / "diagnostics.py"
        code = """
import runpy, sys
sys.argv = [sys.argv[1], '--help']
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except SystemExit as exc:
    assert exc.code == 0
assert not any(name.startswith(('sec_connector', 'msal', 'yaml', 'aiohttp')) for name in sys.modules)
"""
        result = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(script)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        spec = importlib.util.spec_from_file_location("standalone_diagnostics", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.payload_digest(self.payload), diag.payload_digest(self.payload))
        result = subprocess.run([
            sys.executable, "-I", "-S", str(script), "collect", "--db", str(self.args.db),
            "--downloads", str(self.args.downloads), "--code-root", str(self.args.code_root),
            "--schema", str(self.args.schema), "--connection-id", "fixture", "--out", str(self.args.out),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(diag.load_json(self.args.out)["findings"])

    def test_actual_production_serialization_and_fingerprint_contracts_without_imports(self):
        # Execute only the pure functions' ASTs, never the modules' initialization.
        def pure_functions(filename, names, namespace):
            tree = ast.parse((self.args.code_root / filename).read_text(encoding="utf-8"))
            nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
            self.assertEqual({node.name for node in nodes}, set(names))
            for node in nodes:
                node.returns = None
                for arg in node.args.args:
                    arg.annotation = None
            exec(compile(ast.Module(body=nodes, type_ignores=[]), "<pure-production-contract>", "exec"), namespace)
            return namespace

        namespace = pure_functions("payloads.py", ("serialize_item", "payload_hash"),
                                   {"json": json, "hashlib": hashlib})
        payload = copy.deepcopy(self.payload)
        payload["content"]["value"] += " \u00e9 \u20ac"
        self.assertEqual(namespace["payload_hash"](payload), diag.payload_digest(payload))
        namespace = pure_functions("maintenance.py", ("canonical", "same_payload"), {"json": json})
        for expected, actual in ((1, True), (0, False), (1, 1.0), ({"a": [1]}, {"a": [True]}),
                                 ({"a": 1, "b": [True]}, {"b": [True], "a": 1})):
            self.assertEqual(namespace["same_payload"](actual, expected),
                             diag.canonical(actual) == diag.canonical(expected))
        namespace = pure_functions("pipeline.py", ("document_fingerprint",),
                                   {"json": json, "hashlib": hashlib})
        with closing(sqlite3.connect(self.args.db)) as db:
            options, metadata = db.execute("SELECT processing_options,metadata FROM filings WHERE id=0").fetchone()
            document, = db.execute("SELECT metadata FROM documents WHERE filing_id=0").fetchone()
            cached, = db.execute("SELECT fingerprint FROM document_cache WHERE filing_id=0").fetchone()
        cik, accession, filename = diag.parse_scope(diag.SCOPES[0])
        source = self.args.downloads / cik / accession.replace("-", "") / filename
        filing_model = unittest.mock.Mock()
        filing_model.model_dump.return_value = json.loads(metadata)
        document_model = unittest.mock.Mock()
        document_model.model_dump.return_value = json.loads(document)
        self.assertEqual(namespace["document_fingerprint"](
            diag.file_digest(source), filing_model, document_model, json.loads(options)), cached)
        self.assertTrue(self.collect()["local"]["documents"][0]["source_fingerprint_matches"])


if __name__ == "__main__":
    unittest.main()
