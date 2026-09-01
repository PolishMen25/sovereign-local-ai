import argparse
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
from io import StringIO
import json
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests._temp_support import sovereign_temporary_directory
from services.inference.tokenizer import (
    ByteBpeTokenizer,
    experimental_tokenizer_document,
    train_byte_bpe,
)
from services.inference.checkpoint import (
    CompatibilityError,
    validate_model_gradients_finite,
)
from tools.authorized_text_bundle import AuthorizedTextBundle, AuthorizedTextRecord
from tools.train_core_mini import (
    DATA_MODE_AUTHORIZED_TEXT,
    DATA_MODE_SYNTHETIC,
    MAXIMUM_RESUME_CHECKPOINT_BYTES,
    append_authorized_metric,
    authorized_metrics_binding_from_checkpoint,
    authorized_text_token_rows,
    calculate_final_step,
    checkpoint_public_result,
    load_and_validate_document,
    load_resume_checkpoint,
    load_resume_checkpoint_with_digest,
    load_resume_state_strict,
    load_training_bundle,
    main,
    hash_authorized_metrics_journal,
    open_authorized_metrics_journal,
    save_checkpoint,
    synthetic_token_rows,
    training_contract,
    training_contract_sha256,
    training_metric_record,
    training_run_metadata,
    validate_authorized_metrics_payload,
    validate_resume_checkpoint_document,
    validate_run_limits,
)


def authorized_bundle(*texts: str, vocabulary_size: int = 264) -> AuthorizedTextBundle:
    result = train_byte_bpe(
        ["bonjour bonjour bonjour", *texts], vocabulary_size
    )
    tokenizer_document = experimental_tokenizer_document(
        training_corpus_id="corpus-approved-training",
        training_corpus_sha256="b" * 64,
        result=result,
        minimum_frequency=2,
    )
    return AuthorizedTextBundle(
        corpus_id="corpus-approved-training",
        manifest_schema_version="0.2.0",
        manifest_sha256="a" * 64,
        train_sha256="b" * 64,
        train_byte_size=123,
        train_record_count=len(texts),
        tokenizer_sha256="c" * 64,
        tokenizer_schema_version="0.2.0",
        tokenizer_status="experimental",
        tokenizer_vocabulary_size=result.vocabulary_size,
        normalization_policy_id="unicode-nfc-v1",
        records=tuple(
            AuthorizedTextRecord(record_id=f"record-{index}", text=text)
            for index, text in enumerate(texts)
        ),
        tokenizer=ByteBpeTokenizer.from_document(tokenizer_document),
    )


class ResumeTensor:
    def __init__(
        self,
        shape=(2,),
        *,
        dtype="float32",
        device="cpu",
        layout="strided",
        item_value=1.0,
        finite=True,
        stride=None,
        storage_offset=0,
        storage_token=None,
        storage_bytes=None,
    ) -> None:
        self.shape = shape
        self.dtype = dtype
        self.device = SimpleNamespace(type=device)
        self.layout = layout
        self.item_value = item_value
        self.finite = finite
        self._stride = (
            tuple(stride)
            if stride is not None
            else (() if shape == () else (1,))
        )
        self._storage_offset = storage_offset
        self._storage_token = storage_token if storage_token is not None else object()
        self._storage_bytes = (
            storage_bytes
            if storage_bytes is not None
            else self.numel() * self.element_size()
        )

    def numel(self) -> int:
        return 1 if self.shape == () else 2

    def item(self):
        return self.item_value

    def stride(self):
        return self._stride

    def storage_offset(self):
        return self._storage_offset

    def element_size(self):
        return 4

    def untyped_storage(self):
        return SimpleNamespace(
            nbytes=lambda: self._storage_bytes,
            data_ptr=lambda: id(self._storage_token),
        )


class ResumeModel:
    def __init__(self) -> None:
        self.parameter = ResumeTensor()

    def state_dict(self):
        return {"weight": self.parameter}

    def load_state_dict(self, state, *, strict):
        if not strict:
            raise AssertionError("strict loading is required")
        return SimpleNamespace(missing_keys=[], unexpected_keys=[])

    def parameters(self):
        return iter([self.parameter])


