"""Finite-field and reduction satellite for Realization Engine v3."""


def register(engine):
    rv_make_evidence = engine["rv_make_evidence"]
    GF = engine["GF"]
    QQ = engine["QQ"]

    def finite_field_batch(model, primes=(2,3,5,7,11), max_assignments=1000000,
                           stop_on_first_realization=False, frame=None):
        rows = []
        for p in primes:
            p = int(p)
            try:
                row = engine["rv_finite_field_search"](
                    model, p=p, frame=frame, max_assignments=max_assignments
                )
            except Exception as exc:
                row = {"status": "error", "error": str(exc), "p": p}
            row = dict(row)
            row["p"] = p
            rows.append(row)
            status = str(row.get("status", "")).lower()
            if stop_on_first_realization and "found" in status:
                break
        exhaustive_negative = [
            r for r in rows
            if bool(r.get("exhaustive", False)) and (
                "no" in str(r.get("status", "")).lower()
                or "none" in str(r.get("status", "")).lower()
            )
        ]
        return {
            "rv_type": "finite_field_batch",
            "rows": tuple(rows),
            "exhaustive_negative_primes": tuple(r["p"] for r in exhaustive_negative),
            "evidence": rv_make_evidence(
                "EXHAUSTIVE_FINITE_SEARCH" if exhaustive_negative else "SYMBOLIC_EVIDENCE",
                claim="finite-field realization profile",
                method="bounded/exhaustive search over GF(p)",
                payload={"primes": tuple(int(p) for p in primes)},
                exact=True,
                exhaustive=bool(exhaustive_negative),
                caveats=(
                    "Failure at finitely many primes does not by itself prove non-realizability over Q; bad reduction can occur.",
                ),
            ),
        }

    def reduce_rational_realization(model, points, p):
        p = int(p)
        F = GF(p)
        if not isinstance(points, dict):
            points = {i: tuple(P) for i, P in enumerate(points)}
        reduced = {}
        bad_denominators = []
        for i in range(model["n"]):
            coords = []
            for x in points[i]:
                q = QQ(x)
                den = int(q.denominator())
                if den % p == 0:
                    bad_denominators.append((i, q))
                    coords = None
                    break
                coords.append(F(int(q.numerator())) / F(den))
            if coords is not None:
                if all(c == 0 for c in coords):
                    return {
                        "status": "bad reduction", "p": p,
                        "reason": "projective point reduced to zero vector",
                        "evidence": rv_make_evidence("INCONCLUSIVE", claim="bad reduction at p={}".format(p)),
                    }
                reduced[i] = tuple(coords)
        if bad_denominators:
            return {
                "status": "bad reduction", "p": p,
                "bad_denominators": tuple(bad_denominators),
                "evidence": rv_make_evidence("INCONCLUSIVE", claim="denominator obstruction to this coordinate reduction"),
            }
        cert = engine["rv_validate_realization"](model, reduced, require_exact_matroid=True)
        return {
            "status": "good exact reduction" if cert["valid"] else "reduction changed matroid",
            "p": p,
            "points": reduced,
            "certificate": cert,
            "evidence": rv_make_evidence(
                "EXACT_CERTIFICATE" if cert["valid"] else "LOCAL_OBSTRUCTION",
                claim="exact reduction of supplied Q-realization modulo p",
                method="coordinate reduction and complete determinant validation",
                exact=True, exhaustive=True,
            ),
        }

    def reduction_profile(model, points, primes=(2,3,5,7,11,13,17,19)):
        rows = [reduce_rational_realization(model, points, p) for p in primes]
        return {
            "status": "reduction profile",
            "rows": tuple(rows),
            "good_primes": tuple(r["p"] for r in rows if r["status"] == "good exact reduction"),
            "bad_primes": tuple(r["p"] for r in rows if r["status"] != "good exact reduction"),
            "evidence": rv_make_evidence(
                "EXACT_CERTIFICATE", claim="exact reduction behavior of a supplied rational realization",
                method="finite-field determinant validation", exact=True,
            ),
        }

    actions = {
        "finite_field_batch": finite_field_batch,
        "reduce_rational_realization": reduce_rational_realization,
        "reduction_profile": reduction_profile,
    }
    return engine["rv_register_satellite"](
        "finite_fields", "3.1.0", actions,
        description="Batch GF(p) realization searches and exact reduction checks.",
        capabilities={"exact": True, "finite_fields": True, "local_screening": True},
    )
