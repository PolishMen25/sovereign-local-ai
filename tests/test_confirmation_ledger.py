from pathlib import Path
import tempfile
import unittest

from services.orchestrator.confirmations import ConfirmationLedger, canonical_payload_sha256


class ConfirmationLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.ledger = ConfirmationLedger(Path(self.temporary.name) / "confirmations.sqlite3")
        self.ledger.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_proposal_requires_owner_and_is_consumed_once(self) -> None:
        digest = canonical_payload_sha256({"service": "approved-service"})
        proposal = self.ledger.propose(
            capability="service.restart_approved",
            target="approved-service",
            summary="Redémarrer le service approuvé",
            payload_sha256=digest,
        )
        confirmation = self.ledger.confirm(
            proposal["proposal_id"], owner="owner", expected_payload_sha256=digest
        )
        self.ledger.consume(
            proposal["proposal_id"],
            authorization=confirmation["authorization"],
            capability="service.restart_approved",
            target="approved-service",
            payload_sha256=digest,
        )
        with self.assertRaises(PermissionError):
            self.ledger.consume(
                proposal["proposal_id"],
                authorization=confirmation["authorization"],
                capability="service.restart_approved",
                target="approved-service",
                payload_sha256=digest,
            )

    def test_digest_drift_and_generic_shell_are_refused(self) -> None:
        digest = canonical_payload_sha256({"target": "one"})
        proposal = self.ledger.propose(
            capability="proxmox.status",
            target="cluster",
            summary="Lire l'état du cluster",
            payload_sha256=digest,
        )
        with self.assertRaises(PermissionError):
            self.ledger.confirm(proposal["proposal_id"], owner="owner", expected_payload_sha256="0" * 64)
        with self.assertRaises(ValueError):
            self.ledger.propose(
                capability="shell",
                target="cluster",
                summary="generic shell",
                payload_sha256=digest,
            )


if __name__ == "__main__":
    unittest.main()
