"""Genus-2 / hyperelliptic satellite for Realization Engine v3.2."""


def register(engine):
    rv_make_evidence = engine["rv_make_evidence"]
    QQ = engine["QQ"]
    ZZ = engine["ZZ"]
    PolynomialRing = engine["PolynomialRing"]
    HyperellipticCurve = engine["HyperellipticCurve"]

    def quadratic_double_cover(poly, y_var=None):
        """Extract W^2=D(X) when a bivariate plane curve is quadratic in y_var."""
        R = poly.parent()
        gens = tuple(R.gens())
        if len(gens) != 2:
            return {"status": "unsupported", "reason": "requires a bivariate polynomial ring",
                    "evidence": rv_make_evidence("INCONCLUSIVE", claim="quadratic double-cover extraction unsupported")}
        if y_var is None:
            y_var = gens[-1]
        if y_var not in gens:
            raise ValueError("y_var is not a generator of the polynomial ring")
        yi = gens.index(y_var)
        x_var = gens[1 - yi]
        if int(poly.degree(y_var)) != 2:
            return {"status": "unsupported", "reason": "polynomial is not quadratic in selected variable",
                    "evidence": rv_make_evidence("INCONCLUSIVE", claim="quadratic double-cover extraction not applicable")}
        values = list(gens)
        values[yi] = R(0)
        kill_y = R.hom(values, R)
        c = R(kill_y(poly))
        b = R(kill_y(poly.derivative(y_var)))
        a = R(kill_y(poly.derivative(y_var).derivative(y_var)) / 2)
        if a == 0:
            raise ValueError("quadratic coefficient vanished")
        w_expr = R(2*a*y_var + b)
        Dmulti = R(b**2 - 4*a*c)
        if y_var in engine["rv_poly_variables"](Dmulti):
            raise ValueError("discriminant unexpectedly depends on quadratic variable")
        S = PolynomialRing(R.base_ring(), names=("X",))
        X = S.gen()
        hom_values = [None, None]
        hom_values[1 - yi] = X
        hom_values[yi] = S(0)
        phi = R.hom(hom_values, S)
        D = S(phi(Dmulti))
        gcd = D.gcd(D.derivative())
        squarefree = bool(gcd == 1)
        H = None
        genus = None
        error = None
        if squarefree:
            try:
                H = HyperellipticCurve(D)
                genus = int(H.genus())
            except Exception as exc:
                error = str(exc)
        disc = None
        try:
            disc = D.discriminant()
        except Exception:
            pass
        ok = squarefree and H is not None
        return {
            "status": "ok" if ok else "partial",
            "source_polynomial": poly,
            "x_var": x_var, "y_var": y_var,
            "quadratic_coefficients": (a, b, c),
            "W_expression": w_expr,
            "discriminant_multivariate": Dmulti,
            "univariate_ring": S, "X": X,
            "discriminant_polynomial": D,
            "squarefree_gcd": gcd, "squarefree": squarefree,
            "discriminant": disc,
            "curve": H, "genus": genus, "error": error,
            "evidence": rv_make_evidence(
                "EXACT_CERTIFICATE" if ok else "SYMBOLIC_EVIDENCE",
                claim="exact quadratic double-cover / hyperelliptic model extracted" if ok else "partial quadratic double-cover extraction",
                method="exact coefficient extraction and discriminant identity",
                exact=True,
                caveats=() if ok else ("HyperellipticCurve construction or smoothness certification incomplete.",),
            ),
        }


    def singular_quartic_double_cover(poly, singular_point, projection="slope_y_over_x"):
        """Normalize a nodal/cuspidal plane quartic through projection from a singular point.

        For projection='slope_y_over_x', write

            x = x0 + U,   y = y0 + T*U.

        The exact transformed equation is divided by its maximal power of U.
        If the residual equation is quadratic in U, its discriminant gives an
        exact hyperelliptic double-cover model.  The raw quotient is preserved;
        no sign canonicalization is applied, avoiding loss of coordinate-map
        provenance.
        """
        R = poly.parent()
        gens = tuple(R.gens())
        if len(gens) != 2:
            return {
                "status": "unsupported",
                "reason": "requires a bivariate polynomial ring",
                "evidence": rv_make_evidence("INCONCLUSIVE", claim="singular quartic projection unsupported"),
            }
        if int(poly.total_degree()) != 4:
            return {
                "status": "unsupported",
                "reason": "source polynomial is not a plane quartic",
                "evidence": rv_make_evidence("INCONCLUSIVE", claim="singular quartic projection not applicable"),
            }
        x, y = gens
        x0, y0 = (R.base_ring()(singular_point[0]), R.base_ring()(singular_point[1]))
        Fx = poly.derivative(x)
        Fy = poly.derivative(y)
        singular_verified = bool(poly(x0, y0) == 0 and Fx(x0, y0) == 0 and Fy(x0, y0) == 0)
        if not singular_verified:
            return {
                "status": "invalid singular point",
                "singular_point": (x0, y0),
                "evidence": rv_make_evidence(
                    "INCONCLUSIVE", claim="supplied point is not an affine singularity",
                    method="exact value and partial-derivative checks", exact=True,
                ),
            }
        if str(projection) != "slope_y_over_x":
            return {
                "status": "unsupported",
                "reason": "only projection='slope_y_over_x' is currently implemented",
                "evidence": rv_make_evidence("INCONCLUSIVE", claim="requested projection chart unsupported"),
            }

        S = PolynomialRing(R.base_ring(), names=("T", "U"))
        T, U = S.gens()
        phi = R.hom([x0 + U, y0 + T*U], S)
        transformed = S(phi(poly))

        quotient = transformed
        multiplicity = 0
        while quotient != 0:
            q, r = quotient.quo_rem(U)
            if r != 0:
                break
            quotient = q
            multiplicity += 1
        raw_quotient = S(quotient)
        if multiplicity < 2:
            return {
                "status": "partial",
                "singular_point": (x0, y0),
                "singular_verified": True,
                "transformed_polynomial": transformed,
                "singular_multiplicity": multiplicity,
                "raw_projected_equation": raw_quotient,
                "reason": "projection did not expose multiplicity at least two",
                "evidence": rv_make_evidence("SYMBOLIC_EVIDENCE", claim="singular projection transformed exactly", exact=True),
            }
        if int(raw_quotient.degree(U)) != 2:
            return {
                "status": "partial",
                "singular_point": (x0, y0),
                "singular_verified": True,
                "transformed_polynomial": transformed,
                "singular_multiplicity": multiplicity,
                "raw_projected_equation": raw_quotient,
                "reason": "residual projection equation is not quadratic in U",
                "evidence": rv_make_evidence("SYMBOLIC_EVIDENCE", claim="singular projection transformed exactly", exact=True),
            }

        kill_u = S.hom([T, S(0)], S)
        c = S(kill_u(raw_quotient))
        b = S(kill_u(raw_quotient.derivative(U)))
        a = S(kill_u(raw_quotient.derivative(U).derivative(U)) / 2)
        if a == 0:
            raise ValueError("quadratic coefficient vanished after singular projection")
        W = S(2*a*U + b)
        Dmulti = S(b**2 - 4*a*c)
        identity = S(W**2 - Dmulti - 4*a*raw_quotient)

        P = PolynomialRing(R.base_ring(), names=("T",))
        TT = P.gen()
        to_uni = S.hom([TT, P(0)], P)
        D = P(to_uni(Dmulti))
        gcdD = D.gcd(D.derivative())
        squarefree = bool(gcdD == 1)
        H = None
        genus = None
        error = None
        if squarefree:
            try:
                H = HyperellipticCurve(D)
                genus = int(H.genus())
            except Exception as exc:
                error = str(exc)
        disc = None
        try:
            disc = D.discriminant()
        except Exception:
            pass
        ok = bool(identity == 0 and squarefree and H is not None)
        return {
            "status": "ok" if ok else "partial",
            "source_polynomial": poly,
            "singular_point": (x0, y0),
            "singular_verified": True,
            "projection": str(projection),
            "projection_ring": S,
            "T": T,
            "U": U,
            "transformed_polynomial": transformed,
            "singular_multiplicity": int(multiplicity),
            "raw_projected_equation": raw_quotient,
            "quadratic_coefficients": (a, b, c),
            "W_expression": W,
            "double_cover_identity_residual": identity,
            "inverse_U_expression_description": "U=(W-b)/(2*a)",
            "inverse_denominator": S(2*a),
            "discriminant_multivariate": Dmulti,
            "univariate_ring": P,
            "X": TT,
            "discriminant_polynomial": D,
            "squarefree_gcd": gcdD,
            "squarefree": squarefree,
            "discriminant": disc,
            "curve": H,
            "genus": genus,
            "error": error,
            "evidence": rv_make_evidence(
                "EXACT_CERTIFICATE" if ok else "SYMBOLIC_EVIDENCE",
                claim=(
                    "exact singular-quartic projection produced a smooth hyperelliptic double cover"
                    if ok else
                    "singular-quartic projection partially extracted"
                ),
                method="exact singular-point check, projection, multiplicity removal, and discriminant identity",
                exact=True,
                caveats=() if ok else ("Smooth hyperelliptic model construction was incomplete.",),
            ),
        }

    def hyperelliptic_capabilities(curve, construct_jacobian=True):
        names = tuple(sorted(set(dir(curve))))
        interesting = tuple(n for n in names if any(k in n.lower() for k in (
            "rational", "point", "jacob", "rank", "selmer", "chabauty", "integral", "local", "infinity"
        )))
        out = {"status": "probed", "curve_methods": interesting, "jacobian": None,
               "jacobian_methods": (), "errors": []}
        if construct_jacobian and hasattr(curve, "jacobian"):
            try:
                J = curve.jacobian()
                out["jacobian"] = J
                jnames = tuple(sorted(set(dir(J))))
                out["jacobian_methods"] = tuple(n for n in jnames if any(k in n.lower() for k in (
                    "rank", "torsion", "selmer", "chabauty", "point", "mordell", "kummer", "endo"
                )))
            except Exception as exc:
                out["errors"].append(("jacobian", str(exc)))
        out["evidence"] = rv_make_evidence(
            "SYMBOLIC_EVIDENCE", claim="runtime hyperelliptic/Jacobian capability probe",
            method="method introspection", exact=False,
            caveats=("Method presence is not a proof that a backend computation will succeed.",),
        )
        return out

    def rational_x_search(poly, height=20):
        """Exhaustively search reduced x=a/b with |a|,b <= height for square poly(x)."""
        H = int(height)
        if H < 1:
            raise ValueError("height must be positive")
        hits = []
        seen = set()
        for b in range(1, H + 1):
            for a in range(-H, H + 1):
                if engine["gcd"](ZZ(a), ZZ(b)) != 1:
                    continue
                x = QQ(a) / QQ(b)
                if x in seen:
                    continue
                seen.add(x)
                q = QQ(poly(x))
                if q < 0:
                    continue
                try:
                    sq = bool(q.is_square())
                except Exception:
                    sq = bool(ZZ(q.numerator()).is_square() and ZZ(q.denominator()).is_square())
                if not sq:
                    continue
                try:
                    y = q.sqrt()
                except Exception:
                    yn = ZZ(q.numerator()).sqrt()
                    yd = ZZ(q.denominator()).sqrt()
                    y = QQ(yn) / QQ(yd)
                hits.append((x, y))
                if y != 0:
                    hits.append((x, -y))
        hits = tuple(sorted(set(hits), key=lambda P: (P[0], P[1])))
        return {
            "status": "bounded exhaustive x-search",
            "height": H, "points": hits, "x_values_tested": len(seen),
            "evidence": rv_make_evidence(
                "HEURISTIC_SEARCH",
                claim="all affine rational points with reduced x-height within bound found",
                method="exhaustive bounded rational x search", exact=True, exhaustive=True,
                payload={"height": H, "points_found": len(hits)},
                caveats=("This is exhaustive only inside the stated x-height box; absence outside the box is not certified.",),
            ),
        }

    actions = {
        "quadratic_double_cover": quadratic_double_cover,
        "singular_quartic_double_cover": singular_quartic_double_cover,
        "hyperelliptic_capabilities": hyperelliptic_capabilities,
        "hyperelliptic_rational_x_search": rational_x_search,
    }
    return engine["rv_register_satellite"](
        "genus2", "3.2.0", actions,
        description="Quadratic and singular-quartic double-cover extraction, genus-2/hyperelliptic capability probing, and bounded rational searches.",
        capabilities={"exact_double_cover": True, "singular_quartic_projection": True, "hyperelliptic": True, "rational_search": "bounded"},
    )