class ResumeOptimizer:
    def __init__(self, parameter) -> None:
        self.parameter = parameter
        self.param_groups = [
            {"params": [parameter], "lr": 0.1, "amsgrad": False}
        ]
        self.state = {}

    def state_dict(self):
        serialized_state = {0: self.state[self.parameter]} if self.state else {}
        group = {
            "params": [0],
            "lr": self.param_groups[0]["lr"],
            "amsgrad": self.param_groups[0]["amsgrad"],
        }
        return {"state": serialized_state, "param_groups": [group]}

    def load_state_dict(self, state):
        received_group = state["param_groups"][0]
        self.param_groups = [
            {
                "params": [self.parameter],
                "lr": received_group["lr"],
                "amsgrad": received_group["amsgrad"],
            }
        ]
        self.state = {self.parameter: state["state"][0]}


RESUME_TORCH = SimpleNamespace(
    is_tensor=lambda value: isinstance(value, ResumeTensor),
    isfinite=lambda value: SimpleNamespace(
        all=lambda: SimpleNamespace(item=lambda: value.finite)
    ),
    float32="float32",
    strided="strided",
)


def resume_checkpoint(
    *, checkpoint_step: int = 3, optimizer_step: float = 3.0
) -> tuple[dict, ResumeModel, ResumeOptimizer]:
    model = ResumeModel()
    optimizer = ResumeOptimizer(model.parameter)
    checkpoint = {
        "step": checkpoint_step,
        "model": {"weight": ResumeTensor()},
        "optimizer": {
            "state": {
                0: {
                    "step": ResumeTensor(shape=(), item_value=optimizer_step),
                    "exp_avg": ResumeTensor(),
                    "exp_avg_sq": ResumeTensor(),
                }
            },
            "param_groups": [{"params": [0], "lr": 0.1, "amsgrad": False}],
        },
    }
    return checkpoint, model, optimizer


def authorized_contract(bundle: AuthorizedTextBundle) -> dict[str, object]:
    args = argparse.Namespace(
        learning_rate=3e-4,
        batch_size=1,
        sequence_length=8,
        seed=7,
        threads=1,
        data_mode=DATA_MODE_AUTHORIZED_TEXT,
    )
    return training_contract(
        args,
        "d" * 64,
        SimpleNamespace(__version__="2.13.0+cpu"),
        authorized_bundle=bundle,
    )


