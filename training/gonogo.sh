#!/usr/bin/env bash
# Run on the RTX 4090 Secure Cloud pod. Target: ~30-45 min (~$0.50-0.70). STOP THE POD AFTER.
set -euo pipefail
pip install -q unsloth trl datasets
head -n 200 data/sft.jsonl > data/sft_slice.jsonl
python training/train_sft.py --gonogo --steps 30 --data data/sft_slice.jsonl
echo ">>> Now stop the pod and delete unused volumes."
