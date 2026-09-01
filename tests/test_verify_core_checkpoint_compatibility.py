from io import StringIO
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools.verify_core_checkpoint_compatibility import (
    CHECKPOINT_KEYS,
    CompatibilityError,
    load_checkpoint_safely,
    load_model_state_strict,
    load_optimizer_state_strict,
    main,
    validate_checkpoint_document,
    validate_training_contract,
)


CONFIG_HASH = "a" * 64
BOUNDED_FIXTURE = Path(__file__).parent / "fixtures" / "checkpoint-loader-small.bin"


def valid_contract() -> dict:
    return {
        "schema_version": "0.1.0",
        "config_sha256": CONFIG_HASH,
        "torch": "2.13.0+cpu",
        "device": "cpu",
        "dtype": "float32",
        "optimizer": "AdamW",
        "learning_rate": 3e-4,
        "batch_size": 2,
        "sequence_length": 8,
        "seed": 7,
        "threads": 1,
        "synthetic_generator": "arithmetic-v1",
    }


class LoadOnlyTorch:
    __version__ = "2.13.0+cpu"

    def __init__(self, result: object) -> None:
        self.result = result
        self.kwargs = None
        self.loaded_from_path = None

    def load(self, source, **kwargs):
        self.kwargs = kwargs
        self.loaded_from_path = isinstance(source, (str, Path))
        return self.result


class FakeTensor:
    def __init__(
        self,
        shape=(),
        *,
        scalar=False,
        dtype="float32",
        device="cpu",
        item_value=1.0,
    ) -> None:
        self.shape = shape
        self.device = SimpleNamespace(type=device)
        self.dtype = dtype
        self.layout = "strided"
        self._scalar = scalar
        self._item_value = item_value

    def numel(self) -> int:
        return 1 if self._scalar else 4

    def item(self):
        return self._item_value


class CheckpointCompatibilityTests(unittest.TestCase):
    def test_safe_loader_uses_one_open_file_cpu_and_weights_only(self) -> None:
        expected = {"schema_version": "0.1.0"}
        torch = LoadOnlyTorch(expected)
        loaded, digest, size = load_checkpoint_safely(torch, BOUNDED_FIXTURE)
        self.assertIs(loaded, expected)
        self.assertEqual(torch.kwargs, {"map_location": "cpu", "weights_only": True})
        self.assertFalse(torch.loaded_from_path)
        self.assertEqual(len(digest), 64)
        self.assertEqual(size, BOUNDED_FIXTURE.stat().st_size)

    def test_safe_loader_refuses_file_over_explicit_limit_before_torch_load(self) -> None:
        torch = LoadOnlyTorch({})
        with self.assertRaisesRegex(CompatibilityError, "size"):
            load_checkpoint_safely(torch, BOUNDED_FIXTURE, maximum_bytes=3)
        self.assertIsNone(torch.kwargs)

    def test_training_contract_is_exact_and_cpu_only(self) -> None:
        torch = SimpleNamespace(__version__="2.13.0+cpu")
        self.assertEqual(
            validate_training_contract(valid_contract(), config_sha256=CONFIG_HASH, torch=torch),
            valid_contract(),
        )
        modified = valid_contract()
        modified["device"] = "cuda"
        with self.assertRaisesRegex(CompatibilityError, "execution mode"):
            validate_training_contract(modified, config_sha256=CONFIG_HASH, torch=torch)

    def test_checkpoint_schema_model_config_and_contract_are_strict(self) -> None:
        checkpoint = {key: {} for key in CHECKPOINT_KEYS}
        checkpoint.update(
            schema_version="0.1.0",
            model_name="CORE-MINI-1M",
            step=4,
            config_sha256=CONFIG_HASH,
            training_contract=valid_contract(),
            run={},
        )
        step, contract = validate_checkpoint_document(
            checkpoint,
            model_name="CORE-MINI-1M",
            config_sha256=CONFIG_HASH,
            torch=SimpleNamespace(__version__="2.13.0+cpu"),
        )
        self.assertEqual(step, 4)
        self.assertEqual(contract["synthetic_generator"], "arithmetic-v1")

        checkpoint["model_name"] = "OTHER"
        with self.assertRaisesRegex(CompatibilityError, "model name"):
            validate_checkpoint_document(
                checkpoint,
                model_name="CORE-MINI-1M",
                config_sha256=CONFIG_HASH,
                torch=SimpleNamespace(__version__="2.13.0+cpu"),
            )

    def test_model_state_keys_and_strict_flag_are_verified(self) -> None:
        class Model:
            strict = None

            def state_dict(self):
                return {
                    "token_embeddings.weight": FakeTensor((2, 2)),
                    "final_norm.weight": FakeTensor((2,)),
                }

            def load_state_dict(self, state, *, strict):
                self.strict = strict
                return SimpleNamespace(missing_keys=[], unexpected_keys=[])

        model = Model()
        torch = SimpleNamespace(
            is_tensor=lambda value: isinstance(value, FakeTensor),
            float32="float32",
        )
        count = load_model_state_strict(
            torch,
            model,
            {
                "token_embeddings.weight": FakeTensor((2, 2)),
                "final_norm.weight": FakeTensor((2,)),
            },
        )
        self.assertEqual(count, 2)
        self.assertTrue(model.strict)
        with self.assertRaisesRegex(CompatibilityError, "keys"):
            load_model_state_strict(
                torch, model, {"token_embeddings.weight": FakeTensor((2, 2))}
            )
        with self.assertRaisesRegex(CompatibilityError, "dtype"):
            load_model_state_strict(
                torch,
                model,
                {
                    "token_embeddings.weight": FakeTensor(
                        (2, 2), dtype="float16"
                    ),
                    "final_norm.weight": FakeTensor((2,)),
                },
            )

    def test_optimizer_groups_order_and_tensor_shapes_are_verified(self) -> None:
        class Parameter:
            def __init__(self, shape):
                self.shape = shape
                self.device = SimpleNamespace(type="cpu")
                self.dtype = "float32"
                self.layout = "strided"

        parameters = [Parameter((2, 2)), Parameter((2,))]

        class Model:
            def parameters(self):
                return iter(parameters)

        class Optimizer:
            def __init__(self):
                self.state = {}

            def state_dict(self):
                return {
                    "state": {},
                    "param_groups": [{"params": [0, 1], "lr": 0.1, "amsgrad": False}],
                }

            def load_state_dict(self, state):
                self.state = {
                    parameter: state["state"][index]
                    for index, parameter in enumerate(parameters)
                }

        state = {
            "state": {
                0: {
                    "step": FakeTensor(scalar=True, item_value=4.0),
                    "exp_avg": FakeTensor((2, 2)),
                    "exp_avg_sq": FakeTensor((2, 2)),
                },
                1: {
                    "step": FakeTensor(scalar=True, item_value=4.0),
                    "exp_avg": FakeTensor((2,)),
                    "exp_avg_sq": FakeTensor((2,)),
                },
            },
            "param_groups": [{"params": [0, 1], "lr": 0.1, "amsgrad": False}],
        }
        torch = SimpleNamespace(
            is_tensor=lambda value: isinstance(value, FakeTensor),
            float32="float32",
        )
        self.assertEqual(
            load_optimizer_state_strict(
                torch, Optimizer(), Model(), state, checkpoint_step=4
            ),
            2,
        )
        state["state"][0]["exp_avg"] = FakeTensor((2, 2), dtype="float16")
        with self.assertRaisesRegex(CompatibilityError, "dtype"):
            load_optimizer_state_strict(
                torch, Optimizer(), Model(), state, checkpoint_step=4
            )
        state["state"][0]["exp_avg"] = FakeTensor((2, 2))
        state["state"][1]["step"] = FakeTensor(scalar=True, item_value=3.0)
        with self.assertRaisesRegex(CompatibilityError, "does not match"):
            load_optimizer_state_strict(
                torch, Optimizer(), Model(), state, checkpoint_step=4
            )

    def test_public_failure_does_not_echo_checkpoint_path(self) -> None:
        private_path = "C:/private/historical.pt"
        stderr = StringIO()
        with patch(
            "tools.verify_core_checkpoint_compatibility.verify_checkpoint",
            side_effect=CompatibilityError("checkpoint is unavailable"),
        ), patch("sys.stderr", stderr):
            result = main(["--checkpoint", private_path])
        self.assertEqual(result, 1)
        self.assertNotIn(private_path, stderr.getvalue())


