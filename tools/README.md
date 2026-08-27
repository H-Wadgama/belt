# Separation assistant tool

A tool to help in designing separation processes for chemicals
Currently only implements binary distillation (similar to DISTWU in Aspen)

Full documentation of every module and function in `tools/chopper/` (plus
the merged `separation_rag_agent.py`) lives in `tools/separation_tool.md`
— this file only gives a quick example and run instructions. The
engineering-specification requirements the natural-language tools enforce
(essential inputs that are never silently assumed, Wankat's Case A-D
design specifications) come from `tools/binary-distillation-context.md`.


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
(kmol/hr or kg/hr), a column pressure, the feed's thermal condition
(temperature, vapor fraction, or enthalpy), confirmation that reflux is
saturated liquid, and either a specific reflux ratio or a purity/recovery
target. None of these are ever defaulted for you (no bubble point, no 1
atm, no assumed reflux condition) — the model will ask a follow-up for
whichever of these it doesn't have yet. You don't need to repeat earlier
answers on a follow-up turn; the tool remembers everything already given
about the current separation problem. See `tools/separation_tool.md` for
the full input/output reference, including the two tools available
(`design_separation_case` for a specific reflux ratio, `optimize_separation`
for a cost search) and the deterministic Wankat Case A-D input checks
behind both.

---

## Workflow-only mode (no calculations)

`tools/chopper/binary_distillation_workflow_agent.py` runs a separate,
isolated agent that only checks whether a binary-distillation problem is
completely specified and reports which Wankat Case (A-D) it matches and
what a designer would calculate — it never builds a feed stream or calls
BioSTEAM. See `tools/binary-distillation-workflow.md` for the full spec
and the "`binary_distillation_workflow.py` + `binary_distillation_workflow_agent.py`"
section of `tools/separation_tool.md` for the implementation reference.

```bash
conda activate pyfuel
cd "tools/chopper"
python binary_distillation_workflow_agent.py
```

**If you're testing this at the terminal, run this agent, not
`separation_agent.py` or `separation_rag_agent.py`.** Those two still run
the real BioSTEAM sizing/costing once a spec is complete — that's their
job — so they're the wrong place to check problem-definition/case-routing
behavior (e.g. "does it still default to Case A", "does it stop before
calculating") in isolation. `binary_distillation_workflow_agent.py` can
never perform a calculation (`calculation_performed` is always `False`),
so there's no ambiguity about which behavior you're seeing, and it doesn't
even need `biosteam` to be importable. See "Which agent to test against"
in `tools/separation_tool.md` for the full comparison across all four chat
entry points in this repo.

---

# `tools/chopperRAG/` — separate tool for RAG to get heuristics from process design text books


Currently under development, but the idea is to store chunks of textbooks, and raw heuristics, and then based on this,
the LLM recommends a specific separation system (like distillation if relative volatility difference between components is a certain amount, etc)

