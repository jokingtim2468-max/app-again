#!/usr/bin/env bash
# Run on a RunPod Secure Cloud A100 80GB (or H100 80GB). Disk: 150 GB volume. Est. 2-3 h (~$4-6 on A100).
# Usage: HF_TOKEN=<your write token> bash teacher/run_teacher.sh            (full run)
#        HF_TOKEN=... PER_GROUP=3 SAMPLES=2 bash teacher/run_teacher.sh    (10-min smoke test first - recommended)
set -euo pipefail
: "${HF_TOKEN:?set HF_TOKEN (Hugging Face write token) so the output can be uploaded}"
pip install -q vllm huggingface_hub
python teacher/generate.py --per-group "${PER_GROUP:-25}" --samples "${SAMPLES:-4}" --out teacher_raw.jsonl
REPO="jokingtim24688/gamedev-teacher-raw"
python - <<PY
from huggingface_hub import HfApi
api = HfApi(token="$HF_TOKEN")
api.create_repo("$REPO", repo_type="dataset", private=True, exist_ok=True)
api.upload_file(path_or_fileobj="teacher_raw.jsonl", path_in_repo="teacher_raw.jsonl", repo_id="$REPO", repo_type="dataset")
print("uploaded to https://huggingface.co/datasets/$REPO (private)")
PY
echo ">>> DONE. Tell Claude it's uploaded. Now STOP the pod and delete the volume."
