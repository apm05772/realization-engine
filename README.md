# Realization Engine — computational algebraic geometry in SageMath

**Realization Engine** is a research-oriented SageMath framework for studying **projective incidence configurations and their algebraic realization spaces**. The core provides exact projective and combinatorial methods, symbolic realization charts, algebraic elimination and saturation, and structured records of computational evidence. Optional satellites extend it with arithmetic and numerical tools, finite-field methods, and algebraic-curve computations, including **elliptic and genus-two curves**.

The structure is divided into several parts: the engine, satellites, and tests. Explanations for each are below. This is essentially a toolbox, meant to showcase what I used in my own personal research and potentially aid others in their own tasks. 

## Contents

- `realization_engine_base.py` — projective models, dependent triples and flats, chart compilation, symbolic elimination, saturation, basic exact realization validation, model manifests and evidence bookkeeping.
- `satellites/` — optional arithmetic, curve, elliptic-curve, finite-field, genus-2, numerical and p-adic utilities, each registered through a common hook interface.
- `tests/` — standalone static checks and elementary *synthetic* SageMath smoke tests.

While all of these tools are included, there's no guarantee of a proper result emerging from this. Hence why it is important to be careful when using these tools and claiming to see a result; it should be properly verified before making such a claim.

## Requirements

- SageMath with Python 3 (the core imports `sage.all` and **cannot run with plain Python**).
- The numerical satellite optionally uses `numpy`, `scipy`, and/or `phcpy`; if missing, its numeric functionality is unavailable, while the exact core can still load.
- Some arithmetic functions depend on additional Sage interfaces or external packages. Backend availability should be checked individually.

## Quick start

From the repository root, in a SageMath Python environment:

```python
exec(open("realization_engine_base.py", encoding="utf-8").read())
rv_initialize(load_satellites=True)
model = rv_make_model(5, flats=[(1, 3, 4)], name="toy")
print(rv_model_metrics(model))
```

Or from a shell:

```sh
python3 tests/static_check.py  # syntax and layout only; no Sage required
sage -python tests/smoke.py # executes generic SageMath tests
```

`rv_dispatch(action, ..., provider="name")` invokes a registered satellite action. Discover available hooks using `rv_list_satellites()`.

## Interpretation and limitations

The core represents primal lines as points of the **dual projective plane**, and intersection multiplicities as collinear flats. It keeps combinatorial incidence conditions separate from the vanishing equations and nonvanishing conditions of a realization chart. Existence of a numerical approximation, success of a finite-field search or failure of a bounded search is **not** a proof over the rationals. Evidence-level labels are bookkeeping conventions; they are **not independent mathematical verification**.

Some algorithms and satellite interfaces are experimental, and SageMath or optional-library version differences may require adaptation.

## AI Usage

The engine and satellites are **AI-ASSISTED**, especially the code-writing and error-management. I am not claiming to have done it all myself. Even while **AI-ASSISTED**, I have personally verified the code to the best of my ability. Obviously, if any errors are present, open an issue and let me know. I'll be happy to read and fix the code if necessary. 


No open-source license has been selected. Until one is added by the author, standard copyright restrictions apply.
