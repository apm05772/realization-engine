"""Generic arithmetic satellite for Realization Engine v3."""


def register(engine):
    rv_make_evidence = engine["rv_make_evidence"]
    QQ = engine["QQ"]

    def rational_zero_dimensional(system, max_solutions=None):
        result = engine["rv_rational_points_zero_dimensional"](
            system, max_solutions=max_solutions
        )
        out = dict(result)
        status = str(out.get("status", "")).lower()
        exact_success = (
            "zero-dimensional" in status
            or "rational" in status
            or bool(out.get("solutions"))
        )
        out["evidence"] = rv_make_evidence(
            "EXACT_CERTIFICATE" if exact_success else "INCONCLUSIVE",
            claim=out.get("status", "zero-dimensional rational-point computation"),
            method="exact Sage zero-dimensional variety/rational-point enumeration",
            exact=True,
            caveats=(
                "Interpret only when the routine confirms the closure ideal is zero-dimensional; open-condition validation is still required for exact matroid realizations.",
            ),
        )
        return out

    def rational_specialization_search(system, solve_variables=None, height=2,
                                       trials=500, max_solutions=5, seed=0):
        result = engine["rv_search_rational_specializations"](
            system,
            solve_variables=solve_variables,
            height=height,
            trials=trials,
            max_solutions=max_solutions,
            seed=seed,
        )
        out = dict(result)
        found = bool(out.get("solutions") or out.get("candidates")) or "found" in str(out.get("status", "")).lower()
        out["evidence"] = rv_make_evidence(
            "HEURISTIC_SEARCH" if found else "INCONCLUSIVE",
            claim=out.get("status", "bounded rational specialization search"),
            method="bounded-height specialization",
            payload={"height": int(height), "trials": int(trials)},
            caveats=(
                "Failure of a bounded-height/random specialization search is not evidence of absence of rational points.",
                "Any returned candidate must pass complete exact-matroid validation.",
            ),
        )
        return out

    def number_field_from_polynomial(poly, name="a"):
        try:
            K = engine["NumberField"](poly, name)
            return {
                "status": "constructed",
                "field": K,
                "degree": int(K.degree()),
                "defining_polynomial": K.defining_polynomial(),
                "evidence": rv_make_evidence(
                    "EXACT_CERTIFICATE",
                    claim="exact number field constructed from defining polynomial",
                    method="Sage NumberField", exact=True,
                ),
            }
        except Exception as exc:
            return {
                "status": "failed", "reason": str(exc),
                "evidence": rv_make_evidence("INCONCLUSIVE", claim="number-field construction failed"),
            }

    def reconstruct_rationals(values, max_denominator=1000, tolerance=1e-10):
        """Heuristically reconstruct nearby rationals from numerical values."""
        rows = []
        for value in values:
            try:
                q = QQ(float(value)).nearby_rational(max_denominator=max_denominator)
            except Exception:
                # Conservative fallback using Python Fraction; still heuristic.
                from fractions import Fraction
                fr = Fraction(float(value)).limit_denominator(int(max_denominator))
                q = QQ(fr.numerator) / QQ(fr.denominator)
            err = abs(float(q) - float(value))
            rows.append({"value": float(value), "rational": q, "error": err, "accepted": err <= float(tolerance)})
        return {
            "status": "reconstructed",
            "rows": tuple(rows),
            "all_within_tolerance": all(r["accepted"] for r in rows),
            "evidence": rv_make_evidence(
                "HEURISTIC_SEARCH",
                claim="numerical values approximated by bounded-denominator rationals",
                method="rational reconstruction",
                caveats=("A reconstructed rational tuple is only a guess until substituted and validated exactly.",),
            ),
        }

    def local_solubility_hook(*args, **kwargs):
        return {
            "status": "hook only",
            "note": (
                "Local-solubility algorithms depend strongly on the resulting curve/variety class. "
                "Attach genus-/model-specific implementations here rather than placing them in the core."
            ),
            "evidence": rv_make_evidence("INCONCLUSIVE", claim="generic local-solubility hook not instantiated"),
        }

    actions = {
        "rational_zero_dimensional": rational_zero_dimensional,
        "rational_specialization_search": rational_specialization_search,
        "number_field_from_polynomial": number_field_from_polynomial,
        "reconstruct_rationals": reconstruct_rationals,
        "local_solubility_hook": local_solubility_hook,
    }
    return engine["rv_register_satellite"](
        "arithmetic", "3.1.0", actions,
        description="Generic rational-point searches, number fields, rational reconstruction, and local-arithmetic hooks.",
        capabilities={"exact_zero_dimensional": True, "number_fields": True, "local_solubility": "hook"},
    )
