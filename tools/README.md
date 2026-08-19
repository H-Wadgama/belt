# Separation assistant tool

A tool to help in designing separation processes for chemicals
Currently only implements binary distillation (similar to DISTWU in Aspen)


## Example of selecting best design from candidate separations

```python
from best_design import find_best_design

best = find_best_design(econ_df)
if best['found']:
    print(best['message'])
    best['design']['reflux_ratio_k']   # the winning k
```



## Example of overall wrapper 

```python
from optimizer import optimize_reflux_ratio

result = optimize_reflux_ratio(
    feed=feed,
    LHK=('Methanol', 'Water'),
    reflux_ratios_k=[1.5, 1.75, 2.0, 2.25, 2.5],
    purity_target=0.99,
)

result['n_feasible']            # 5
result['best_design']['reflux_ratio_k']   # winning k, e.g. 1.5
result['message']               # "Best feasible design: reflux_ratio_k=1.5 ..."
```

Running `python optimizer.py` directly runs this exact example on the toy
Water/Methanol/Glycerol feed and prints the feasibility count, summary
message, `key_selection` result, and full best-design breakdown — then runs
a second demo with `LHK=('Methanol', 'Glycerol')` on the same feed (skipping
over Water) to show `validate_key_selection()` flagging the ambiguous key
choice and the resulting sweep coming back with `n_feasible=0`.

---


### How to run it

From an Anaconda Prompt (or any terminal with `conda` on `PATH`):

```bash
conda activate pyfuel
cd "tools/chopper"    # bare-import convention -- see note above

python separation_agent.py                 # interactive REPL
python separation_agent.py "Separate 80 kmol/hr methanol and 100 kmol/hr water, 99% pure methanol overhead"   # one-shot
```

**Prerequisites:**
- A local Ollama server must be running (normally automatic once Ollama
  is installed — a tray app/service; `ollama serve` in a separate terminal
  if it isn't).
- The model must be pulled once: `ollama pull qwen3:8b`.
- Run with the `pyfuel` environment's Python — that's where `ollama` and
  `biosteam` are both installed (`ollama` is not in the repo's base
  `requirements.txt`; it was added ad hoc via `pip install ollama` for
  this agent).

**Getting good results:** state real chemical names (e.g. Water,
Methanol, Ethanol, Glycerol) with explicit flow rates and units
(kmol/hr or kg/hr), and an explicit purity or recovery target — the model
will usually ask a follow-up rather than guess if these are missing,
since the tool has no default feed composition to fall back on.

---

# `tools/chopperRAG/` — separate tool for RAG to get heuristics from process design text books


Currently under development, but the idea is to store chunks of textbooks, and raw heuristics, and then based on this,
the LLM recommends a specific separation system (like distillation if relative volatility difference between components is a certain amount, etc)

