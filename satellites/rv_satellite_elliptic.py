"""Elliptic/arithmetic-curve satellite for Realization Engine v3.1.1."""


def register(engine):
    QQ = engine["QQ"]
    ZZ = engine["ZZ"]
    EllipticCurve = engine["EllipticCurve"]
    PolynomialRing = engine["PolynomialRing"]
    Curve = engine.get("Curve")
    EllipticCurve_from_cubic = engine.get("EllipticCurve_from_cubic")
    rv_make_evidence = engine["rv_make_evidence"]

    def _coerce_curve(curve_or_ainvs):
        if hasattr(curve_or_ainvs, "ainvs"):
            return curve_or_ainvs
        return EllipticCurve(QQ, list(curve_or_ainvs))

    def _proof_arithmetic_flag():
        try:
            proof_obj = engine.get("proof")
            if proof_obj is not None:
                return bool(proof_obj.arithmetic())
        except Exception:
            pass
        return None

    def elliptic_report(curve_or_ainvs, compute_rank=True, compute_generators=True,
                        compute_torsion=True, compute_conductor=True):
        E = _coerce_curve(curve_or_ainvs)
        out = {
            "rv_type": "elliptic_report",
            "curve": E,
            "ainvs": tuple(E.ainvs()),
            "discriminant": E.discriminant(),
            "rank": None,
            "rank_bounds": None,
            "generators": None,
            "torsion_subgroup": None,
            "torsion_points": None,
            "conductor": None,
            "errors": [],
        }
        proof_flag = _proof_arithmetic_flag()
        out["proof_arithmetic"] = proof_flag
        if compute_conductor:
            try:
                out["conductor"] = E.conductor()
            except Exception as exc:
                out["errors"].append(("conductor", str(exc)))
        if compute_rank:
            try:
                out["rank"] = int(E.rank())
            except Exception as exc:
                out["errors"].append(("rank", str(exc)))
            try:
                out["rank_bounds"] = tuple(int(x) for x in E.rank_bounds())
            except Exception as exc:
                out["errors"].append(("rank_bounds", str(exc)))
        if compute_generators:
            try:
                out["generators"] = tuple(E.gens())
            except Exception as exc:
                out["errors"].append(("generators", str(exc)))
        if compute_torsion:
            try:
                out["torsion_subgroup"] = E.torsion_subgroup()
                out["torsion_points"] = tuple(E.torsion_points())
            except Exception as exc:
                out["errors"].append(("torsion", str(exc)))
        level = "EXACT_CERTIFICATE" if not out["errors"] and proof_flag is not False else "SYMBOLIC_EVIDENCE"
        caveats = []
        if proof_flag is False:
            caveats.append("Sage arithmetic proof flag is disabled; rank-related statements may be conditional.")
        if out["errors"]:
            caveats.append("Some requested elliptic invariants failed to compute.")
        out["evidence"] = rv_make_evidence(
            level,
            claim="elliptic-curve arithmetic report",
            method="Sage elliptic-curve arithmetic",
            payload={
                "rank": out["rank"],
                "rank_bounds": out["rank_bounds"],
                "torsion_order": int(out["torsion_subgroup"].order()) if out["torsion_subgroup"] is not None else None,
                "discriminant": str(out["discriminant"]),
                "conductor": str(out["conductor"]) if out["conductor"] is not None else None,
            },
            caveats=tuple(caveats), exact=True,
        )
        return out

    def _homogenize_affine_cubic(poly):
        R = poly.parent()
        gens = tuple(R.gens())
        if len(gens) != 2:
            raise ValueError("affine cubic homogenization requires a 2-variable polynomial ring")
        if poly.total_degree() != 3:
            raise ValueError("plane_cubic_to_elliptic requires total degree exactly 3")
        S = PolynomialRing(QQ, names=("rv_ec_X", "rv_ec_Y", "rv_ec_Z"))
        X, Y, Z = S.gens()
        G = S(0)
        for mon, coeff in poly.dict().items():
            i, j = mon
            G += QQ(coeff) * X**i * Y**j * Z**(3 - i - j)
        return S, G

    def _projective_cubic(poly):
        R = poly.parent()
        gens = tuple(R.gens())
        if len(gens) == 2:
            S, G = _homogenize_affine_cubic(poly)
            return {
                "source_kind": "affine",
                "source_polynomial": poly,
                "projective_ring": S,
                "homogeneous_cubic": G,
            }
        if len(gens) == 3:
            G = R(poly)
            if G.total_degree() != 3:
                raise ValueError("plane_cubic_to_elliptic requires total degree exactly 3")
            if not G.is_homogeneous():
                raise ValueError("3-variable cubic input must be homogeneous")
            return {
                "source_kind": "projective",
                "source_polynomial": poly,
                "projective_ring": R,
                "homogeneous_cubic": G,
            }
        raise ValueError("plane_cubic_to_elliptic expects a 2-variable affine or 3-variable projective cubic")

    def _primitive_projective_points(bound):
        from math import gcd
        seen = set()
        B = int(bound)
        for a in range(-B, B + 1):
            for b in range(-B, B + 1):
                for c in range(-B, B + 1):
                    if a == 0 and b == 0 and c == 0:
                        continue
                    g = gcd(gcd(abs(a), abs(b)), abs(c))
                    if g != 1:
                        continue
                    t = (a, b, c)
                    # Canonical projective sign.
                    first = next(x for x in t if x != 0)
                    if first < 0:
                        t = tuple(-x for x in t)
                    if t in seen:
                        continue
                    seen.add(t)
                    yield tuple(QQ(x) for x in t)

    def _nonsingular_on_cubic(G, P):
        if G(*P) != 0:
            return False
        grads = [G.derivative(x)(*P) for x in G.parent().gens()]
        return any(v != 0 for v in grads)

    def _elliptic_homogeneous_equation(E, ring):
        x, y, z = ring.gens()
        a1, a2, a3, a4, a6 = E.ainvs()
        return ring(
            y**2*z + a1*x*y*z + a3*y*z**2
            - x**3 - a2*x**2*z - a4*x*z**2 - a6*z**3
        )

    def _verify_cubic_morphisms(G, phi, psi, E):
        out = {
            "forward_valid": False,
            "inverse_valid": False,
            "forward_pullback": None,
            "forward_quotient": None,
            "forward_remainder": None,
            "inverse_pullback": None,
            "inverse_quotient": None,
            "inverse_remainder": None,
            "errors": [],
        }
        # Cubic -> E.
        try:
            U, V, W = phi.defining_polynomials()
            S = G.parent()
            a1, a2, a3, a4, a6 = E.ainvs()
            Epb = S(
                V**2*W + a1*U*V*W + a3*V*W**2
                - U**3 - a2*U**2*W - a4*U*W**2 - a6*W**3
            )
            q, r = Epb.quo_rem(G)
            out.update({
                "forward_pullback": Epb,
                "forward_quotient": q,
                "forward_remainder": r,
                "forward_valid": bool(r == 0),
            })
        except Exception as exc:
            out["errors"].append(("forward", str(exc)))

        # E -> cubic.
        try:
            p0, p1, p2 = psi.defining_polynomials()
            RE = p0.parent()
            Gpb = RE(G(p0, p1, p2))
            Ehom = _elliptic_homogeneous_equation(E, RE)
            q, r = Gpb.quo_rem(Ehom)
            out.update({
                "inverse_pullback": Gpb,
                "inverse_quotient": q,
                "inverse_remainder": r,
                "inverse_valid": bool(r == 0),
            })
        except Exception as exc:
            out["errors"].append(("inverse", str(exc)))
        return out

    def plane_cubic_to_elliptic(poly, base_point=None, search_bound=3):
        """Convert a rational plane cubic to an elliptic curve with explicit maps.

        Accepts either an affine 2-variable cubic or a homogeneous 3-variable
        cubic.  If no rational base point is supplied, a deterministic bounded
        search for a nonsingular rational projective point is performed.
        """
        if EllipticCurve_from_cubic is None:
            return {
                "status": "unavailable",
                "reason": "Sage EllipticCurve_from_cubic constructor unavailable",
                "evidence": rv_make_evidence("INCONCLUSIVE", claim="plane cubic conversion unavailable"),
            }
        try:
            data = _projective_cubic(poly)
            G = data["homogeneous_cubic"]
            candidates = []
            if base_point is not None:
                P = tuple(QQ(x) for x in base_point)
                if len(P) != 3 or not _nonsingular_on_cubic(G, P):
                    raise ValueError("supplied base_point is not a nonsingular rational point on the projective cubic")
                candidates.append(P)
            else:
                for P in _primitive_projective_points(search_bound):
                    if _nonsingular_on_cubic(G, P):
                        candidates.append(P)
            if not candidates:
                return {
                    "status": "no rational base point found",
                    "reason": "no nonsingular rational projective point found within search_bound={}".format(search_bound),
                    "homogeneous_cubic": G,
                    "evidence": rv_make_evidence(
                        "HEURISTIC_SEARCH",
                        claim="no small rational base point found on plane cubic",
                        method="bounded primitive projective search",
                        exact=True,
                        caveats=("This does not prove that the cubic has no rational point.",),
                    ),
                }

            last_error = None
            for P in candidates:
                try:
                    phi = EllipticCurve_from_cubic(G, list(P), morphism=True)
                    E = phi.codomain()
                    psi = phi.inverse()
                    verification = _verify_cubic_morphisms(G, phi, psi, E)
                    exact = verification["forward_valid"] and verification["inverse_valid"]
                    try:
                        C = Curve(G) if Curve is not None else None
                    except Exception:
                        C = None
                    try:
                        Emin = E.global_minimal_model() if hasattr(E, "global_minimal_model") else E.minimal_model()
                    except Exception:
                        Emin = None
                    return {
                        "status": "converted",
                        "source_kind": data["source_kind"],
                        "source_polynomial": data["source_polynomial"],
                        "projective_ring": data["projective_ring"],
                        "homogeneous_cubic": G,
                        "plane_curve": C,
                        "base_point": P,
                        "forward_map": phi,
                        "inverse_map": psi,
                        "elliptic_curve": E,
                        "minimal_model": Emin,
                        "verification": verification,
                        "exact_birational_certificate": bool(exact),
                        "evidence": rv_make_evidence(
                            "EXACT_CERTIFICATE" if exact else "SYMBOLIC_EVIDENCE",
                            claim="plane cubic converted to an elliptic model with explicit rational maps",
                            method="EllipticCurve_from_cubic(..., morphism=True) plus exact pullback division",
                            exact=True,
                            caveats=() if exact else ("One or both exact pullback verifications did not complete.",),
                        ),
                    }
                except Exception as exc:
                    last_error = exc
                    continue
            return {
                "status": "conversion failed",
                "reason": str(last_error) if last_error is not None else "unknown conversion failure",
                "homogeneous_cubic": G,
                "candidate_base_points": tuple(candidates),
                "evidence": rv_make_evidence("INCONCLUSIVE", claim="plane cubic conversion failed"),
            }
        except Exception as exc:
            return {
                "status": "conversion failed",
                "reason": str(exc),
                "evidence": rv_make_evidence("INCONCLUSIVE", claim="plane cubic conversion failed"),
            }

    def rank_zero_rational_points(curve_or_ainvs, require_proof=True):
        """Certify E(Q)=E(Q)_tors when the Mordell-Weil rank is exactly zero."""
        E = _coerce_curve(curve_or_ainvs)
        proof_flag = _proof_arithmetic_flag()
        errors = []
        bounds = None
        rank = None
        torsion = None
        points = None
        try:
            bounds = tuple(int(x) for x in E.rank_bounds())
        except Exception as exc:
            errors.append(("rank_bounds", str(exc)))
        try:
            rank = int(E.rank())
        except Exception as exc:
            errors.append(("rank", str(exc)))
        try:
            torsion = E.torsion_subgroup()
            points = tuple(E.torsion_points())
        except Exception as exc:
            errors.append(("torsion", str(exc)))

        rank_zero = bounds == (0, 0) and (rank in (None, 0))
        proof_ok = (proof_flag is True) or (not require_proof)
        complete = bool(rank_zero and proof_ok and points is not None and not errors)
        caveats = []
        if require_proof and proof_flag is not True:
            caveats.append("Arithmetic proof mode is not confirmed true.")
        if not rank_zero:
            caveats.append("Rank zero was not certified by rank_bounds().")
        if errors:
            caveats.append("One or more exact arithmetic computations failed.")
        return {
            "rv_type": "rank_zero_rational_points",
            "curve": E,
            "rank": rank,
            "rank_bounds": bounds,
            "proof_arithmetic": proof_flag,
            "torsion_subgroup": torsion,
            "torsion_points": points,
            "rational_points": points if complete else None,
            "complete": complete,
            "errors": tuple(errors),
            "evidence": rv_make_evidence(
                "EXACT_CERTIFICATE" if complete else "INCONCLUSIVE",
                claim="all rational points on the elliptic curve are enumerated",
                method="rank-zero Mordell-Weil certificate plus exact torsion enumeration",
                payload={
                    "rank": rank,
                    "rank_bounds": bounds,
                    "torsion_order": int(torsion.order()) if torsion is not None else None,
                    "rational_point_count": len(points) if complete else None,
                },
                caveats=tuple(caveats), exact=True,
            ),
        }

    def verify_weierstrass_pullback(curve_poly, X_expr, Y_expr, ainvs):
        """Check that a proposed affine map lands on a Weierstrass model."""
        R = curve_poly.parent()
        E = EllipticCurve(QQ, list(ainvs))
        a1, a2, a3, a4, a6 = E.ainvs()
        relation = R(
            Y_expr**2 + a1*X_expr*Y_expr + a3*Y_expr
            - X_expr**3 - a2*X_expr**2 - a4*X_expr - a6
        )
        I = R.ideal([R(curve_poly)])
        try:
            remainder = I.reduce(relation)
        except Exception:
            try:
                remainder = relation.reduce(I.groebner_basis())
            except Exception as exc:
                return {
                    "status": "reduction failed", "reason": str(exc),
                    "relation": relation,
                    "evidence": rv_make_evidence("INCONCLUSIVE", claim="map verification failed"),
                }
        valid = remainder == 0
        return {
            "status": "verified" if valid else "not verified",
            "relation": relation,
            "remainder": remainder,
            "valid": bool(valid),
            "elliptic_curve": E,
            "evidence": rv_make_evidence(
                "EXACT_CERTIFICATE" if valid else "INCONCLUSIVE",
                claim="proposed affine map satisfies the Weierstrass equation modulo the source curve",
                method="exact ideal reduction", exact=True,
                caveats=("Forward relation is not by itself a proof of birationality.",),
            ),
        }

    def torsion_chart_candidates(curve_or_ainvs, inverse_map, excluded_test=None):
        E = _coerce_curve(curve_or_ainvs)
        rows = []
        for P in E.torsion_points():
            try:
                image = inverse_map(P)
                excluded = bool(excluded_test(image)) if excluded_test is not None and image is not None else False
                rows.append({"point": P, "image": image, "excluded": excluded})
            except Exception as exc:
                rows.append({"point": P, "image": None, "excluded": None, "error": str(exc)})
        return {
            "status": "enumerated torsion points",
            "rows": tuple(rows),
            "evidence": rv_make_evidence(
                "EXACT_CERTIFICATE", claim="torsion points mapped through supplied inverse chart",
                method="exact elliptic torsion enumeration", exact=True,
                caveats=("If the Mordell-Weil rank is positive, torsion points are not all rational points.",),
            ),
        }

    actions = {
        "elliptic_report": elliptic_report,
        "plane_cubic_to_elliptic": plane_cubic_to_elliptic,
        "rank_zero_rational_points": rank_zero_rational_points,
        "verify_weierstrass_pullback": verify_weierstrass_pullback,
        "torsion_chart_candidates": torsion_chart_candidates,
    }
    return engine["rv_register_satellite"](
        "elliptic", "3.1.1", actions,
        description="Elliptic curves, exact plane-cubic conversion, Mordell-Weil/torsion certificates, and map verification.",
        capabilities={"exact": True, "elliptic_curves": True, "plane_cubics": True, "rank_zero_certificates": True},
    )
