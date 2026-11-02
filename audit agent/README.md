The Audit Agent implementation is `mesh/agents.py:AuditAgent`.
It validates citations against authorized passages and rejects unsupported extracts.
The workflow returns an audit event; persistent storage must be added by the backend.
