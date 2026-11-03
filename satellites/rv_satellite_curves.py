"""General algebraic-curve diagnostics satellite for Realization Engine v3."""


def register(engine):
    rv_make_evidence = engine["rv_make_evidence"]

    def plane_curve_report(poly, compute_genus=True, compute_singularities=False):
        Curve = engine.get("Curve")
        out = {
            "rv_type": "plane_curve_report",
            "polynomial": poly,
            "factorization": tuple(poly.factor()),
            "curve": None,
            "genus": None,
            "singularities": None,
            "errors": [],
        }
        if Curve is None:
            out["errors"].append(("curve", "Sage Curve constructor unavailable"))
        else:
            try:
                C = Curve(poly)
                out["curve"] = C
                if compute_genus:
                    for method in ("genus", "geometric_genus"):
                        if hasattr(C, method):
                            try:
                                out["genus"] = int(getattr(C, method)())
                                break
                            except Exception:
                                pass
                if compute_singularities:
                    for method in ("singular_points", "singularities"):
                        if hasattr(C, method):
                            try:
                                out["singularities"] = tuple(getattr(C, method)())
                                break
                            except Exception:
                                pass
            except Exception as exc:
                out["errors"].append(("curve", str(exc)))
        out["evidence"] = rv_make_evidence(
            "SYMBOLIC_EVIDENCE",
            claim="plane-curve structural diagnostics",
            method="exact Sage factorization/curve methods",
            exact=True,
            caveats=("Genus/singularity fields may be unavailable for some Sage curve representations.",),
        )
        return out

    def component_report(polys):
        polys = tuple(polys)
        rows = []
        for i, f in enumerate(polys):
            rows.append({
                "index": i,
                "degree": int(f.total_degree()) if hasattr(f, "total_degree") else None,
                "factorization": tuple(f.factor()),
            })
        return {
            "status": "factored generators",
            "rows": tuple(rows),
            "evidence": rv_make_evidence(
                "SYMBOLIC_EVIDENCE",
                claim="generator factorization report",
                method="exact polynomial factorization", exact=True,
                caveats=("Factoring generators is not the same as primary decomposition of the ideal.",),
            ),
        }

    def primary_decomposition_hook(system):
        R = system["ring"]
        I = R.ideal(list(system["closure_polynomials"]))
        for method in ("primary_decomposition", "associated_primes"):
            if hasattr(I, method):
                try:
                    data = getattr(I, method)()
                    return {
                        "status": "computed",
                        "method": method,
                        "data": data,
                        "evidence": rv_make_evidence(
                            "SYMBOLIC_EVIDENCE",
                            claim="ideal component diagnostic",
                            method=method, exact=True,
                            caveats=("Interpret component output in the presence of open nondegeneracy conditions.",),
                        ),
                    }
                except Exception as exc:
                    last = str(exc)
        return {
            "status": "unavailable",
            "reason": locals().get("last", "no decomposition method exposed by this Sage ideal backend"),
            "evidence": rv_make_evidence("INCONCLUSIVE", claim="primary-decomposition hook unavailable"),
        }

    actions = {
        "plane_curve_report": plane_curve_report,
        "component_report": component_report,
        "primary_decomposition": primary_decomposition_hook,
    }
    return engine["rv_register_satellite"](
        "curves", "3.1.0", actions,
        description="Plane-curve genus/singularity diagnostics and ideal-component hooks.",
        capabilities={"exact": True, "curves": True, "primary_decomposition": "backend-dependent"},
    )
