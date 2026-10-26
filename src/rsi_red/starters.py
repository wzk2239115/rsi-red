"""Export editable CPU training starters; production frameworks plug into job entrypoints."""
import json
from pathlib import Path

METHODS = {"sft", "grpo", "env_rl", "self_distill", "merge"}


def create(method, output):
    if method not in METHODS:
        raise ValueError("unsupported starter")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    recipe = {"method": method, "weights": [0.0], "teacher_weights": [2.0],
              "rows": [{"x": [-1.0], "label": 0}, {"x": [1.0], "label": 1}],
              "steps": 120, "learning_rate": .2, "seed": 42,
              "parents": [[1.0], [2.0]], "coefficients": [.5, .5], "output": str(output / "model")}
    (output / "recipe.json").write_text(json.dumps(recipe, indent=2))
    (output / "train.py").write_text('"""Editable simulation entrypoint: CPU linear policy, not LLM training."""\n'
                                     'from rsi_red.simulation import main\n\nif __name__ == "__main__":\n    main()\n')
    (output / "README.md").write_text("# CPU simulation starter\n\n"
        "This trains a small binary linear policy, not an LLM. Edit train.py or replace it with your own trainer.\n"
        "Run: python train.py --config recipe.json\n")
    return output
