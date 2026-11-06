"""End-to-end HTTP tests, including direct API attacks on restricted evidence."""

import base64
import copy
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest

from backend.server import create_server
from backend.workspace import Workspace


PASSWORDS = {"analyst": "AnalystDemo!2026", "manager": "ManagerDemo!2026"}


class FullWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory()
        self.server = create_server(0, data_dir=self.runtime.name)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.cookies = {}
        for username in PASSWORDS:
            status, _, response = self.call(None, "POST", "/api/login", {
                "username": username, "password": PASSWORDS[username]})
            self.assertEqual(status, 200)
            self.cookies[username] = response.getheader("Set-Cookie").split(";", 1)[0]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.runtime.cleanup()

    def call(self, user, method, path, payload=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        request_headers = {"Content-Type": "application/json"}
        if user:
            request_headers["Cookie"] = self.cookies[user]
        request_headers.update(headers or {})
        connection.request(method, path, body=json.dumps(payload) if payload is not None else None,
                           headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw) if raw else None, response

    def demo(self, user="analyst"):
        status, payload, _ = self.call(user, "GET", "/api/demo")
        self.assertEqual(status, 200)
        return payload["documents"]

    def analyze(self, user="analyst", task="brief", documents=None):
        docs = documents if documents is not None else self.demo(user)
        return self.call(user, "POST", "/api/analysis", {
            "task": task, "document_ids": [d["document_id"] for d in docs],
            "requirements": ["audit records", "quantum encryption"]})

    def test_complete_brief_audit_approve_reject_and_trail(self):
        docs = self.demo()
        status, run, _ = self.analyze(documents=docs)
        self.assertEqual(status, 200)
        self.assertEqual(run["mode"], "deterministic_demo")
        self.assertEqual(run["audit"]["status"], "passed")
        lookup = {doc["document_id"]: doc for doc in docs}
        for claim in run["claims"]:
            for citation in claim["citations"]:
                source = lookup[citation["document_id"]]["lines"][citation["line_start"] - 1]["text"]
                self.assertEqual(source, claim["text"])
                self.assertEqual(source, citation["quote"])
        route = "/api/analysis/" + run["analysis_id"]
        for decision in ("approve", "reject"):
            status, reviewed, _ = self.call("manager", "POST", route + "/review", {
                "decision": decision, "comment": "Synthetic demo review: " + decision})
            self.assertEqual(status, 200)
            self.assertEqual(reviewed["audit"]["status"], "passed")
            self.assertEqual(reviewed["review"]["status"], "approved" if decision == "approve" else "rejected")
        status, trail, _ = self.call("analyst", "GET", route + "/audit")
        self.assertEqual(status, 200)
        self.assertEqual([e["event"] for e in trail["events"]], ["analysis_audited", "human_review", "human_review"])
        log = Path(self.runtime.name, "audit.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("FICTIONAL", log)
        self.assertNotIn("Synthetic demo review", log)
        self.assertNotIn("password", log)
        self.assertEqual(len(log.splitlines()), 3)

    def test_requirements_conflict_and_missing_evidence(self):
        status, run, _ = self.analyze(task="requirements")
        self.assertEqual(status, 200)
        self.assertEqual(run["audit"]["status"], "passed")
        self.assertEqual([c["line_start"] for c in run["contradictions"][0]["citations"]], [9, 8])
        self.assertEqual(run["requirement_checks"][1]["citations"], [])
        self.assertEqual(run["requirement_checks"][1]["status"], "unclear")

    def test_direct_restricted_retrieval_analysis_and_spoofed_metadata_are_denied(self):
        docs = self.demo("manager")
        restricted = next(d for d in docs if d["access"] == "restricted")
        identifier = restricted["document_id"]
        snapshot = copy.deepcopy(restricted)
        snapshot.update(access="public", allowed_roles=["analyst", "manager"])
        attempts = [
            ("GET", "/api/documents/" + identifier, None),
            ("POST", "/api/analysis", {"task": "brief", "document_ids": [identifier], "role": "manager"}),
            ("POST", "/api/analysis", {"task": "brief", "documents": [snapshot], "role": "manager"}),
        ]
        for method, route, payload in attempts:
            with self.subTest(route=route, payload=payload):
                status, error, _ = self.call("analyst", method, route, payload, {"X-Role": "manager"})
                self.assertEqual(status, 403)
                self.assertEqual(error["error"]["code"], "access_denied")
                self.assertNotIn("CEDAR-DEMO-742", repr(error))
                self.assertNotIn("4200", repr(error))
        self.assertEqual(len(self.demo()), 3)
        status, listing, _ = self.call("analyst", "GET", "/api/documents?role=manager")
        self.assertEqual(status, 200)
        self.assertNotIn(identifier, repr(listing))
        self.assertNotIn("CEDAR-DEMO-742", repr(listing))

    def test_restricted_results_and_audit_events_cannot_be_retrieved_by_analyst(self):
        restricted = [d for d in self.demo("manager") if d["access"] == "restricted"]
        status, run, _ = self.analyze("manager", documents=restricted)
        self.assertEqual(status, 200)
        self.assertIn("CEDAR-DEMO-742", repr(run))
        route = "/api/analysis/" + run["analysis_id"]
        for suffix in ("", "/audit"):
            status, error, _ = self.call("analyst", "GET", route + suffix)
            self.assertEqual(status, 403)
            self.assertNotIn("CEDAR-DEMO-742", repr(error))
        _, listing, _ = self.call("analyst", "GET", "/api/analyses")
        self.assertNotIn(run["analysis_id"], repr(listing))

    def test_anonymous_and_fake_session_cannot_access_document_routes(self):
        for method, route, payload in (("GET", "/api/demo", None), ("GET", "/api/documents", None),
                                       ("POST", "/api/analysis", {"task": "brief", "document_ids": []}),
                                       ("POST", "/api/documents", {"files": []})):
            status, _, _ = self.call(None, method, route, payload)
            self.assertEqual(status, 401)
        status, _, _ = self.call(None, "GET", "/api/demo", headers={"Cookie": "icontinuum_session=fake", "X-Role": "manager"})
        self.assertEqual(status, 401)

    def test_logout_and_session_expiry_revoke_access(self):
        status, _, response = self.call("analyst", "POST", "/api/logout", {})
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0", response.getheader("Set-Cookie"))
        self.assertEqual(self.call("analyst", "GET", "/api/demo")[0], 401)
        token = self.cookies["manager"].split("=", 1)[1]
        self.server.workspace.sessions[token]["expires"] = 0
        self.assertEqual(self.call("manager", "GET", "/api/demo")[0], 401)

    def test_wrong_password_does_not_grant_a_session(self):
        status, _, response = self.call(None, "POST", "/api/login", {"username": "manager", "password": "wrong", "role": "manager"})
        self.assertEqual(status, 401)
        self.assertIsNone(response.getheader("Set-Cookie"))

    def test_analyst_cannot_review_and_flagged_results_cannot_be_approved(self):
        _, run, _ = self.analyze()
        route = "/api/analysis/" + run["analysis_id"] + "/review"
        payload = {"decision": "approve", "comment": "Reviewed."}
        self.assertEqual(self.call("analyst", "POST", route, payload)[0], 403)
        self.server.workspace.runs[run["analysis_id"]]["result"]["audit"]["status"] = "flagged"
        self.assertEqual(self.call("manager", "POST", route, payload)[0], 409)
        payload["decision"] = "reject"
        self.assertEqual(self.call("manager", "POST", route, payload)[0], 200)

    def test_uploaded_restricted_evidence_is_server_enforced(self):
        file = {"file_name": "restricted-upload.txt", "content_base64": base64.b64encode(b"FICTIONAL secret upload 5199\n").decode()}
        payload = {"files": [file], "access": "restricted"}
        self.assertEqual(self.call("analyst", "POST", "/api/documents", payload)[0], 403)
        status, uploaded, _ = self.call("manager", "POST", "/api/documents", payload)
        self.assertEqual(status, 200)
        doc = uploaded["documents"][0]
        self.assertEqual(self.call("analyst", "GET", "/api/documents/" + doc["document_id"])[0], 403)
        # Uploading identical known bytes cannot change an existing ACL.
        payload["access"] = "public"
        self.assertEqual(self.call("analyst", "POST", "/api/documents", payload)[0], 403)

    def test_client_cannot_replace_canonical_source_text(self):
        doc = self.demo()[0]
        doc["text"] = "Invented evidence."
        status, error, _ = self.call("analyst", "POST", "/api/analysis", {"task": "brief", "documents": [doc]})
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "modified_evidence")

    def test_sample_manifest_can_be_swapped_without_code_changes(self):
        folder = Path(self.runtime.name) / "other_samples"
        folder.mkdir()
        (folder / "custom.txt").write_bytes(b"FICTIONAL custom evidence.\r\n\r\nThird line.\n")
        (folder / "manifest.json").write_text(json.dumps({"documents": [
            {"path": "custom.txt", "allowed_roles": ["manager"]}]}), encoding="utf-8")
        workspace = Workspace(folder, self.runtime.name)
        self.assertEqual(workspace.list_documents({"username": "analyst", "role": "analyst"}), [])
        documents = workspace.list_documents({"username": "manager", "role": "manager"})
        self.assertEqual(documents[0]["line_count"], 3)
        self.assertEqual(documents[0]["lines"][1]["text"], "")

    def test_manifest_path_escape_is_rejected(self):
        folder = Path(self.runtime.name) / "bad_samples"
        folder.mkdir()
        (folder / "manifest.json").write_text(json.dumps({"documents": [
            {"path": "../outside.txt", "allowed_roles": ["manager"]}]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            Workspace(folder, self.runtime.name)

    def test_second_server_cannot_silently_reuse_the_demo_port(self):
        with self.assertRaises(OSError):
            create_server(self.server.server_address[1], data_dir=self.runtime.name)

    def test_restricted_sources_and_logs_are_not_static_assets(self):
        for route in ("/sample_documents/restricted/manager_notes.txt", "/.runtime/audit.jsonl",
                      "/sample_documents/manifest.json", "/../sample_documents/restricted/manager_notes.txt"):
            with self.subTest(route=route):
                status, body, _ = self.call("analyst", "GET", route)
                self.assertEqual(status, 404)
                self.assertNotIn("CEDAR-DEMO-742", repr(body))

    def test_audit_log_survives_workspace_restart_without_restoring_sessions(self):
        self.assertEqual(self.analyze()[0], 200)
        log = self.server.workspace.log_path.read_text(encoding="utf-8")
        root = Path(__file__).resolve().parents[1] / "sample_documents"
        restarted = Workspace(root, self.runtime.name)
        self.assertEqual(restarted.log_path.read_text(encoding="utf-8"), log)
        self.assertEqual(restarted.sessions, {})
        self.assertEqual(restarted.runs, {})