class CoreMiniHarnessTests(unittest.TestCase):
    CONFIG = (
        Path(__file__).parents[1]
        / "configs"
        / "models"
        / "core-mini.candidate.json"
    )
    BOUNDED_FIXTURE = Path(__file__).parent / "fixtures" / "checkpoint-loader-small.bin"

    def test_candidate_has_exact_parameter_count(self) -> None:
        document, _ = load_and_validate_document(self.CONFIG)
        self.assertEqual(document["parameter_count"]["total_trainable"], 1_328_256)

    def test_synthetic_rows_are_deterministic_and_bounded(self) -> None:
        first = synthetic_token_rows(
            step=3,
            batch_size=2,
            sequence_length=8,
            vocabulary_size=32,
            seed=7,
        )
        second = synthetic_token_rows(
            step=3,
            batch_size=2,
            sequence_length=8,
            vocabulary_size=32,
            seed=7,
        )
        self.assertEqual(first, second)
        self.assertEqual([len(row) for row in first], [9, 9])
        self.assertTrue(all(0 <= token < 32 for row in first for token in row))

    def test_run_limits_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "steps"):
            validate_run_limits(steps=0, batch_size=1, sequence_length=2)
        with self.assertRaisesRegex(ValueError, "batch_size"):
            validate_run_limits(steps=1, batch_size=0, sequence_length=2)
        with self.assertRaisesRegex(ValueError, "sequence_length"):
            validate_run_limits(steps=1, batch_size=1, sequence_length=1)
        with self.assertRaisesRegex(ValueError, "steps"):
            validate_run_limits(steps=True, batch_size=1, sequence_length=2)

    def test_training_contract_normalizes_torch_version_to_plain_string(self) -> None:
        class TorchVersion(str):
            pass

        args = SimpleNamespace(
            learning_rate=3e-4,
            batch_size=2,
            sequence_length=32,
            seed=7,
            threads=1,
        )
        torch = SimpleNamespace(__version__=TorchVersion("2.13.0+cpu"))

        contract = training_contract(args, "a" * 64, torch)

        self.assertIs(type(contract["torch"]), str)
        self.assertEqual(contract["torch"], "2.13.0+cpu")

    def test_historical_synthetic_contract_stays_compatible(self) -> None:
        args = argparse.Namespace(
            learning_rate=3e-4,
            batch_size=2,
            sequence_length=32,
            seed=7,
            threads=1,
            data_mode=DATA_MODE_SYNTHETIC,
        )
        contract = training_contract(
            args, "a" * 64, SimpleNamespace(__version__="2.13.0+cpu")
        )
        self.assertEqual(contract["schema_version"], "0.1.0")
        self.assertEqual(contract["synthetic_generator"], "arithmetic-v1")
        self.assertNotIn("data_mode", contract)
        self.assertNotIn("data_lineage", contract)

    def test_authorized_rows_are_deterministic_bounded_and_use_only_bundle_tokens(self) -> None:
        bundle = authorized_bundle("A", "Deuxième texte autorisé.")
        first = authorized_text_token_rows(
            bundle, step=3, batch_size=2, sequence_length=8, seed=7
        )
        second = authorized_text_token_rows(
            bundle, step=3, batch_size=2, sequence_length=8, seed=7
        )
        self.assertEqual(first, second)
        self.assertEqual([len(row) for row in first], [9, 9])
        self.assertTrue(
            all(
                0 <= token_id < bundle.tokenizer_vocabulary_size
                for row in first
                for token_id in row
            )
        )

    def test_authorized_contract_and_metrics_bind_content_free_lineage(self) -> None:
        bundle = authorized_bundle("Texte autorisé uniquement.")
        args = argparse.Namespace(
            learning_rate=3e-4,
            batch_size=1,
            sequence_length=8,
            seed=7,
            threads=1,
            data_mode=DATA_MODE_AUTHORIZED_TEXT,
        )
        contract = training_contract(
            args,
            "d" * 64,
            SimpleNamespace(__version__="2.13.0+cpu"),
            authorized_bundle=bundle,
        )
        metric = training_metric_record(
            step=1,
            loss=1.25,
            elapsed_seconds=0.5,
            tokens=8,
            authorized_bundle=bundle,
            training_contract_document=contract,
        )

        self.assertEqual(contract["data_mode"], DATA_MODE_AUTHORIZED_TEXT)
        self.assertEqual(contract["schema_version"], "0.2.0")
        self.assertEqual(contract["data_lineage"], bundle.lineage_contract())
        self.assertEqual(metric["data_lineage"], bundle.lineage_contract())
        self.assertEqual(
            metric["training_contract_sha256"], training_contract_sha256(contract)
        )
        serialized = json.dumps({"contract": contract, "metric": metric})
        self.assertNotIn("Texte autorisé", serialized)
        self.assertNotIn("record-", serialized)
        self.assertNotIn("path", serialized)
        self.assertNotIn("synthetic_generator", contract)

    def test_authorized_mode_is_explicit_complete_and_has_no_fallback(self) -> None:
        synthetic_with_path = argparse.Namespace(
            data_mode=DATA_MODE_SYNTHETIC,
            authorized_manifest=Path("manifest.json"),
            authorized_train_jsonl=None,
            authorized_tokenizer=None,
        )
        with self.assertRaisesRegex(ValueError, "forbidden"):
            load_training_bundle(synthetic_with_path, model_vocabulary_size=264)

        incomplete = argparse.Namespace(
            data_mode=DATA_MODE_AUTHORIZED_TEXT,
            authorized_manifest=Path("manifest.json"),
            authorized_train_jsonl=None,
            authorized_tokenizer=Path("tokenizer.json"),
        )
        with self.assertRaisesRegex(ValueError, "requires"):
            load_training_bundle(incomplete, model_vocabulary_size=264)

        bundle = authorized_bundle("Texte strict.")
        complete = argparse.Namespace(
            data_mode=DATA_MODE_AUTHORIZED_TEXT,
            authorized_manifest=Path("manifest.json"),
            authorized_train_jsonl=Path("train.jsonl"),
            authorized_tokenizer=Path("tokenizer.json"),
        )
        with patch(
            "tools.train_core_mini.load_authorized_text_bundle",
            return_value=bundle,
        ) as loader:
            loaded = load_training_bundle(
                complete, model_vocabulary_size=bundle.tokenizer_vocabulary_size
            )
        self.assertIs(loaded, bundle)
        loader.assert_called_once_with(
            manifest_path=Path("manifest.json"),
            train_jsonl_path=Path("train.jsonl"),
            tokenizer_path=Path("tokenizer.json"),
        )

        with patch(
            "tools.train_core_mini.load_authorized_text_bundle",
            return_value=bundle,
        ):
            with self.assertRaisesRegex(ValueError, "vocabulary"):
                load_training_bundle(
                    complete,
                    model_vocabulary_size=bundle.tokenizer_vocabulary_size + 1,
                )

    def test_authorized_contract_refuses_missing_validated_bundle(self) -> None:
        args = argparse.Namespace(
            learning_rate=3e-4,
            batch_size=1,
            sequence_length=8,
            seed=7,
            threads=1,
            data_mode=DATA_MODE_AUTHORIZED_TEXT,
        )
        with self.assertRaisesRegex(ValueError, "validated"):
            training_contract(
                args, "a" * 64, SimpleNamespace(__version__="2.13.0+cpu")
            )

    def test_resume_loader_is_bounded_cpu_only_and_weights_only(self) -> None:
        class Torch:
            kwargs = None
            loaded_from_path = None

            def load(self, source, **kwargs):
                self.kwargs = kwargs
                self.loaded_from_path = isinstance(source, (str, Path))
                self.loaded_bytes = None if self.loaded_from_path else source.read()
                return {"schema_version": "0.1.0"}

        torch = Torch()
        checkpoint = load_resume_checkpoint(torch, self.BOUNDED_FIXTURE)
        self.assertEqual(checkpoint, {"schema_version": "0.1.0"})
        self.assertEqual(
            torch.kwargs, {"map_location": "cpu", "weights_only": True}
        )
        self.assertFalse(torch.loaded_from_path)

        oversized = SimpleNamespace(
            st_mode=stat.S_IFREG,
            st_size=MAXIMUM_RESUME_CHECKPOINT_BYTES + 1,
        )
        with patch("tools.train_core_mini.os.fstat", return_value=oversized):
            with self.assertRaisesRegex(RuntimeError, "bounded"):
                load_resume_checkpoint(Torch(), self.BOUNDED_FIXTURE)

        digest_torch = Torch()
        loaded, digest = load_resume_checkpoint_with_digest(
            digest_torch, self.BOUNDED_FIXTURE
        )
        self.assertEqual(loaded, {"schema_version": "0.1.0"})
        self.assertEqual(
            digest, hashlib.sha256(self.BOUNDED_FIXTURE.read_bytes()).hexdigest()
        )
        self.assertEqual(digest_torch.loaded_bytes, self.BOUNDED_FIXTURE.read_bytes())

    def test_checkpoint_save_is_exclusive_durable_hashed_and_cleans_failure(self) -> None:
        class SaveTorch:
            def save(self, payload, destination):
                self.destination_is_path = isinstance(destination, (str, Path))
                destination.write(b"deterministic-checkpoint")

        class BrokenTorch:
            def save(self, payload, destination):
                destination.write(b"partial")
                raise OSError("C:/private/checkpoint.pt")

        with sovereign_temporary_directory() as temporary_directory:
            directory = Path(temporary_directory)
            checkpoint_path = directory / "core-mini.pt"
            predictable_temporary = checkpoint_path.with_suffix(
                checkpoint_path.suffix + ".tmp"
            )
            predictable_temporary.write_bytes(b"sentinel")
            torch = SaveTorch()
            digest = save_checkpoint(torch, checkpoint_path, {"safe": True})
            self.assertFalse(torch.destination_is_path)
            self.assertEqual(checkpoint_path.read_bytes(), b"deterministic-checkpoint")
            self.assertEqual(
                digest, hashlib.sha256(b"deterministic-checkpoint").hexdigest()
            )
            self.assertEqual(predictable_temporary.read_bytes(), b"sentinel")
            self.assertEqual(list(directory.glob("*.tmp")), [predictable_temporary])

            failed_path = directory / "failed.pt"
            with self.assertRaises(RuntimeError) as captured:
                save_checkpoint(BrokenTorch(), failed_path, {})
            self.assertIsNone(captured.exception.__cause__)
            self.assertNotIn("private", str(captured.exception))
            self.assertFalse(failed_path.exists())
            self.assertEqual(list(directory.glob("*.tmp")), [predictable_temporary])

    def test_parent_checkpoint_lineage_and_public_output_are_path_free(self) -> None:
        args = SimpleNamespace(
            threads=1,
            batch_size=2,
            sequence_length=8,
            seed=7,
            learning_rate=3e-4,
        )
        parent_sha256 = "a" * 64
        run = training_run_metadata(
            args,
            {"torch": "2.13.0+cpu"},
            authorized_bundle=None,
            parent_checkpoint_sha256=parent_sha256,
            parent_step=3,
        )
        self.assertEqual(
            run["lineage"],
            {
                "parent_checkpoint_sha256": parent_sha256,
                "parent_step": 3,
            },
        )
        result = checkpoint_public_result(
            Path("C:/private/output/core-mini-step-000004.pt"), "b" * 64
        )
        self.assertEqual(
            set(result), {"checkpoint_name", "checkpoint_sha256"}
        )
        self.assertNotIn("private", json.dumps(result))

    def test_public_cli_failure_never_echoes_private_path(self) -> None:
        private_path = "C:/private/checkpoint.pt"
        stderr = StringIO()
        with patch(
            "tools.train_core_mini._main", side_effect=OSError(private_path)
        ), redirect_stderr(stderr):
            result = main([])
        self.assertEqual(result, 1)
        self.assertNotIn(private_path, stderr.getvalue())

    def test_public_parser_is_path_free_and_help_stays_successful(self) -> None:
        private_path = "C:/private/operator-secret.pt"
        for arguments in (
            ["--unknown-option", private_path],
            ["--output-dir", "out", "--steps", private_path],
        ):
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main(arguments), 1)
            self.assertNotIn(private_path, stderr.getvalue())
            self.assertEqual(stderr.getvalue().strip(), "CORE-MINI training refused")

        stdout = StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as captured:
            main(["--help"])
        self.assertEqual(captured.exception.code, 0)
        self.assertIn("--output-dir", stdout.getvalue())

    def test_missing_authorized_input_error_does_not_echo_private_path(self) -> None:
        private_path = Path("C:/private/corpus/train.jsonl")
        args = argparse.Namespace(
            data_mode=DATA_MODE_AUTHORIZED_TEXT,
            authorized_manifest=Path("manifest.json"),
            authorized_train_jsonl=private_path,
            authorized_tokenizer=Path("tokenizer.json"),
        )
        with patch(
            "tools.train_core_mini.load_authorized_text_bundle",
            side_effect=FileNotFoundError(str(private_path)),
        ):
            with self.assertRaises(ValueError) as captured:
                load_training_bundle(args, model_vocabulary_size=4096)
        self.assertNotIn(str(private_path), str(captured.exception))

    def test_resume_state_rejects_optimizer_dtype_mismatch(self) -> None:
        checkpoint, model, optimizer = resume_checkpoint()
        checkpoint["optimizer"]["state"][0]["exp_avg"] = ResumeTensor(
            dtype="float16"
        )
        with self.assertRaisesRegex(CompatibilityError, "dtype"):
            load_resume_state_strict(
                RESUME_TORCH, model, optimizer, checkpoint
            )

    def test_resume_state_rejects_non_finite_tensor(self) -> None:
        checkpoint, model, optimizer = resume_checkpoint()
        checkpoint["optimizer"]["state"][0]["exp_avg"] = ResumeTensor(
            finite=False
        )
        with self.assertRaisesRegex(CompatibilityError, "non-finite"):
            load_resume_state_strict(
                RESUME_TORCH, model, optimizer, checkpoint
            )

        model.parameter.grad = ResumeTensor(finite=False)
        with self.assertRaisesRegex(CompatibilityError, "non-finite"):
            validate_model_gradients_finite(RESUME_TORCH, model)

    def test_resume_state_rejects_optimizer_step_mismatch(self) -> None:
        checkpoint, model, optimizer = resume_checkpoint(optimizer_step=2.0)
        with self.assertRaisesRegex(CompatibilityError, "does not match"):
            load_resume_state_strict(
                RESUME_TORCH, model, optimizer, checkpoint
            )

    def test_resume_state_rejects_incomplete_optimizer_state(self) -> None:
        checkpoint, model, optimizer = resume_checkpoint()
        checkpoint["optimizer"]["state"] = {}
        with self.assertRaisesRegex(CompatibilityError, "incomplete"):
            load_resume_state_strict(
                RESUME_TORCH, model, optimizer, checkpoint
            )

    def test_resume_state_rejects_optimizer_stride_storage_and_aliases(self) -> None:
        checkpoint, model, optimizer = resume_checkpoint()
        checkpoint["optimizer"]["state"][0]["exp_avg"] = ResumeTensor(
            stride=(2,)
        )
        with self.assertRaisesRegex(CompatibilityError, "stride"):
            load_resume_state_strict(RESUME_TORCH, model, optimizer, checkpoint)

        checkpoint, model, optimizer = resume_checkpoint()
        checkpoint["optimizer"]["state"][0]["exp_avg"] = ResumeTensor(
            storage_offset=1
        )
        with self.assertRaisesRegex(CompatibilityError, "offset"):
            load_resume_state_strict(RESUME_TORCH, model, optimizer, checkpoint)

        checkpoint, model, optimizer = resume_checkpoint()
        checkpoint["optimizer"]["state"][0]["exp_avg"] = ResumeTensor(
            storage_bytes=64
        )
        with self.assertRaisesRegex(CompatibilityError, "storage size"):
            load_resume_state_strict(RESUME_TORCH, model, optimizer, checkpoint)

        checkpoint, model, optimizer = resume_checkpoint()
        shared_tensor = checkpoint["optimizer"]["state"][0]["exp_avg"]
        checkpoint["optimizer"]["state"][0]["exp_avg_sq"] = shared_tensor
        with self.assertRaisesRegex(CompatibilityError, "identities"):
            load_resume_state_strict(RESUME_TORCH, model, optimizer, checkpoint)

        checkpoint, model, optimizer = resume_checkpoint()
        shared_storage = object()
        checkpoint["optimizer"]["state"][0]["exp_avg"] = ResumeTensor(
            storage_token=shared_storage
        )
        checkpoint["optimizer"]["state"][0]["exp_avg_sq"] = ResumeTensor(
            storage_token=shared_storage
        )
        with self.assertRaisesRegex(CompatibilityError, "storages"):
            load_resume_state_strict(RESUME_TORCH, model, optimizer, checkpoint)

        checkpoint, model, optimizer = resume_checkpoint()
        checkpoint["optimizer"]["state"][0]["exp_avg"] = ResumeTensor(
            storage_token=model.parameter._storage_token
        )
        with self.assertRaisesRegex(CompatibilityError, "model parameter storage"):
            load_resume_state_strict(RESUME_TORCH, model, optimizer, checkpoint)

    def test_resume_and_total_step_counts_are_bounded(self) -> None:
        contract = {"schema_version": "0.2.0", "data_mode": "authorized-text"}
        checkpoint = {
            "schema_version": "0.1.0",
            "model_name": "CORE-MINI-1M",
            "step": 10_001,
            "config_sha256": "a" * 64,
            "training_contract": contract,
            "model": {},
            "optimizer": {},
            "run": {},
        }
        with self.assertRaisesRegex(RuntimeError, "step"):
            validate_resume_checkpoint_document(
                checkpoint,
                model_name="CORE-MINI-1M",
                config_sha256="a" * 64,
                contract=contract,
            )
        with self.assertRaisesRegex(RuntimeError, "Final"):
            calculate_final_step(start_step=9_999, steps=2)
        self.assertEqual(calculate_final_step(start_step=9_999, steps=1), 10_000)

    def test_resume_envelope_binds_exact_configuration_and_contract(self) -> None:
        contract = {"schema_version": "0.2.0", "data_mode": "authorized-text"}
        checkpoint = {
            "schema_version": "0.1.0",
            "model_name": "CORE-MINI-1M",
            "step": 3,
            "config_sha256": "a" * 64,
            "training_contract": contract,
            "model": {},
            "optimizer": {},
            "run": {},
        }
        self.assertEqual(
            validate_resume_checkpoint_document(
                checkpoint,
                model_name="CORE-MINI-1M",
                config_sha256="a" * 64,
                contract=contract,
            ),
            3,
        )
        tampered = dict(checkpoint)
        tampered["config_sha256"] = "b" * 64
        with self.assertRaisesRegex(RuntimeError, "configuration"):
            validate_resume_checkpoint_document(
                tampered,
                model_name="CORE-MINI-1M",
                config_sha256="a" * 64,
                contract=contract,
            )
        extra = dict(checkpoint)
        extra["unexpected"] = "refused"
        with self.assertRaisesRegex(RuntimeError, "keys"):
            validate_resume_checkpoint_document(
                extra,
                model_name="CORE-MINI-1M",
                config_sha256="a" * 64,
                contract=contract,
            )

        strict_contract = {"schema_version": "0.2.0", "nested": {"count": 1}}
        bool_contract_checkpoint = dict(checkpoint)
        bool_contract_checkpoint["training_contract"] = {
            "schema_version": "0.2.0",
            "nested": {"count": True},
        }
        with self.assertRaisesRegex(RuntimeError, "contract"):
            validate_resume_checkpoint_document(
                bool_contract_checkpoint,
                model_name="CORE-MINI-1M",
                config_sha256="a" * 64,
                contract=strict_contract,
            )

    def test_existing_authorized_metrics_require_exact_lineage_contract_and_types(self) -> None:
        bundle = authorized_bundle("Historique autorisé.")
        contract = authorized_contract(bundle)
        records = [
            training_metric_record(
                step=step,
                loss=1.0,
                elapsed_seconds=float(step),
                tokens=8,
                authorized_bundle=bundle,
                training_contract_document=contract,
            )
            for step in range(1, 5)
        ]
        payload = b"".join(
            json.dumps(record, sort_keys=True).encode("utf-8") + b"\n"
            for record in records
        )
        last_step, prefix_offset = validate_authorized_metrics_payload(
            payload,
            authorized_bundle=bundle,
            training_contract_document=contract,
            expected_tokens=8,
            checkpoint_step=4,
        )
        self.assertEqual((last_step, prefix_offset), (4, len(payload)))

        with self.assertRaisesRegex(RuntimeError, "lineage"):
            validate_authorized_metrics_payload(
                payload,
                authorized_bundle=replace(bundle, train_sha256="d" * 64),
                training_contract_document=contract,
                expected_tokens=8,
                checkpoint_step=4,
            )
        with self.assertRaisesRegex(RuntimeError, "contract"):
            validate_authorized_metrics_payload(
                payload,
                authorized_bundle=bundle,
                training_contract_document={**contract, "threads": 2},
                expected_tokens=8,
                checkpoint_step=4,
            )
        with self.assertRaisesRegex(RuntimeError, "token count"):
            validate_authorized_metrics_payload(
                payload,
                authorized_bundle=bundle,
                training_contract_document=contract,
                expected_tokens=9,
                checkpoint_step=4,
            )
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            validate_authorized_metrics_payload(
                payload.rstrip(b"\n"),
                authorized_bundle=bundle,
                training_contract_document=contract,
                expected_tokens=8,
                checkpoint_step=4,
            )

        bool_lineage = dict(records[0])
        bool_lineage["data_lineage"] = dict(bool_lineage["data_lineage"])
        bool_lineage["data_lineage"]["corpus"] = dict(
            bool_lineage["data_lineage"]["corpus"]
        )
        bool_lineage["data_lineage"]["corpus"]["record_count"] = True
        with self.assertRaisesRegex(RuntimeError, "lineage"):
            validate_authorized_metrics_payload(
                json.dumps(bool_lineage).encode("utf-8") + b"\n",
                authorized_bundle=bundle,
                training_contract_document=contract,
                expected_tokens=8,
                checkpoint_step=1,
            )

    def test_authorized_metrics_reject_content_keys_duplicates_and_late_start(self) -> None:
        bundle = authorized_bundle("Journal strict.")
        contract = authorized_contract(bundle)
        record = training_metric_record(
            step=1,
            loss=1.0,
            elapsed_seconds=0.1,
            tokens=8,
            authorized_bundle=bundle,
            training_contract_document=contract,
        )
        for forbidden_key in ("text", "path"):
            with self.subTest(forbidden_key=forbidden_key):
                invalid = {**record, forbidden_key: "DUMMY_PRIVATE_CONTENT"}
                payload = json.dumps(invalid).encode("utf-8") + b"\n"
                with self.assertRaisesRegex(RuntimeError, "keys"):
                    validate_authorized_metrics_payload(
                        payload,
                        authorized_bundle=bundle,
                        training_contract_document=contract,
                        expected_tokens=8,
                        checkpoint_step=1,
                    )

        encoded = json.dumps(record, separators=(",", ":"))
        duplicate_step = (encoded[:-1] + ',"step":1}\n').encode("utf-8")
        with self.assertRaisesRegex(RuntimeError, "strict JSON"):
            validate_authorized_metrics_payload(
                duplicate_step,
                authorized_bundle=bundle,
                training_contract_document=contract,
                expected_tokens=8,
                checkpoint_step=1,
            )

        late = training_metric_record(
            step=2,
            loss=1.0,
            elapsed_seconds=0.2,
            tokens=8,
            authorized_bundle=bundle,
            training_contract_document=contract,
        )
        with self.assertRaisesRegex(RuntimeError, "contiguous"):
            validate_authorized_metrics_payload(
                json.dumps(late).encode("utf-8") + b"\n",
                authorized_bundle=bundle,
                training_contract_document=contract,
                expected_tokens=8,
                checkpoint_step=2,
            )

    def test_resume_requires_existing_authorized_metrics_without_path_leak(self) -> None:
        bundle = authorized_bundle("Reprise stricte.")
        contract = authorized_contract(bundle)
        with sovereign_temporary_directory() as temporary_directory:
            missing_path = Path(temporary_directory) / "private-history.jsonl"
            with self.assertRaises(RuntimeError) as captured:
                with open_authorized_metrics_journal(
                    missing_path,
                    authorized_bundle=bundle,
                    training_contract_document=contract,
                    expected_tokens=8,
                    checkpoint_step=2,
                    require_existing=True,
                    recover_ahead=True,
                ):
                    pass
            self.assertNotIn(str(missing_path), str(captured.exception))
            self.assertFalse(missing_path.exists())

    def test_authorized_metrics_ahead_of_checkpoint_are_recovered_on_same_handle(self) -> None:
        bundle = authorized_bundle("Récupération après interruption.")
        contract = authorized_contract(bundle)
        records = [
            training_metric_record(
                step=step,
                loss=1.0,
                elapsed_seconds=float(step),
                tokens=8,
                authorized_bundle=bundle,
                training_contract_document=contract,
            )
            for step in range(1, 5)
        ]
        with sovereign_temporary_directory() as temporary_directory:
            metrics_path = Path(temporary_directory) / "metrics.jsonl"
            metrics_path.write_bytes(
                b"".join(
                    json.dumps(record, sort_keys=True).encode("utf-8") + b"\n"
                    for record in records
                )
            )
            with open_authorized_metrics_journal(
                metrics_path,
                authorized_bundle=bundle,
                training_contract_document=contract,
                expected_tokens=8,
                checkpoint_step=2,
                require_existing=True,
                recover_ahead=True,
                expected_prefix_sha256=hashlib.sha256(
                    b"".join(
                        json.dumps(record, sort_keys=True).encode("utf-8") + b"\n"
                        for record in records[:2]
                    )
                ).hexdigest(),
            ) as journal:
                append_authorized_metric(journal, records[2])
                prefix_sha256 = hash_authorized_metrics_journal(
                    journal,
                    authorized_bundle=bundle,
                    training_contract_document=contract,
                    expected_tokens=8,
                    checkpoint_step=3,
                )

            recovered_payload = metrics_path.read_bytes()
            recovered_steps = [
                json.loads(line)["step"] for line in recovered_payload.splitlines()
            ]
            self.assertEqual(recovered_steps, [1, 2, 3])
            self.assertEqual(prefix_sha256, hashlib.sha256(recovered_payload).hexdigest())
            validate_authorized_metrics_payload(
                recovered_payload,
                authorized_bundle=bundle,
                training_contract_document=contract,
                expected_tokens=8,
                checkpoint_step=3,
            )

    def test_authorized_checkpoint_binds_exact_metrics_prefix_without_content(self) -> None:
        bundle = authorized_bundle("Journal lié au checkpoint.")
        contract = authorized_contract(bundle)
        first = training_metric_record(
            step=1,
            loss=1.0,
            elapsed_seconds=0.1,
            tokens=8,
            authorized_bundle=bundle,
            training_contract_document=contract,
        )
        different = dict(first)
        different["loss"] = 2.0
        first_payload = json.dumps(first, sort_keys=True).encode("utf-8") + b"\n"
        different_payload = (
            json.dumps(different, sort_keys=True).encode("utf-8") + b"\n"
        )
        expected_hash = hashlib.sha256(first_payload).hexdigest()
        run = training_run_metadata(
            SimpleNamespace(
                threads=1,
                batch_size=1,
                sequence_length=8,
                seed=7,
                learning_rate=3e-4,
            ),
            contract,
            authorized_bundle=bundle,
            parent_checkpoint_sha256=None,
            parent_step=None,
            authorized_metrics_prefix_sha256=expected_hash,
            authorized_metrics_step=1,
        )
        checkpoint = {"run": run}
        self.assertEqual(
            authorized_metrics_binding_from_checkpoint(
                checkpoint, checkpoint_step=1
            ),
            expected_hash,
        )
        self.assertNotIn("Journal lié", json.dumps(run))

        with sovereign_temporary_directory() as temporary_directory:
            metrics_path = Path(temporary_directory) / "metrics.jsonl"
            metrics_path.write_bytes(different_payload)
            with self.assertRaisesRegex(RuntimeError, "prefix does not match"):
                with open_authorized_metrics_journal(
                    metrics_path,
                    authorized_bundle=bundle,
                    training_contract_document=contract,
                    expected_tokens=8,
                    checkpoint_step=1,
                    require_existing=True,
                    recover_ahead=True,
                    expected_prefix_sha256=expected_hash,
                ):
                    pass

        missing_binding = {"run": {"data_mode": DATA_MODE_AUTHORIZED_TEXT}}
        with self.assertRaisesRegex(RuntimeError, "binding"):
            authorized_metrics_binding_from_checkpoint(
                missing_binding, checkpoint_step=1
            )


if __name__ == "__main__":
    unittest.main()