HAS_TORCH = importlib.util.find_spec("torch") is not None


@unittest.skipUnless(HAS_TORCH, "verified offline PyTorch bundle is not installed locally")
class RealCheckpointCompatibilityTests(unittest.TestCase):
    def test_generated_historical_contract_can_resume_exactly_one_step(self) -> None:
        # The full compatibility path is exercised on the ML350, where the
        # verified CPU-only PyTorch bundle is installed.  Local development
        # machines without that bundle skip instead of downloading anything.
        from services.inference.model import build_model, require_cpu_torch
        from tools.train_core_mini import (
            DEFAULT_CONFIG,
            load_and_validate_document,
            save_checkpoint,
            training_contract,
        )
        from tools.verify_core_checkpoint_compatibility import (
            resume_one_synthetic_step,
            verify_checkpoint,
        )
        import argparse
        import hashlib

        torch = require_cpu_torch()
        document, config = load_and_validate_document(DEFAULT_CONFIG)
        config_hash = hashlib.sha256(DEFAULT_CONFIG.read_bytes()).hexdigest()
        args = argparse.Namespace(
            learning_rate=3e-4,
            batch_size=1,
            sequence_length=2,
            seed=7,
            threads=1,
        )
        contract = training_contract(args, config_hash, torch)
        torch.set_num_threads(1)
        torch.manual_seed(7)
        torch.use_deterministic_algorithms(True)
        model = build_model(torch, config)
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
        resume_one_synthetic_step(
            torch, model, optimizer, config, contract, step=0
        )
        payload = {
            "schema_version": "0.1.0",
            "model_name": document["name"],
            "step": 1,
            "config_sha256": config_hash,
            "training_contract": contract,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "run": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "historical.pt"
            save_checkpoint(torch, checkpoint, payload)
            report = verify_checkpoint(checkpoint, torch_module=torch)
        self.assertEqual(report["step_before"], 1)
        self.assertEqual(report["step_after"], 2)
        self.assertEqual(report["resumed_steps"], 1)


if __name__ == "__main__":
    unittest.main()
