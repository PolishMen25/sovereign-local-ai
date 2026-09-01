#!/usr/bin/env bash
set -euo pipefail

bootstrap_root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
runtime_dir="$bootstrap_root/runtime"
model_path="$bootstrap_root/models/qwen2.5-1.5b-instruct-q4_k_m.gguf"

test -x "$runtime_dir/llama-cli" || { echo "bootstrap runtime is missing" >&2; exit 1; }
test -r "$model_path" || { echo "bootstrap model is missing" >&2; exit 1; }

export LD_LIBRARY_PATH="$runtime_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec "$runtime_dir/llama-cli" \
  --model "$model_path" \
  --conversation \
  --simple-io \
  --system-prompt "Tu es BOOTSTRAP, un assistant local temporaire distinct de CORE-80M. Réponds en français, clairement et honnêtement. Tu n'as ni outil ni accès Internet. Ne prétends jamais être CORE." \
  --threads "${SOVEREIGN_CHAT_THREADS:-20}" \
  --ctx-size "${SOVEREIGN_CHAT_CONTEXT:-4096}" \
  --n-predict "${SOVEREIGN_CHAT_MAX_TOKENS:-512}" \
  --temp "${SOVEREIGN_CHAT_TEMPERATURE:-0.4}" \
  --top-k 40 \
  --no-display-prompt
