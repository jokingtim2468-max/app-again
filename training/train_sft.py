"""QLoRA SFT with Unsloth.

Go/no-go:  python training/train_sft.py --gonogo --steps 30
  Prints peak VRAM, sec/step, and projected full-run cost at $0.89/hr (RTX 4090).
Full run:  python training/train_sft.py --epochs 2
"""
import argparse, json, math, time

p = argparse.ArgumentParser()
p.add_argument("--model", default="Qwen/Qwen3.6-27B")  # verify exact repo id + license first
p.add_argument("--data", default="data/sft.jsonl")
p.add_argument("--max-len", type=int, default=4096)
p.add_argument("--epochs", type=float, default=2)
p.add_argument("--steps", type=int, default=30)
p.add_argument("--gonogo", action="store_true")
p.add_argument("--rate", type=float, default=0.89, help="$/hr of the pod")
p.add_argument("--budget", type=float, default=8.0)
p.add_argument("--full-examples", type=int, default=2137)
a = p.parse_args()

import torch
from datasets import load_dataset
from unsloth import FastModel  # Qwen3.6-27B is multimodal (qwen3_5 arch); train text layers only
from trl import SFTConfig, SFTTrainer

model, tok = FastModel.from_pretrained(a.model, max_seq_length=a.max_len, load_in_4bit=True)
model = FastModel.get_peft_model(
    model, finetune_vision_layers=False, finetune_language_layers=True,
    finetune_attention_modules=True, finetune_mlp_modules=True, r=16, lora_alpha=32, lora_dropout=0,
    use_gradient_checkpointing="unsloth")

ds = load_dataset("json", data_files=a.data, split="train")
tmpl = getattr(tok, "tokenizer", tok)  # processor -> tokenizer for multimodal models
ds = ds.map(lambda r: {"text": tmpl.apply_chat_template(r["messages"], tokenize=False)})
bs, ga = 1, 8
cfg = SFTConfig(output_dir="out/adapter", per_device_train_batch_size=bs, gradient_accumulation_steps=ga,
                learning_rate=1e-4, logging_steps=5, bf16=True, optim="adamw_8bit",
                max_seq_length=a.max_len, dataset_text_field="text", save_strategy="no" if a.gonogo else "epoch",
                **({"max_steps": a.steps} if a.gonogo else {"num_train_epochs": a.epochs}))
trainer = SFTTrainer(model=model, processing_class=tmpl, train_dataset=ds, args=cfg)

torch.cuda.reset_peak_memory_stats()
t0 = time.time()
trainer.train()
dt = time.time() - t0

if a.gonogo:
    peak = torch.cuda.max_memory_allocated() / 1e9
    sec_step = dt / a.steps
    full_steps = math.ceil(a.full_examples * a.epochs / (bs * ga))
    hours = full_steps * sec_step / 3600
    cost = hours * a.rate
    go = peak < 23.0 and cost < a.budget
    result = dict(peak_vram_gb=round(peak, 2), sec_per_step=round(sec_step, 2),
                  projected_hours=round(hours, 2), projected_cost=round(cost, 2), decision="GO" if go else "NO-GO")
    print(json.dumps(result, indent=2))
    json.dump(result, open("gonogo_result.json", "w"), indent=2)
else:
    model.save_pretrained("out/adapter"); tok.save_pretrained("out/adapter")
