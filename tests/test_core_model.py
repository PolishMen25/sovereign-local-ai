from types import SimpleNamespace
import unittest

from services.inference.model import build_model, validate_cpu_torch
from tools.count_core_parameters import CoreConfig
from tools.train_core_mini import build_model as training_build_model


class CoreModelBoundaryTests(unittest.TestCase):
    @staticmethod
    def torch_metadata(*, cuda_build=None, hip_build=None, available=False):
        return SimpleNamespace(
            version=SimpleNamespace(cuda=cuda_build, hip=hip_build),
            cuda=SimpleNamespace(is_available=lambda: available),
        )

    def test_accepts_explicit_cpu_only_runtime(self) -> None:
        torch = self.torch_metadata()
        self.assertIs(validate_cpu_torch(torch), torch)

    def test_rejects_cuda_build_even_when_device_is_unavailable(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "CUDA/ROCm"):
            validate_cpu_torch(self.torch_metadata(cuda_build="13.0"))

    def test_rejects_rocm_build(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "CUDA/ROCm"):
            validate_cpu_torch(self.torch_metadata(hip_build="7.0"))

    def test_rejects_available_cuda_runtime(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "CUDA runtime"):
            validate_cpu_torch(self.torch_metadata(available=True))

    def test_rejects_incomplete_runtime_metadata(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "version metadata"):
            validate_cpu_torch(SimpleNamespace())

    def test_training_uses_the_shared_builder(self) -> None:
        self.assertIs(training_build_model, build_model)

    def test_shared_builder_rejects_untied_embeddings_before_allocation(self) -> None:
        config = CoreConfig(
            vocabulary_size=32,
            hidden_size=8,
            num_hidden_layers=1,
            num_attention_heads=1,
            head_dimension=8,
            intermediate_size=16,
            tie_word_embeddings=False,
        )
        with self.assertRaisesRegex(ValueError, "tied embeddings"):
            build_model(self.torch_metadata(), config)


if __name__ == "__main__":
    unittest.main()
