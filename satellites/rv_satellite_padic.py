"""p-adic/Hensel hooks for Realization Engine v3."""


def register(engine):
    rv_make_evidence = engine["rv_make_evidence"]

    def hensel_univariate(f, p, residue, precision=30):
        p = int(p)
        precision = int(precision)
        try:
            Zp = engine["Zp"]
            K = Zp(p, prec=precision)
            R = f.parent()
            xgen = R.gen() if R.ngens() == 1 else None
            if xgen is None:
                raise ValueError("hensel_univariate requires a univariate polynomial")
            df = f.derivative(xgen)
            a = K(int(residue))
            # Simple-root Hensel condition modulo p.
            if int(engine["ZZ"](f(int(residue))) % p) != 0:
                raise ValueError("residue is not a root modulo p")
            if int(engine["ZZ"](df(int(residue))) % p) == 0:
                raise ValueError("derivative vanishes modulo p; simple-root Hensel does not apply")
            # Newton iteration in Q_p/Z_p.
            for _ in range(max(8, precision.bit_length() + 2)):
                fa = K(f(a))
                dfa = K(df(a))
                a = a - fa / dfa
            return {
                "status": "lifted",
                "p": p,
                "precision": precision,
                "root": a,
                "evidence": rv_make_evidence(
                    "EXACT_CERTIFICATE",
                    claim="simple mod-p root lifted p-adically by Hensel/Newton",
                    method="simple-root Hensel lemma", exact=True,
                    caveats=("The returned p-adic expansion is finite-precision representation of the unique lifted root.",),
                ),
            }
        except Exception as exc:
            return {
                "status": "lift failed", "reason": str(exc),
                "evidence": rv_make_evidence("INCONCLUSIVE", claim="p-adic lift failed"),
            }

    def multivariate_hensel_hook(*args, **kwargs):
        return {
            "status": "hook only",
            "note": (
                "General multivariate Hensel lifting is intentionally not hard-coded in the core. "
                "Attach a project-specific solver once the square system / Jacobian nonsingularity conditions are fixed."
            ),
            "evidence": rv_make_evidence("INCONCLUSIVE", claim="multivariate p-adic hook not instantiated"),
        }

    actions = {
        "hensel_univariate": hensel_univariate,
        "multivariate_hensel_hook": multivariate_hensel_hook,
    }
    return engine["rv_register_satellite"](
        "padic", "3.1.0", actions,
        description="Simple-root Hensel lifting and extension point for multivariate p-adic methods.",
        capabilities={"exact": True, "univariate_hensel": True, "multivariate_hensel": "hook"},
    )
