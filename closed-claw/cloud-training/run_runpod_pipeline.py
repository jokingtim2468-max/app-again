#!/usr/bin/env python3
"""RunPod GPU pipeline: synthetic macro dataset -> Unsloth LoRA fine-tune -> GGUF q4_k_m -> Ollama Modelfile.

Run on an RTX 4090 / A5000 / A6000 pod (CUDA 12.x):   python run_runpod_pipeline.py
Typical cost: ~15-25 min of GPU time (~$0.15-0.30 on a community 4090). Stop the pod afterwards.

Caveat: the dataset is rule-generated (textbook macro reactions), so the model learns those
heuristics in a compact JSON format. It is not trained on real historical gold reactions.
"""
from __future__ import annotations

import importlib
import json
import random
import subprocess
import sys
from pathlib import Path

REQUIRED = ["unsloth", "torch", "transformers", "trl", "peft", "accelerate", "bitsandbytes", "datasets"]
BASE_MODEL = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit"
OUT = Path("export")
SYSTEM_PROMPT = (
    "You are news-predictor-3b, a deterministic macroeconomic news prediction engine for gold futures. "
    "Given an event, consensus forecast and actual print, reply with ONLY one compact JSON object with keys "
    "event, actual_vs_forecast, gold_bias, confidence, expected_expansion_points. No prose."
)


def ensure_deps() -> None:
    missing = []
    for pkg in REQUIRED:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[setup] installing {missing}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--upgrade", *missing])


# event: (unit, typical consensus range, surprise step, "higher is" hawkish?, base expansion pts)
EVENTS = {
    "US CPI YoY": ("%", (2.0, 4.0), 0.1, True, 12.0),
    "US Core CPI MoM": ("%", (0.1, 0.5), 0.1, True, 11.0),
    "US Core PCE MoM": ("%", (0.1, 0.4), 0.1, True, 8.0),
    "US Nonfarm Payrolls": ("K", (50, 300), 25, True, 14.0),
    "US Unemployment Rate": ("%", (3.5, 4.8), 0.1, False, 9.0),
    "US GDP QoQ Annualized": ("%", (0.5, 3.5), 0.3, True, 7.0),
    "FOMC Rate Decision": ("%", (3.25, 5.5), 0.25, True, 16.0),
}


def make_example(rng: random.Random) -> dict:
    event, (unit, (lo, hi), step, higher_hawkish, base) = rng.choice(list(EVENTS.items()))
    consensus = round(rng.uniform(lo, hi) / step) * step
    k = rng.choice([-3, -2, -1, 0, 0, 1, 2, 3])
    actual = consensus + k * step
    fmt = (lambda v: f"{v:.0f}{unit}") if unit == "K" else (lambda v: f"{v:.2f}{unit}")
    if k == 0:
        avf, bias, conf, pts = "in_line", "neutral", 0.55, round(base * 0.3, 1)
    else:
        avf = "higher_than_expected" if k > 0 else "lower_than_expected"
        hawkish = (k > 0) == higher_hawkish
        bias = "bearish" if hawkish else "bullish"  # hawkish -> stronger USD / real yields -> gold down
        conf = round(min(0.95, 0.6 + 0.1 * abs(k) + rng.uniform(-0.03, 0.03)), 2)
        pts = round(base * (0.6 + 0.35 * abs(k)) * rng.uniform(0.9, 1.1), 1)
    headline = rng.choice([f"{event} prints {fmt(actual)} vs {fmt(consensus)} expected",
                           f"BREAKING: {event} at {fmt(actual)}, consensus {fmt(consensus)}",
                           f"{event} release: actual {fmt(actual)}"])
    user = (f"Event: {event}\nHeadline: {headline}\nConsensus forecast: {fmt(consensus)}\n"
            f"Actual print: {fmt(actual)}\nReturn the gold reaction JSON.")
    answer = {"event": event, "actual_vs_forecast": avf, "gold_bias": bias,
              "confidence": conf, "expected_expansion_points": pts}
    return {"messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": user},
                         {"role": "assistant", "content": json.dumps(answer, separators=(",", ":"))}]}


