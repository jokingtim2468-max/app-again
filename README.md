# Game-Dev Coder Model

Fine-tune Qwen3.6-27B (fallback: 7-8B) with QLoRA into a Roblox (Luau) + Unity (C#) assistant,
with an image-to-3D workflow (TRELLIS.2 -> Blender bpy cleanup -> engine import).
Unreal is documentation-only.

## Layout
- `dataset/sources.csv` - every data source + its license (permissive only).
- `dataset/verify.py` - compiles/lints each example; only passing ones go to `data/verified/`.
- `dataset/build_sft.py` - turns verified examples into chat-format JSONL.
- `training/train_sft.py` - QLoRA SFT (Unsloth). `--gonogo` mode measures VRAM + speed + projected cost.
- `training/gonogo.sh` - run on the RTX 4090 pod for the go/no-go check.
- `blender/cleanup.py` - bpy mesh cleanup for image-to-3D output.
- `blender/rig.py` - auto-rigs humanoid characters (Rigify basic human, 29 bones).
- `dataset/design_examples.py` - menus, maps, characters (Luau + C#, all verified) and design specs.
