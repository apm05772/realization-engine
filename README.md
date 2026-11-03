# Realization Engine — computational algebraic geometry in SageMath

**Realization Engine** is a research-oriented SageMath framework for studying **projective incidence configurations and their algebraic realization spaces**. The core provides exact projective and combinatorial methods, symbolic realization charts, algebraic elimination and saturation, and structured records of computational evidence. Optional satellites extend it with arithmetic and numerical tools, finite-field methods, and algebraic-curve computations, including **elliptic and genus-two curves**.

This repository contains a deliberately reduced, research-neutral software core derived from a larger private workspace. It does not publish new mathematical results, application-specific experiments, or a complete research archive.

## Contents

- `realization_engine_base.py` — projective models, dependent triples and flats, chart compilation, symbolic elimination, saturation, basic exact realization validation, model manifests and evidence bookkeeping.
- `satellites/` — optional arithmetic, curve, elliptic-curve, finite-field, genus-2, numerical and p-adic utilities, each registered through a common hook interface.
- `tests/` — standalone static checks and elementary *synthetic* SageMath smoke tests.

There are **no research datasets, actual arrangement-specific fixtures, results, proof drafts, experimental notebooks, certificates, numerical outputs or binary checkpoints** in this repository. There is no claim that any open mathematical problem is solved by this code.

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

Some algorithms and satellite interfaces are experimental, and SageMath or optional-library version differences may require adaptation. The original private workspace included application-specific regression tests; the public distribution replaces them with small synthetic tests, so it is **not regression-equivalent to the private research environment**. No full runtime or cross-version compatibility guarantee is made.

## Publication scope

This repository is a software portfolio artifact. It deliberately excludes ongoing mathematical work and does not document unpublished conclusions. To apply the engine to a specific mathematical problem, supply your own incidence model and independently check your results.

No open-source license has been selected. Until one is added by the author, standard copyright restrictions apply.