def build_dataset(n: int = 600, path: Path = Path("news_dataset.jsonl")) -> Path:
    rng = random.Random(1337)
    with path.open("w") as f:
        for _ in range(n):
            f.write(json.dumps(make_example(rng)) + "\n")
    print(f"[data] wrote {n} ChatML examples -> {path}")
    return path


def train(dataset_path: Path):
    from unsloth import FastLanguageModel, is_bfloat16_supported  # import first (patches)
    from unsloth.chat_templates import get_chat_template
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer

    model, tokenizer = FastLanguageModel.from_pretrained(BASE_MODEL, max_seq_length=2048, load_in_4bit=True)
    tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=16, lora_dropout=0, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=3407)

    ds = load_dataset("json", data_files=str(dataset_path), split="train")
    ds = ds.map(lambda b: {"text": [tokenizer.apply_chat_template(m, tokenize=False) for m in b["messages"]]},
                batched=True)

    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=ds,
        args=SFTConfig(dataset_text_field="text", max_seq_length=2048, per_device_train_batch_size=4,
                       gradient_accumulation_steps=2, warmup_steps=10, max_steps=150, learning_rate=2e-4,
                       fp16=not is_bfloat16_supported(), bf16=is_bfloat16_supported(), logging_steps=10,
                       optim="adamw_8bit", weight_decay=0.01, lr_scheduler_type="linear", seed=3407,
                       output_dir="outputs", report_to="none"))
    trainer.train()
    return model, tokenizer


def smoke_test(model, tokenizer) -> None:
    from unsloth import FastLanguageModel
    FastLanguageModel.for_inference(model)
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Event: US CPI YoY\nHeadline: CPI hot\nConsensus forecast: 3.00%\n"
                                        "Actual print: 3.30%\nReturn the gold reaction JSON."}]
    ids = tokenizer.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to("cuda")
    out = model.generate(input_ids=ids, max_new_tokens=96, do_sample=False)
    print("[smoke]", tokenizer.decode(out[0][ids.shape[1]:], skip_special_tokens=True))


def export(model, tokenizer) -> None:
    OUT.mkdir(exist_ok=True)
    model.save_pretrained_gguf(str(OUT / "news-predictor-3b"), tokenizer, quantization_method="q4_k_m")
    ggufs = sorted(Path(".").rglob("*.gguf"), key=lambda p: p.stat().st_mtime)
    gguf = ggufs[-1]
    final = OUT / "news-predictor-3b.Q4_K_M.gguf"
    if gguf.resolve() != final.resolve():
        gguf.replace(final)
    (OUT / "Modelfile").write_text(f'''FROM ./{final.name}
TEMPLATE """{{{{ if .System }}}}<|im_start|>system
{{{{ .System }}}}<|im_end|>
{{{{ end }}}}<|im_start|>user
{{{{ .Prompt }}}}<|im_end|>
<|im_start|>assistant
"""
SYSTEM """{SYSTEM_PROMPT}"""
PARAMETER temperature 0.1
PARAMETER top_p 0.9
PARAMETER num_ctx 2048
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|im_start|>"
PARAMETER stop "<|endoftext|>"
''')
    (OUT / "download_instructions.txt").write_text(f"""1. Download the export/ folder from the pod (runpodctl send export  OR  Jupyter file browser).
2. On your machine, in the folder holding {final.name} and Modelfile:
       ollama create news-predictor-3b -f ./Modelfile
3. Test:
       ollama run news-predictor-3b "Event: US CPI YoY\\nConsensus forecast: 3.00%\\nActual print: 3.30%"
4. STOP / TERMINATE the RunPod pod so it stops billing.
""")
    print(f"[export] {final}  + Modelfile + download_instructions.txt in {OUT}/")


def main() -> None:
    ensure_deps()
    import torch
    if not torch.cuda.is_available():
        sys.exit("CUDA GPU not found. Run this on a RunPod GPU pod (CUDA 12.x).")
    print(f"[gpu] {torch.cuda.get_device_name(0)}")
    ds = build_dataset()
    model, tok = train(ds)
    smoke_test(model, tok)
    export(model, tok)


if __name__ == "__main__":
    if "--dataset-only" in sys.argv:
        build_dataset()
    else:
        main()
