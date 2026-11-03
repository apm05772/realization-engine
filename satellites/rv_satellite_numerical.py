"""Numerical algebraic-geometry satellite for Realization Engine v3.

The default backend is scipy least_squares. PHCpack/phcpy is exposed as a
capability hook but is deliberately not treated as a proof-producing backend.
"""


def register(engine):
    rv_make_evidence = engine["rv_make_evidence"]

    def backend_status():
        out = {}
        try:
            import numpy as np
            out["numpy"] = getattr(np, "__version__", True)
        except Exception:
            out["numpy"] = False
        try:
            import scipy
            out["scipy"] = getattr(scipy, "__version__", True)
        except Exception:
            out["scipy"] = False
        try:
            import phcpy
            out["phcpy"] = getattr(phcpy, "__version__", True)
        except Exception:
            out["phcpy"] = False
        return out

    def chart_least_squares(system, starts=30, scale=2.0, seed=0,
                            residual_tolerance=1e-10,
                            forbidden_tolerance=1e-8,
                            max_nfev=5000):
        import random
        try:
            import numpy as np
            from scipy.optimize import least_squares
            from sage.ext.fast_callable import fast_callable
        except Exception as exc:
            return {
                "status": "numerical backend unavailable", "reason": str(exc),
                "evidence": rv_make_evidence("INCONCLUSIVE", claim="numerical backend unavailable"),
            }
        engine["rv_validate_chart_contract"](system, strict_fingerprint=False)
        R = system["ring"]
        variables = tuple(R.gens())
        closure_fc = [fast_callable(R(f), vars=variables, domain=engine["RDF"])
                      for f in system["closure_polynomials"]]
        open_fc = [fast_callable(R(g), vars=variables, domain=engine["RDF"])
                   for g in system.get("open_conditions", system["forbidden_polynomials"])]
        rng = random.Random(int(seed))
        best = None
        accepted = []

        def residual(x):
            try:
                return np.array([float(f(*x)) for f in closure_fc], dtype=float)
            except Exception:
                return np.full(len(closure_fc), 1e100, dtype=float)

        for start in range(int(starts)):
            x0 = np.array([rng.uniform(-float(scale), float(scale)) for _ in variables])
            try:
                if closure_fc:
                    fit = least_squares(residual, x0, max_nfev=int(max_nfev))
                    x = np.array(fit.x, dtype=float)
                    res = residual(x)
                    max_residual = float(np.max(np.abs(res))) if len(res) else 0.0
                else:
                    x = x0
                    max_residual = 0.0
                open_values = [abs(float(g(*x))) for g in open_fc]
                min_open = min(open_values) if open_values else float("inf")
            except Exception:
                continue
            row = {
                "start": start,
                "assignment": tuple(float(v) for v in x),
                "max_closure_residual": max_residual,
                "min_abs_open_condition": min_open,
            }
            score = (max_residual, -min_open)
            row["score"] = score
            if best is None or score < best["score"]:
                best = row
            if max_residual <= float(residual_tolerance) and min_open > float(forbidden_tolerance):
                accepted.append(row)
        return {
            "status": "numerical candidates found" if accepted else "no acceptable numerical candidate found",
            "accepted": tuple(accepted),
            "best_candidate": best,
            "backend": backend_status(),
            "evidence": rv_make_evidence(
                "NUMERICAL_EVIDENCE" if accepted else "INCONCLUSIVE",
                claim="numerical search for the exact-matroid open locus",
                method="scipy least_squares on chart closure equations",
                payload={"starts": int(starts), "accepted": len(accepted)},
                caveats=(
                    "Numerical zeros are not exact realization certificates.",
                    "Failure of randomized optimization is not evidence of non-realizability.",
                ),
            ),
        }

    def numerical_jacobian_rank(system, assignment, tolerance=1e-9):
        try:
            import numpy as np
            from sage.ext.fast_callable import fast_callable
        except Exception as exc:
            return {"status": "backend unavailable", "reason": str(exc),
                    "evidence": rv_make_evidence("INCONCLUSIVE", claim="numerical Jacobian unavailable")}
        R = system["ring"]
        vars_ = tuple(R.gens())
        values = [float(assignment[v]) if isinstance(assignment, dict) else float(assignment[i])
                  for i, v in enumerate(vars_)]
        J = engine["rv_jacobian_matrix"](system["closure_polynomials"])
        numeric = []
        for row in J.rows():
            numeric.append([
                float(fast_callable(R(entry), vars=vars_, domain=engine["RDF"])(*values))
                for entry in row
            ])
        A = np.array(numeric, dtype=float)
        singular_values = np.linalg.svd(A, compute_uv=False) if A.size else np.array([])
        rank = int(np.sum(singular_values > float(tolerance)))
        return {
            "status": "computed",
            "rank": rank,
            "tangent_dimension_estimate": len(vars_) - rank,
            "singular_values": tuple(float(x) for x in singular_values),
            "tolerance": float(tolerance),
            "evidence": rv_make_evidence(
                "NUMERICAL_EVIDENCE", claim="numerical Jacobian-rank estimate",
                method="SVD", caveats=("Rank depends on the numerical tolerance.",),
            ),
        }


    def nag_random_slice(system, expected_dimension, seed=0, coefficient_bound=7):
        """Prepare exact random affine slices for witness-set computations.

        This does not solve the sliced system. It creates a reproducible square-ish
        system that can be exported to PHCpack/Bertini/HomotopyContinuation.
        """
        import random
        engine["rv_validate_chart_contract"](system, strict_fingerprint=False)
        R = system["ring"]
        vars_ = tuple(R.gens())
        d = int(expected_dimension)
        if d < 0 or d > len(vars_):
            raise ValueError("expected_dimension outside 0..n_variables")
        rng = random.Random(int(seed))
        slices = []
        for j in range(d):
            coeffs = [rng.randint(-int(coefficient_bound), int(coefficient_bound)) for _ in vars_]
            while not any(coeffs):
                coeffs = [rng.randint(-int(coefficient_bound), int(coefficient_bound)) for _ in vars_]
            constant = rng.randint(-int(coefficient_bound), int(coefficient_bound))
            L = R(constant)
            for a, x in zip(coeffs, vars_):
                L += R(a) * x
            slices.append(L)
        equations = tuple(system["closure_polynomials"]) + tuple(slices)
        return {
            "status": "prepared",
            "expected_dimension": d,
            "seed": int(seed),
            "slices": tuple(slices),
            "equations": equations,
            "variables": vars_,
            "evidence": rv_make_evidence(
                "SYMBOLIC_EVIDENCE",
                claim="exact reproducible affine slices prepared for numerical witness computation",
                method="random integer linear slices",
                exact=True,
                caveats=("A numerical solver must still compute and track the witness points.",),
            ),
        }

    def export_polynomial_system(system_or_equations, path=None, format="phc"):
        """Export equations in a simple text representation for external NAG tools."""
        fmt = str(format).lower()
        if isinstance(system_or_equations, dict) and "closure_polynomials" in system_or_equations:
            equations = tuple(system_or_equations["closure_polynomials"])
            variables = tuple(system_or_equations["ring"].gens())
        else:
            equations = tuple(system_or_equations)
            variables = tuple(equations[0].parent().gens()) if equations else ()
        def poly_text(f):
            txt = str(f)
            if fmt in ("phc", "phcpack"):
                return txt + ";"
            if fmt in ("bertini", "bertini2"):
                return txt + ";"
            return txt
        body = "\n".join(poly_text(f) for f in equations)
        header = "# variables: {}\n".format(", ".join(str(v) for v in variables))
        text = header + body + ("\n" if body else "")
        if path is not None:
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(text)
        return {
            "status": "exported" if path is not None else "rendered",
            "format": fmt,
            "path": path,
            "variables": variables,
            "equation_count": len(equations),
            "text": text,
            "evidence": rv_make_evidence(
                "SYMBOLIC_EVIDENCE",
                claim="polynomial system serialized for an external numerical backend",
                method="text export", exact=True,
                caveats=("External solver syntax can vary by version; inspect the exported text before running it.",),
            ),
        }

    def phc_hook_status():
        status = backend_status()
        return {
            "status": "available" if status.get("phcpy") else "unavailable",
            "backend": status,
            "note": (
                "PHCpack is intentionally exposed as a hook only. Add a project-specific adapter "
                "once the target polynomial-system format and witness-set workflow are fixed."
            ),
            "evidence": rv_make_evidence("INCONCLUSIVE", claim="PHC backend capability check"),
        }

    actions = {
        "numerical_backend_status": backend_status,
        "numerical_chart_search": chart_least_squares,
        "numerical_jacobian_rank": numerical_jacobian_rank,
        "nag_random_slice": nag_random_slice,
        "export_polynomial_system": export_polynomial_system,
        "phc_hook_status": phc_hook_status,
    }
    return engine["rv_register_satellite"](
        "numerical", "3.1.0", actions,
        description="Numerical chart solving, Jacobian diagnostics, and NAG backend hooks.",
        capabilities=backend_status(),
    )
