"""
Realization Engine v3 (public core)
===================================
Exact-computation toolkit for projective line-arrangement realization spaces.
Unified exact/projective realization-space engine with chart atlases, evidence tracking, reproducibility manifests, and satellite hooks for arithmetic/numerical methods.

Conventions
-----------
* Work in the dual projective plane.
* A primal line is a dual projective point P_i in P^2.
* A primal k-fold intersection is a maximal collinear flat F of k dual points.
* Rich flats have size >= 3. Double points are inferred from the pair budget.
* Core combinatorics is kept separate from symbolic/projective algebra.

The engine intentionally uses conservative Sage APIs and wraps version-sensitive
operations. Keep this file/core cell fixed; put experiments in later notebook cells.
"""

from sage.all import *
from itertools import combinations, product
from collections import defaultdict, Counter
import hashlib
import json
import os
import time
import importlib.util
import traceback


# =============================================================================
# V3 ENGINE METADATA, SCHEMAS, EVIDENCE, AND SATELLITE REGISTRY
# =============================================================================

RV_ENGINE_VERSION = "3.2.0-public"
RV_SCHEMA_VERSION = 3

RV_EVIDENCE_ORDER = {
    "INCONCLUSIVE": 0,
    "HEURISTIC_SEARCH": 10,
    "NUMERICAL_EVIDENCE": 20,
    "SYMBOLIC_EVIDENCE": 30,
    "LOCAL_OBSTRUCTION": 40,
    "EXHAUSTIVE_FINITE_SEARCH": 50,
    "EXACT_CERTIFICATE": 80,
    "PROOF": 100,
}

RV_SATELLITES = {}
RV_HOOKS = defaultdict(dict)


def rv_stable_data(obj):
    """Convert nested engine/Sage data to deterministic JSON-friendly data.

    This is for fingerprints and manifests, not for reconstructing arbitrary
    Sage objects. Exact mathematical payloads should still be saved with the
    dedicated model/certificate serializers.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {
            str(k): rv_stable_data(obj[k])
            for k in sorted(obj, key=lambda x: str(x))
        }
    if isinstance(obj, (list, tuple)):
        return [rv_stable_data(x) for x in obj]
    if isinstance(obj, set):
        return sorted((rv_stable_data(x) for x in obj), key=lambda x: str(x))
    # Sage integers/rationals and polynomial objects stringify exactly enough
    # for audit fingerprints. Their reconstruction belongs to serializers.
    try:
        if hasattr(obj, "parent"):
            return {
                "sage_parent": str(obj.parent()),
                "value": str(obj),
            }
    except Exception:
        pass
    return str(obj)


def rv_digest(obj, algorithm="sha256"):
    payload = json.dumps(
        rv_stable_data(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    h = hashlib.new(algorithm)
    h.update(payload)
    return h.hexdigest()


def rv_model_fingerprint(model):
    """Fingerprint only the mathematical incidence structure and labels."""
    payload = {
        "n": int(model["n"]),
        "flats": [list(F) for F in model["flats"]],
    }
    return rv_digest(payload)


def rv_system_fingerprint(system):
    payload = {
        "model": rv_model_fingerprint(system["model"]),
        "frame": list(system.get("frame", ())),
        "chart_kind": system.get("chart_kind", system.get("chart_type", "legacy")),
        "variables": [str(x) for x in system.get("variables", ())],
        "closure": [str(f) for f in system.get("closure_polynomials", ())],
        "open": [str(f) for f in system.get("forbidden_polynomials", ())],
    }
    return rv_digest(payload)


def rv_make_evidence(level, claim=None, method=None, payload=None,
                     caveats=(), exact=False, exhaustive=False):
    level = str(level).upper()
    if level not in RV_EVIDENCE_ORDER:
        raise ValueError("unknown evidence level: {}".format(level))
    return {
        "rv_type": "evidence",
        "schema_version": RV_SCHEMA_VERSION,
        "level": level,
        "strength": RV_EVIDENCE_ORDER[level],
        "claim": claim,
        "method": method,
        "exact": bool(exact),
        "exhaustive": bool(exhaustive),
        "payload": payload,
        "caveats": tuple(str(x) for x in caveats),
    }


def rv_evidence_at_least(evidence, level):
    if evidence is None:
        return False
    target = RV_EVIDENCE_ORDER[str(level).upper()]
    return int(evidence.get("strength", -1)) >= target


def rv_new_manifest(model=None, label=None, metadata=None):
    manifest = {
        "rv_type": "experiment_manifest",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "sage_version": rv_sage_version() if "rv_sage_version" in globals() else "loading",
        "label": label or "unnamed_experiment",
        "created_unix": time.time(),
        "model_fingerprint": None,
        "model_name": None,
        "steps": [],
        "metadata": dict(metadata or {}),
    }
    if model is not None:
        manifest["model_fingerprint"] = rv_model_fingerprint(model)
        manifest["model_name"] = str(model.get("name", "unnamed"))
    return manifest


def rv_manifest_record(manifest, action, result=None, evidence=None,
                       parameters=None, notes=None):
    step = {
        "index": len(manifest["steps"]),
        "action": str(action),
        "time_unix": time.time(),
        "parameters": rv_stable_data(parameters or {}),
        "result": rv_stable_data(result),
        "evidence": rv_stable_data(evidence),
        "notes": None if notes is None else str(notes),
    }
    manifest["steps"].append(step)
    return step


def rv_save_manifest(manifest, path):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(rv_stable_data(manifest), stream, indent=2, sort_keys=True)
    return path




def rv_new_research_ledger(model=None, label=None, metadata=None):
    """Create an append-only research ledger separating evidence layers.

    The ledger is intentionally not a replacement for chart/system objects.
    It is an index over raw evidence, derived structure, certificates,
    observations, and failures, with deterministic payload digests and explicit
    dependencies.  Original payload objects are retained in memory; saving the
    ledger serializes them through rv_stable_data without mutating the originals.
    """
    ledger = {
        "rv_type": "research_ledger",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "sage_version": rv_sage_version() if "rv_sage_version" in globals() else "loading",
        "label": label or "unnamed_research_ledger",
        "created_unix": time.time(),
        "model_fingerprint": rv_model_fingerprint(model) if model is not None else None,
        "model_name": str(model.get("name", "unnamed")) if model is not None else None,
        "metadata": dict(metadata or {}),
        "entries": [],
    }
    return ledger


def rv_ledger_record(ledger, layer, action, payload=None, evidence=None,
                     dependencies=(), tags=(), notes=None):
    """Append one transparent research record and return its stable entry id.

    Layers are deliberately semantic rather than algorithmic:
      raw          direct engine/tool output or exact equations;
      derived      structure inferred exactly from raw data;
      certificate  theorem-level or exact certification object;
      observation  pattern/hypothesis that should not be mistaken for proof;
      failure      exceptions, crashes, negative experiments, API issues.
    """
    allowed = {"raw", "derived", "certificate", "observation", "failure"}
    layer = str(layer).lower()
    if layer not in allowed:
        raise ValueError("layer must be one of {}".format(sorted(allowed)))
    dependencies = tuple(str(x) for x in dependencies)
    tags = tuple(str(x) for x in tags)
    stable_payload = rv_stable_data(payload)
    entry_index = len(ledger["entries"])
    digest = rv_digest({
        "layer": layer,
        "action": str(action),
        "payload": stable_payload,
        "dependencies": dependencies,
        "tags": tags,
    })
    entry_id = "rvlog-{:04d}-{}".format(entry_index, digest[:12])
    entry = {
        "entry_id": entry_id,
        "index": entry_index,
        "time_unix": time.time(),
        "layer": layer,
        "action": str(action),
        "payload": payload,
        "payload_digest": digest,
        "evidence": evidence,
        "dependencies": dependencies,
        "tags": tags,
        "notes": None if notes is None else str(notes),
    }
    ledger["entries"].append(entry)
    return entry


def rv_ledger_summary(ledger):
    counts = Counter(str(E.get("layer")) for E in ledger.get("entries", ()))
    return {
        "rv_type": "research_ledger_summary",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "label": ledger.get("label"),
        "model_fingerprint": ledger.get("model_fingerprint"),
        "entry_count": len(ledger.get("entries", ())),
        "layer_counts": dict(counts),
        "entry_ids": tuple(E.get("entry_id") for E in ledger.get("entries", ())),
        "ledger_digest": rv_digest(tuple(
            (E.get("entry_id"), E.get("payload_digest"))
            for E in ledger.get("entries", ())
        )),
    }


def rv_save_research_ledger(ledger, path):
    """Save an append-only research ledger as deterministic JSON-friendly data."""
    payload = rv_stable_data(ledger)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
    return {"path": path, "summary": rv_ledger_summary(ledger)}

def rv_register_satellite(name, version, actions, description="",
                          capabilities=None, metadata=None):
    """Register a specialized algorithm provider with the engine.

    `actions` is a dict action_name -> callable. Core research code can then
    dispatch by action rather than importing implementation-specific modules.
    """
    name = str(name)
    if not isinstance(actions, dict) or not actions:
        raise ValueError("satellite actions must be a nonempty dict")
    for action, fn in actions.items():
        if not callable(fn):
            raise TypeError("satellite action {} is not callable".format(action))
    record = {
        "name": name,
        "version": str(version),
        "description": str(description),
        "actions": dict(actions),
        "capabilities": dict(capabilities or {}),
        "metadata": dict(metadata or {}),
    }
    if name in RV_SATELLITES:
        rv_unregister_satellite(name)  # Avoid retaining hooks from an earlier registration.
    RV_SATELLITES[name] = record
    for action, fn in actions.items():
        RV_HOOKS[str(action)][name] = fn
    return record


def rv_unregister_satellite(name):
    name = str(name)
    record = RV_SATELLITES.pop(name, None)
    if record is None:
        return False
    for action in list(record["actions"]):
        RV_HOOKS.get(action, {}).pop(name, None)
    return True


def rv_list_satellites(print_report=True):
    out = []
    for name in sorted(RV_SATELLITES):
        rec = RV_SATELLITES[name]
        row = {
            "name": name,
            "version": rec["version"],
            "actions": tuple(sorted(rec["actions"])),
            "capabilities": dict(rec.get("capabilities", {})),
            "description": rec.get("description", ""),
        }
        out.append(row)
        if print_report:
            print("{} v{}: {}".format(name, row["version"], ", ".join(row["actions"])))
    return tuple(out)


def rv_dispatch(action, *args, **kwargs):
    """Dispatch a specialized action through a registered satellite.

    Pass provider='name' to select a satellite explicitly. Without it, exactly
    one provider must be registered for the requested action.
    """
    provider = kwargs.pop("provider", None)
    choices = RV_HOOKS.get(str(action), {})
    if provider is not None:
        if provider not in choices:
            raise KeyError("provider {} does not expose action {}".format(provider, action))
        return choices[provider](*args, **kwargs)
    if not choices:
        raise KeyError(
            "no satellite exposes action {}. Load satellites with rv_load_satellites().".format(action)
        )
    if len(choices) != 1:
        raise ValueError(
            "multiple providers for {}: {}. Choose provider=...".format(
                action, sorted(choices)
            )
        )
    return next(iter(choices.values()))(*args, **kwargs)


def rv_load_satellite_file(path):
    path = os.path.abspath(path)
    module_name = "rv_satellite_" + hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load satellite {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "register"):
        raise AttributeError("satellite {} has no register(engine_globals) function".format(path))
    before = set(RV_SATELLITES)
    result = module.register(globals())
    after = set(RV_SATELLITES)
    return {
        "path": path,
        "registered": tuple(sorted(after - before)),
        "return_value": result,
    }


def rv_load_satellites(directory=None, strict=False, print_report=True):
    if directory is None:
        try:
            directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), "satellites")
        except Exception:
            directory = os.path.join(os.getcwd(), "satellites")
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        if strict:
            raise FileNotFoundError(directory)
        return {"directory": directory, "loaded": (), "errors": ()}
    loaded = []
    errors = []
    for filename in sorted(os.listdir(directory)):
        if not (filename.startswith("rv_satellite_") and filename.endswith(".py")):
            continue
        if filename == "rv_satellite_template.py":
            continue
        path = os.path.join(directory, filename)
        try:
            info = rv_load_satellite_file(path)
            loaded.extend(info["registered"])
        except Exception as exc:
            errors.append({"file": filename, "error": str(exc), "traceback": traceback.format_exc()})
            if strict:
                raise
    if print_report:
        print("satellites loaded =", tuple(loaded))
        if errors:
            print("satellite load errors =", tuple(e["file"] for e in errors))
    return {"directory": directory, "loaded": tuple(loaded), "errors": tuple(errors)}


def rv_capabilities(print_report=False):
    """Inspect the current runtime without assuming optional packages exist."""
    caps = {
        "engine_version": RV_ENGINE_VERSION,
        "sage_version": rv_sage_version() if "rv_sage_version" in globals() else "loading",
        "satellites": tuple(sorted(RV_SATELLITES)),
    }
    for module_name in ("numpy", "scipy", "phcpy", "cypari2"):
        try:
            mod = __import__(module_name)
            caps[module_name] = getattr(mod, "__version__", True)
        except Exception:
            caps[module_name] = False
    # Sage interfaces can exist even if the corresponding external program is absent.
    caps["sage_exact_polynomials"] = True
    if print_report:
        for key in sorted(caps):
            print("{} = {}".format(key, caps[key]))
    return caps


# =============================================================================
# 0. COMPATIBILITY / EXACT-ALGEBRA LAYER
# =============================================================================


def rv_sage_version():
    try:
        import sage.version
        return sage.version.version
    except Exception:
        try:
            return version()
        except Exception:
            return "unknown"


def rv_common_parent(values):
    """Infer a common Sage universe from all supplied exact values."""
    vals = list(values)
    if not vals:
        return QQ
    return Sequence(vals).universe()


def rv_poly_variables(f):
    """Version-safe list of polynomial variables actually occurring in f."""
    try:
        return tuple(f.variables())
    except Exception:
        R = parent(f)
        return tuple(x for x in R.gens() if f.degree(x) > 0)


def rv_leading_coefficient(f):
    """Version-safe leading coefficient for a multivariate polynomial."""
    f = parent(f)(f)
    if f == 0:
        return parent(f)(0)
    try:
        return f.lc()
    except Exception:
        mons = f.monomials()
        if not mons:
            return f
        return f.monomial_coefficient(mons[0])


def rv_canonical_poly(f):
    """Normalize a nonzero polynomial up to multiplication by a nonzero scalar."""
    R = parent(f)
    f = R(f)
    if f == 0:
        return f
    lc = rv_leading_coefficient(f)
    return R(f / lc)


def rv_factor_list(f):
    """Return [(factor, exponent), ...] using only conservative Sage APIs."""
    f = parent(f)(f)
    return list(f.factor())


def rv_nonconstant_factors(f):
    out = []
    for g, e in rv_factor_list(f):
        if g.degree() > 0:
            out.append((rv_canonical_poly(g), int(e)))
    return out


def rv_is_irreducible(f):
    """Version-safe irreducibility test for a nonconstant multivariate polynomial."""
    f = parent(f)(f)
    if f.degree() <= 0:
        return False
    fac = rv_factor_list(f)
    return len(fac) == 1 and int(fac[0][1]) == 1


def rv_groebner_basis(polys):
    polys = list(polys)
    if not polys:
        return []
    R = parent(polys[0])
    I = R.ideal([R(f) for f in polys])
    return list(I.groebner_basis())



def rv_ideal(polys, ring=None):
    polys = list(polys)
    if ring is None:
        if not polys:
            raise ValueError("ring required for empty ideal")
        ring = parent(polys[0])
    return ring.ideal([ring(f) for f in polys])


def rv_ideal_membership(f, ideal_or_polys):
    """Exact membership test with a conservative Groebner fallback."""
    if hasattr(ideal_or_polys, "ring") or hasattr(ideal_or_polys, "gens"):
        I = ideal_or_polys
    else:
        I = rv_ideal(ideal_or_polys)
    try:
        return bool(f in I)
    except Exception:
        try:
            return I.reduce(f) == 0
        except Exception:
            R = parent(f)
            G = list(I.groebner_basis())
            try:
                return R(f).reduce(G) == 0
            except Exception:
                return False


def rv_elimination_ideal(I, variables):
    """Version-safe elimination wrapper.

    Sage polynomial backends differ substantially here. We use the native
    method when available and otherwise fail descriptively rather than silently
    inventing a ring-order conversion that could change the mathematics.
    """
    variables = tuple(variables)
    try:
        return I.elimination_ideal(list(variables))
    except Exception as exc:
        raise RuntimeError(
            "elimination_ideal is unavailable/failed in this Sage backend: {}. "
            "Construct an explicit lexicographic auxiliary ring for this calculation.".format(exc)
        )


def rv_radical_ideal(I):
    try:
        return I.radical()
    except Exception as exc:
        raise RuntimeError("radical computation unavailable in this Sage backend: {}".format(exc))


def rv_primary_decomposition_safe(I):
    for name in ("primary_decomposition", "primary_decomposition_complete"):
        if hasattr(I, name):
            try:
                return {"status": "ok", "method": name, "components": tuple(getattr(I, name)())}
            except Exception as exc:
                last = exc
    return {"status": "unavailable", "method": None, "components": (),
            "error": str(locals().get("last", "no primary decomposition method"))}


def rv_associated_primes_safe(I):
    if hasattr(I, "associated_primes"):
        try:
            return {"status": "ok", "primes": tuple(I.associated_primes())}
        except Exception as exc:
            return {"status": "error", "primes": (), "error": str(exc)}
    return {"status": "unavailable", "primes": (), "error": "method unavailable"}


def rv_singular_locus_ideal_safe(I):
    """Best-effort hook; exact behavior depends on Sage ideal backend."""
    for name in ("singular_locus", "singular_locus_ideal"):
        if hasattr(I, name):
            try:
                return {"status": "ok", "method": name, "data": getattr(I, name)()}
            except Exception as exc:
                last = exc
    return {"status": "unavailable", "data": None,
            "error": str(locals().get("last", "method unavailable"))}


def rv_saturate_by_polynomial(polys, g):
    """
    Compute I : g^infinity by Rabinowitsch elimination:
        (I, 1 - z*g) intersect R.

    Returns a dict containing the elimination equations back in the original ring,
    plus the auxiliary Groebner basis for inspection.
    """
    polys = list(polys)
    R = parent(g)
    g = R(g)
    if not polys:
        return {
            "ring": R,
            "elimination": [],
            "aux_ring": None,
            "aux_groebner": [],
        }

    names = tuple(str(x) for x in R.gens())
    zname = "rv_sat_z"
    while zname in names:
        zname = "_" + zname

    S = PolynomialRing(
        R.base_ring(),
        names=(zname,) + names,
        order="lex",
    )
    SG = S.gens()
    z = SG[0]

    phi = R.hom(list(SG[1:]), S)
    polys_S = [phi(R(f)) for f in polys]
    gS = phi(g)

    Iaux = S.ideal(polys_S + [S(1) - z * gS])
    G = list(Iaux.groebner_basis())

    elim_S = [f for f in G if z not in rv_poly_variables(f)]

    # Map the eliminated equations back to R. z can be sent to 0 because it no
    # longer occurs in elim_S.
    psi = S.hom([R(0)] + list(R.gens()), R)
    elim_R = [rv_canonical_poly(psi(f)) for f in elim_S]

    # Deduplicate associates.
    unique = []
    seen = set()
    for f in elim_R:
        key = str(f)
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return {
        "ring": R,
        "elimination": unique,
        "aux_ring": S,
        "aux_groebner": G,
    }


# =============================================================================
# 1. PROJECTIVE LINEAR ALGEBRA
# =============================================================================


def rv_cross(P, Q):
    """Homogeneous cross product. Works over fields or polynomial rings."""
    return (
        P[1] * Q[2] - P[2] * Q[1],
        P[2] * Q[0] - P[0] * Q[2],
        P[0] * Q[1] - P[1] * Q[0],
    )


def rv_det(P, Q, R):
    """Exact 3x3 determinant of homogeneous projective vectors."""
    return (
        P[0] * (Q[1] * R[2] - Q[2] * R[1])
        - P[1] * (Q[0] * R[2] - Q[2] * R[0])
        + P[2] * (Q[0] * R[1] - Q[1] * R[0])
    )


def rv_is_zero_vector(P):
    return all(x == 0 for x in P)


def rv_projectively_equal(P, Q):
    return rv_is_zero_vector(rv_cross(P, Q))


def rv_projective_normalize(P):
    """
    Normalize by the first nonzero coordinate. Use only for exact field-valued
    vectors, not as part of generic symbolic propagation.
    """
    P = tuple(P)
    for x in P:
        if x != 0:
            return tuple(y / x for y in P)
    raise ValueError("zero vector is not a projective point")


def rv_linear_combo(P, a, Q, b):
    return tuple(a * P[i] + b * Q[i] for i in range(3))


def rv_dependent_triples_from_points(points):
    """All collinear triples among exact dual projective points."""
    points = list(points)
    out = []
    for T in combinations(range(len(points)), 3):
        i, j, k = T
        if rv_det(points[i], points[j], points[k]) == 0:
            out.append(T)
    return tuple(out)


def rv_gauge_to_standard_frame(points, frame):
    """
    Apply a dual projective transformation sending four points in general
    position to e1, e2, e3, (1,1,1), projectively.
    """
    points = tuple(tuple(P) for P in points)
    frame = tuple(frame)
    if len(frame) != 4:
        raise ValueError("frame must contain four indices")

    flat_coeffs = [x for P in points for x in P]
    K = rv_common_parent(flat_coeffs)

    i0, i1, i2, i3 = frame

    basis = matrix(
        K,
        [list(points[i0]), list(points[i1]), list(points[i2])],
    ).transpose()

    if basis.det() == 0:
        raise ValueError("first three frame points are dependent")

    Binv = basis.inverse()
    u = Binv * vector(K, points[i3])

    if any(x == 0 for x in u):
        raise ValueError("fourth frame point is not in general position")

    D = diagonal_matrix(K, [1 / u[0], 1 / u[1], 1 / u[2]])
    T = D * Binv

    transformed = []
    for P in points:
        v = T * vector(K, P)
        transformed.append(rv_projective_normalize(tuple(v)))

    return tuple(transformed)


# =============================================================================
# 2. COMBINATORIAL MODEL: MAXIMAL RANK-TWO FLATS
# =============================================================================


def rv_normalize_flat(F):
    F = tuple(sorted(set(int(i) for i in F)))
    if len(F) < 3:
        raise ValueError("rich flats must have size >= 3")
    return F


def rv_normalize_flats(flats):
    unique = sorted(set(rv_normalize_flat(F) for F in flats))

    # No rich flat may properly contain another rich flat in a maximal-flat list.
    for i, F in enumerate(unique):
        SF = set(F)
        for j, G in enumerate(unique):
            if i == j:
                continue
            SG = set(G)
            if SF < SG:
                raise ValueError("non-maximal flat detected: {} < {}".format(F, G))

    # Two distinct projective lines in the dual plane cannot share two points.
    for F, G in combinations(unique, 2):
        if len(set(F).intersection(G)) >= 2:
            raise ValueError(
                "inconsistent flats share >=2 points: {} and {}".format(F, G)
            )

    return tuple(unique)


def rv_dependent_triples_from_flats(flats):
    D = set()
    for F in flats:
        for T in combinations(F, 3):
            D.add(tuple(sorted(T)))
    return tuple(sorted(D))


def rv_flats_from_dependent_triples(n, dependent_triples):
    """
    Reconstruct maximal collinear flats from a complete dependent-triple list.

    IMPORTANT: the supplied triple list must be complete: if four points lie on
    one flat, all four choose three dependent triples must be present.
    """
    n = int(n)
    D = set()

    for T in dependent_triples:
        T = tuple(sorted(set(int(i) for i in T)))
        if len(T) != 3:
            raise ValueError("every dependent triple must contain exactly 3 indices")
        if min(T) < 0 or max(T) >= n:
            raise ValueError("triple index outside 0..n-1: {}".format(T))
        D.add(T)

    pair_to_points = defaultdict(set)
    for T in D:
        for i, j in combinations(T, 2):
            pair_to_points[(i, j)].update(T)

    candidates = set()
    for pts in pair_to_points.values():
        F = tuple(sorted(pts))
        if len(F) >= 3:
            candidates.add(F)

    # Completeness check: every inferred candidate flat must contain all its
    # dependent triples in the supplied data.
    for F in candidates:
        missing = [T for T in combinations(F, 3) if tuple(sorted(T)) not in D]
        if missing:
            raise ValueError(
                "dependent-triple list is incomplete/inconsistent for flat {}. "
                "Missing e.g. {}".format(F, missing[0])
            )

    # Retain only maximal candidates.
    maximal = []
    for F in sorted(candidates, key=lambda X: (-len(X), X)):
        SF = set(F)
        if not any(SF < set(G) for G in maximal):
            maximal.append(F)

    flats = rv_normalize_flats(maximal)

    # Every input dependent triple must lie in exactly one maximal flat.
    for T in D:
        containing = [F for F in flats if set(T).issubset(F)]
        if len(containing) != 1:
            raise ValueError(
                "triple {} belongs to {} maximal flats".format(T, len(containing))
            )

    return flats


def rv_make_model(n, flats=None, dependent_triples=None, name=None):
    n = int(n)
    if n < 3:
        raise ValueError("need at least 3 projective points")

    if (flats is None) == (dependent_triples is None):
        raise ValueError("provide exactly one of flats= or dependent_triples=")

    if flats is None:
        flats = rv_flats_from_dependent_triples(n, dependent_triples)
    else:
        flats = rv_normalize_flats(flats)

    for F in flats:
        if min(F) < 0 or max(F) >= n:
            raise ValueError("flat index outside 0..n-1: {}".format(F))

    D = rv_dependent_triples_from_flats(flats)
    Dset = set(D)

    pair_owner = {}
    for fid, F in enumerate(flats):
        for pair in combinations(F, 2):
            if pair in pair_owner:
                raise ValueError("pair {} lies on two rich flats".format(pair))
            pair_owner[pair] = fid

    model = {
        "rv_type": "model",
        "schema_version": RV_SCHEMA_VERSION,
        "name": name or "unnamed",
        "n": n,
        "flats": tuple(flats),
        "dependent_triples": D,
        "dependent_set": Dset,
        "pair_owner": pair_owner,
    }
    model["fingerprint"] = rv_model_fingerprint(model)
    return model


def rv_model_from_points(points, name=None):
    D = rv_dependent_triples_from_points(points)
    return rv_make_model(
        len(points),
        dependent_triples=D,
        name=name or "from_points",
    )


def rv_forbidden_triples(model):
    D = model["dependent_set"]
    return tuple(
        T for T in combinations(range(model["n"]), 3)
        if T not in D
    )


def rv_incidence_map(model):
    inc = defaultdict(list)
    for fid, F in enumerate(model["flats"]):
        for p in F:
            inc[p].append(fid)
    return {p: tuple(v) for p, v in inc.items()}


def rv_model_metrics(model):
    """Combinatorial t-vector, pair check, Melchior defect, and Chern data."""
    n = model["n"]
    tk = Counter(len(F) for F in model["flats"])

    rich_pair_mass = sum(binomial(k, 2) * c for k, c in tk.items())
    t2 = binomial(n, 2) - rich_pair_mass
    if t2 < 0:
        raise ValueError("rich flats overuse the pair budget")

    tk_full = {2: int(t2)}
    for k in sorted(tk):
        tk_full[int(k)] = int(tk[k])

    pair_rhs = sum(binomial(k, 2) * v for k, v in tk_full.items())
    pair_lhs = binomial(n, 2)

    c1sq = 9 - 5 * n + sum((3 * k - 4) * v for k, v in tk_full.items())
    c2 = 3 - 2 * n + sum((k - 1) * v for k, v in tk_full.items())
    defect = tk_full.get(2, 0) - 3 - sum(
        (k - 3) * v for k, v in tk_full.items() if k >= 4
    )

    slope = None if c2 == 0 else QQ(c1sq) / QQ(c2)

    return {
        "n": n,
        "tk": tk_full,
        "pair_lhs": pair_lhs,
        "pair_rhs": pair_rhs,
        "pair_ok": pair_lhs == pair_rhs,
        "defect": int(defect),
        "c1sq": int(c1sq),
        "c2": int(c2),
        "slope": slope,
    }


def rv_model_summary(model):
    M = rv_model_metrics(model)
    print("name =", model["name"])
    print("n =", model["n"])
    print("rich flats =", len(model["flats"]))
    print("flat sizes =", dict(sorted(Counter(map(len, model["flats"])).items())))
    print("dependent triples =", len(model["dependent_triples"]))
    print("t_k =", M["tk"])
    print("pair identity =", M["pair_ok"])
    print("defect =", M["defect"])
    print("c1^2 =", M["c1sq"])
    print("c2 =", M["c2"])
    print("slope =", M["slope"])


# =============================================================================
# 3. COMBINATORIAL CONSTRUCTION PLANNER
# =============================================================================


def rv_is_general_frame(model, frame):
    frame = tuple(frame)
    if len(frame) != 4 or len(set(frame)) != 4:
        return False
    if min(frame) < 0 or max(frame) >= model["n"]:
        return False
    D = model["dependent_set"]
    return all(tuple(sorted(T)) not in D for T in combinations(frame, 3))


def rv_find_general_frames(model, limit=None):
    out = []
    for F in combinations(range(model["n"]), 4):
        if rv_is_general_frame(model, F):
            out.append(F)
            if limit is not None and len(out) >= int(limit):
                break
    return tuple(out)


def rv_determined_flats(model, known):
    known = set(known)
    out = []
    for fid, F in enumerate(model["flats"]):
        if sum(p in known for p in F) >= 2:
            out.append(fid)
    return tuple(out)


def rv_combinatorial_closure(model, known):
    """
    Purely combinatorial propagation.

    A rich flat is determined once >=2 of its points are known. An unknown point
    is forced once it lies on >=2 determined flats. Extra usable flats are
    recorded rather than silently discarded.
    """
    known = set(int(p) for p in known)
    inc = rv_incidence_map(model)
    history = []

    while True:
        determined = set(rv_determined_flats(model, known))
        found = None

        for p in range(model["n"]):
            if p in known:
                continue
            usable = tuple(fid for fid in inc.get(p, ()) if fid in determined)
            if len(usable) >= 2:
                found = {
                    "point": p,
                    "construct_flats": usable[:2],
                    "extra_flats": usable[2:],
                }
                break

        if found is None:
            break

        known.add(found["point"])
        history.append(found)

    return tuple(sorted(known)), tuple(history)


def rv_seed_candidates(model, known):
    """
    Return unknown points with their current parameter cost:
      cost 1: lies on exactly one determined rich flat;
      cost 2: lies on no determined rich flat.
    Points on >=2 determined flats should already be propagated first.
    """
    known = set(known)
    determined = set(rv_determined_flats(model, known))
    inc = rv_incidence_map(model)
    out = []

    for p in range(model["n"]):
        if p in known:
            continue
        usable = tuple(fid for fid in inc.get(p, ()) if fid in determined)
        if len(usable) >= 2:
            cost = 0
        elif len(usable) == 1:
            cost = 1
        else:
            cost = 2
        out.append({"point": p, "parameter_cost": cost, "flats": usable})

    return tuple(out)


def rv_find_seed_plans(
    model,
    frame,
    max_seeds=3,
    one_parameter_only=True,
    limit=200
):
    """
    Search combinatorially for seed sequences which,
    together with a projective frame, generate the full model.

    This is a planner only:
    no symbolic coordinates or polynomial arithmetic are used.
    """

    if not rv_is_general_frame(
        model,
        frame
    ):
        raise ValueError(
            "frame is not in general position"
        )

    base, _ = rv_combinatorial_closure(
        model,
        frame
    )

    results = []
    seen_states = set()


    def seed_signature(seeds):
        """
        Convert mutable seed dictionaries into a canonical,
        hashable representation for memoization.
        """

        return tuple(
            (
                int(S["point"]),
                int(S["parameter_cost"]),
                tuple(
                    int(fid)
                    for fid in S["flats"]
                ),
            )
            for S in seeds
        )


    def rec(
        known,
        seeds
    ):
        if len(results) >= limit:
            return

        closed, _ = rv_combinatorial_closure(
            model,
            known
        )

        key = (
            tuple(closed),
            seed_signature(seeds),
        )

        if key in seen_states:
            return

        seen_states.add(key)


        # Full combinatorial closure achieved.
        if len(closed) == model["n"]:

            results.append(
                tuple(
                    {
                        "point":
                            int(S["point"]),

                        "parameter_cost":
                            int(S["parameter_cost"]),

                        "flats":
                            tuple(
                                int(fid)
                                for fid in S["flats"]
                            ),
                    }
                    for S in seeds
                )
            )

            return


        if len(seeds) >= max_seeds:
            return


        candidates = rv_seed_candidates(
            model,
            closed
        )

        # Cost-zero points should already have been
        # absorbed by combinatorial closure.
        candidates = [
            C
            for C in candidates
            if C["parameter_cost"] > 0
        ]

        if one_parameter_only:

            candidates = [
                C
                for C in candidates
                if C["parameter_cost"] == 1
            ]


        candidates.sort(
            key=lambda C: (
                C["parameter_cost"],
                C["point"],
                tuple(C["flats"]),
            )
        )


        for C in candidates:

            new_known = tuple(
                sorted(
                    set(closed).union(
                        {C["point"]}
                    )
                )
            )

            new_seed = {
                "point":
                    int(C["point"]),

                "parameter_cost":
                    int(C["parameter_cost"]),

                "flats":
                    tuple(
                        int(fid)
                        for fid in C["flats"]
                    ),
            }

            rec(
                new_known,
                seeds + [new_seed]
            )


    rec(
        base,
        []
    )

    return tuple(results)


# =============================================================================
# 4. SYMBOLIC REALIZATION / PROPAGATION
# =============================================================================


def rv_standard_frame_points(R):
    """Standard dual projective frame keyed by local frame position 0..3."""
    return (
        (R(1), R(0), R(0)),
        (R(0), R(1), R(0)),
        (R(0), R(0), R(1)),
        (R(1), R(1), R(1)),
    )


def rv_points_from_frame(R, frame):
    std = rv_standard_frame_points(R)
    return {frame[i]: std[i] for i in range(4)}


def rv_symbolic_flat_lines(model, points):
    """Return determined dual lines (one per rich flat with >=2 known points)."""
    points = dict(points)
    out = {}
    for fid, F in enumerate(model["flats"]):
        known_here = [p for p in F if p in points]
        if len(known_here) >= 2:
            p, q = known_here[0], known_here[1]
            L = rv_cross(points[p], points[q])
            if not rv_is_zero_vector(L):
                out[fid] = {
                    "line": L,
                    "anchors": (p, q),
                }
    return out


def rv_symbolic_propagate(model, points):
    """
    Construct every point forced as the intersection of two determined rich flats.
    No projective normalization is performed, so coordinates stay polynomial.
    """
    points = dict(points)
    inc = rv_incidence_map(model)
    history = []

    while True:
        flat_lines = rv_symbolic_flat_lines(model, points)
        found = None

        for p in range(model["n"]):
            if p in points:
                continue

            usable = tuple(fid for fid in inc.get(p, ()) if fid in flat_lines)
            if len(usable) >= 2:
                f1, f2 = usable[0], usable[1]
                candidate = rv_cross(flat_lines[f1]["line"], flat_lines[f2]["line"])

                if rv_is_zero_vector(candidate):
                    raise ValueError(
                        "symbolic construction of point {} collapsed identically "
                        "from flats {} and {}".format(p, f1, f2)
                    )

                found = {
                    "point": p,
                    "construct_flats": (f1, f2),
                    "extra_flats": usable[2:],
                    "coordinates": candidate,
                }
                break

        if found is None:
            break

        points[found["point"]] = found["coordinates"]
        history.append(found)

    return points, tuple(history)


def rv_seed_on_determined_flat(model, points, point_index, t, chart=0, flat_id=None):
    """
    Put an unknown point at a generic point of one determined rich flat.

    chart=0: P + t Q   (first homogeneous coefficient fixed to 1)
    chart=1: t P + Q   (second homogeneous coefficient fixed to 1)

    Together the two charts cover the seed P^1. The returned metadata records
    exactly which chart was used.
    """
    points = dict(points)
    p = int(point_index)

    candidates = []
    for fid in rv_incidence_map(model).get(p, ()):
        F = model["flats"][fid]
        known_here = [q for q in F if q in points]
        if len(known_here) >= 2:
            candidates.append((fid, known_here[0], known_here[1]))

    if flat_id is not None:
        candidates = [C for C in candidates if C[0] == int(flat_id)]

    if not candidates:
        raise ValueError("point does not lie on a currently determined rich flat")

    fid, a, b = candidates[0]
    P, Q = points[a], points[b]

    if int(chart) == 0:
        X = rv_linear_combo(P, 1, Q, t)
        chart_desc = "P+tQ"
    elif int(chart) == 1:
        X = rv_linear_combo(P, t, Q, 1)
        chart_desc = "tP+Q"
    else:
        raise ValueError("P^1 seed chart must be 0 or 1")

    return X, {
        "point": p,
        "flat": fid,
        "anchors": (a, b),
        "chart": int(chart),
        "chart_description": chart_desc,
    }


def rv_free_point_P2(s, t, chart=0):
    """Generic projective point in one of the three standard affine charts of P^2."""
    if int(chart) == 0:
        return (1, s, t)
    if int(chart) == 1:
        return (s, 1, t)
    if int(chart) == 2:
        return (s, t, 1)
    raise ValueError("P^2 chart must be 0, 1, or 2")


def rv_flat_closure_equations(model, points):
    """
    For each rich flat F={p0,p1,...}, impose det(p0,p1,pj)=0 for j>=2.
    Identically-zero equations are omitted but recorded.
    """
    points = dict(points)
    equations = []
    identities = []

    for fid, F in enumerate(model["flats"]):
        if not all(p in points for p in F):
            continue
        a, b = F[0], F[1]
        for c in F[2:]:
            f = rv_det(points[a], points[b], points[c])
            rec = {
                "flat": fid,
                "triple": (a, b, c),
                "polynomial": f,
            }
            if f == 0:
                identities.append(rec)
            else:
                equations.append(rec)

    return {
        "equations": tuple(equations),
        "identities": tuple(identities),
    }


def rv_forbidden_determinants(model, points):
    """All forbidden-triple determinants after every point is known."""
    points = dict(points)
    if len(points) != model["n"]:
        missing = sorted(set(range(model["n"])) - set(points))
        raise ValueError("not all points are known; missing {}".format(missing))

    zero_forbidden = []
    nonzero = []

    for T in rv_forbidden_triples(model):
        i, j, k = T
        f = rv_det(points[i], points[j], points[k])
        rec = {"triple": T, "polynomial": f}
        if f == 0:
            zero_forbidden.append(rec)
        else:
            nonzero.append(rec)

    return {
        "identically_zero": tuple(zero_forbidden),
        "nonzero": tuple(nonzero),
    }


def rv_closure_factor_diagnostic(model, points):
    """
    Factor-based diagnostic for closure and boundary factors.

    Candidate factors come from nontrivial closure equations. A candidate is
    labelled 'degeneracy' if it also divides at least one forbidden determinant.
    This is a diagnostic, not a substitute for a full scheme-theoretic saturation.
    """
    closure = rv_flat_closure_equations(model, points)
    closure_polys = [rec["polynomial"] for rec in closure["equations"]]

    candidates = set()
    for f in closure_polys:
        for g, _e in rv_nonconstant_factors(f):
            candidates.add(g)

    forbidden = rv_forbidden_determinants(model, points)
    bad = set()

    for rec in forbidden["nonzero"]:
        f = rec["polynomial"]
        for g, _e in rv_nonconstant_factors(f):
            if g in candidates:
                bad.add(g)

    return {
        "closure": closure,
        "closure_polynomials": tuple(closure_polys),
        "candidate_factors": tuple(sorted(candidates, key=str)),
        "degeneracy_factors": tuple(sorted(bad, key=str)),
        "essential_factors": tuple(sorted(candidates - bad, key=str)),
        "identically_forbidden": forbidden["identically_zero"],
    }


# =============================================================================
# 5. JACOBIAN / LOCAL EXACT DIAGNOSTICS
# =============================================================================


def rv_jacobian_matrix(polys):
    polys = list(polys)
    if not polys:
        raise ValueError("need at least one polynomial")
    R = parent(polys[0])
    vars_ = R.gens()
    return matrix(
        R,
        [[R(f).derivative(x) for x in vars_] for f in polys],
    )


def rv_jacobian_at(polys, values, codomain=None):
    """
    Exact Jacobian evaluation. Returns tangent-space information.

    NOTE: nvars-rank is the Zariski tangent-space dimension. It equals the local
    dimension only at a smooth point; the engine deliberately does not conflate
    those two notions.
    """
    polys = list(polys)
    if not polys:
        raise ValueError("need at least one polynomial")

    R = parent(polys[0])
    values = list(values)
    if len(values) != R.ngens():
        raise ValueError("expected {} coordinate values".format(R.ngens()))

    if codomain is None:
        codomain = rv_common_parent(values)

    J = rv_jacobian_matrix(polys)
    phi = R.hom(values, codomain)

    J0 = matrix(
        codomain,
        J.nrows(),
        J.ncols(),
        [phi(entry) for entry in J.list()],
    )

    rank = int(J0.rank())
    tangent_dim = int(R.ngens() - rank)

    return {
        "matrix": J0,
        "rank": rank,
        "tangent_dimension": tangent_dim,
        "nvars": int(R.ngens()),
    }

def rv_test_compatibility(verbose=True):
    # Common-parent test over a quadratic field.
    K = QuadraticField(15, "rv_s")
    s = K.gen()
    U = rv_common_parent([QQ(0), s, QQ(1) / 3])
    assert U == K

    # Multivariate factor / canonicalization / irreducibility wrappers.
    R = PolynomialRing(QQ, names=("rv_x", "rv_y"))
    x, y = R.gens()
    fac = rv_factor_list(x**2 - y**2)
    assert len(fac) == 2
    assert rv_is_irreducible(x**2 + y**2 + 1)

    # Exact rank.
    A = matrix(QQ, [[1, 2], [2, 4]])
    assert A.rank() == 1

    # Saturation toy test: <x*y> : x^infinity = <y>.
    sat = rv_saturate_by_polynomial([x * y], x)
    assert len(sat["elimination"]) == 1
    assert rv_canonical_poly(sat["elimination"][0]) == rv_canonical_poly(y)

    # New multi-inequality saturation wrapper should agree on the toy case.
    for method in ("product", "inverse_variables", "sequential"):
        sat_new = rv_saturate_by_polynomials([x * y], [x], method=method)
        assert len(sat_new["elimination"]) == 1
        assert rv_canonical_poly(sat_new["elimination"][0]) == rv_canonical_poly(y)

    if verbose:
        print("Compatibility tests........ PASS")
    return True










# =============================================================================
# 8. EXPERIMENT HELPERS / REPORTING
# =============================================================================


def rv_new_experiment_from_triples(n, triples, name="experiment"):
    M = rv_make_model(n, dependent_triples=triples, name=name)
    rv_model_summary(M)
    frames = rv_find_general_frames(M, limit=10)
    print("general frames found (first 10) =", frames)
    return M


def rv_new_experiment_from_flats(n, flats, name="experiment"):
    M = rv_make_model(n, flats=flats, name=name)
    rv_model_summary(M)
    frames = rv_find_general_frames(M, limit=10)
    print("general frames found (first 10) =", frames)
    return M


def rv_plan_report(model, frame):
    if not rv_is_general_frame(model, frame):
        raise ValueError("frame is not in general position")

    closed, history = rv_combinatorial_closure(model, frame)
    print("frame =", tuple(frame))
    print("closure =", closed)
    print("forced history =")
    for H in history:
        print(" ", H)

    print("seed candidates =")
    for C in rv_seed_candidates(model, closed):
        print(" ", C)


def rv_symbolic_report(model, points):
    print("known points =", sorted(points))
    print("all points constructed =", len(points) == model["n"])

    closure = rv_flat_closure_equations(model, points)
    print("nontrivial closure equations =", len(closure["equations"]))
    print("identical flat equations =", len(closure["identities"]))

    if len(points) == model["n"]:
        F = rv_forbidden_determinants(model, points)
        print("identically forced forbidden triples =", len(F["identically_zero"]))
        if F["identically_zero"]:
            for rec in F["identically_zero"][:20]:
                print("  BAD:", rec["triple"])

    return closure


# Legacy-layer boundary retained in v3 for source navigation


# =============================================================================
# 9. COMPLETE PROJECTIVE CHART FOR REAL / RATIONAL REALIZABILITY
# =============================================================================
# Main design improvement:
#   choose an ordinary pair (a,b), i.e. no rich flat contains both a and b,
#   and use it as the line at infinity. After fixing a 4-point projective frame
#   (a,b,c,d) to e1,e2,e3,(1,1,1), respectively—or a 3-point basis to e1,e2,e3
#   if no 4-point arc exists—every other point has the affine form (x_i,y_i,1).
#   This is a complete chart for every
#   realization of this matroid in which (a,b) is ordinary.  For real point
#   configurations, existence of an ordinary pair follows from Sylvester--
#   Gallai, provided the configuration is not wholly collinear.
#
# Unlike symbolic propagation, this chart does not divide by construction
# determinants and does not silently discard components on which a chosen
# construction fails.  It is usually the right starting point for studying
# the Q-realization variety.  The older propagation engine remains available
# for low-variable construction charts and diagnostics.
# =============================================================================


def rv_pair_is_ordinary(model, i, j):
    """Return True iff no rich flat contains the pair {i,j}."""
    rv_validate_model(model)
    i, j = int(i), int(j)
    if i == j or min(i, j) < 0 or max(i, j) >= model["n"]:
        return False
    pair = tuple(sorted((i, j)))
    rich_pairs = {P for F in model["flats"] for P in combinations(F, 2)}
    return pair not in rich_pairs


def rv_find_q_chart_frame(model, limit=None):
    """Find (a,b,c,d) where (a,b) is ordinary and the four-point frame is general.

    The first two frame points are deliberately the ordinary pair.  This makes
    the affine chart below complete, rather than merely a convenient local chart.
    Returns None if no such frame exists.
    """
    rv_validate_model(model)
    n = model["n"]
    rich_pairs = {P for F in model["flats"] for P in combinations(F, 2)}
    checked = 0
    for a, b in combinations(range(n), 2):
        if (a, b) in rich_pairs:
            continue
        rest = [i for i in range(n) if i not in (a, b)]
        for c, d in combinations(rest, 2):
            checked += 1
            frame = (a, b, c, d)
            if rv_is_general_frame(model, frame):
                return frame
            if limit is not None and checked >= int(limit):
                return None
    return None


def rv_find_q_chart_three_frame(model):
    """Find a basis (a,b,c) with (a,b) an ordinary pair.

    Unlike a four-point projective frame, this three-point basis always leaves
    a two-dimensional diagonal gauge stabilizer. That is harmless for existence
    questions and provides a fallback for valid configurations with no four-point
    arc (for example, all but one point lying on a single line).
    """
    rv_validate_model(model)
    n = model["n"]
    rich_pairs = {P for F in model["flats"] for P in combinations(F, 2)}
    for a, b in combinations(range(n), 2):
        if (a, b) in rich_pairs:
            continue
        for c in range(n):
            if c not in (a, b):
                # An ordinary pair cannot share a dependent triple with c.
                return (a, b, c)
    return None


def rv_q_chart_system(model, frame=None, base_ring=QQ, order="degrevlex", prefix="rv"):
    """Compile incidence data into an exact affine coordinate system.

    Parameters
    ----------
    model : realization-engine model
    frame : ordered three-point basis (a,b,c) or four-point frame (a,b,c,d).
        In either case (a,b) must be an ordinary pair; a four-point frame must
        have no collinear triple. If omitted, a four-point frame is preferred,
        with a three-point basis as a complete fallback.
    base_ring : normally QQ; may be GF(p) for finite-field experiments.
    order : polynomial monomial order.
    prefix : prefix used for generated coordinate variable names.

    Returns a dictionary containing the polynomial ring, point coordinates,
    flat-closure equations, and every forbidden-triple determinant.
    """
    rv_validate_model(model)
    if frame is None:
        frame = rv_find_q_chart_frame(model)
        if frame is None:
            frame = rv_find_q_chart_three_frame(model)
        if frame is None:
            raise ValueError(
                "No ordinary pair found. A real non-collinear configuration "
                "would have one by Sylvester-Gallai; check the model data."
            )
    frame = tuple(int(i) for i in frame)
    if len(frame) not in (3, 4) or len(set(frame)) != len(frame):
        raise ValueError("frame must be an ordered three-point basis or four-point projective frame")
    if min(frame) < 0 or max(frame) >= model["n"]:
        raise ValueError("frame index outside 0..{}".format(model["n"] - 1))
    if len(frame) == 4 and not rv_is_general_frame(model, frame):
        raise ValueError("four-point frame is not in general position")
    if len(frame) == 3 and tuple(sorted(frame)) in model["dependent_set"]:
        raise ValueError("three-point basis is collinear")
    if not rv_pair_is_ordinary(model, frame[0], frame[1]):
        raise ValueError(
            "the first two frame points must form an ordinary pair; "
            "otherwise the affine chart need not cover all realizations"
        )

    free_points = [i for i in range(model["n"]) if i not in frame]
    if not free_points:
        raise ValueError("this coordinate compiler expects at least one non-frame point")

    names = []
    for i in free_points:
        names.extend(("{}_x{}".format(prefix, i), "{}_y{}".format(prefix, i)))
    R = PolynomialRing(base_ring, names=tuple(names), order=order)
    gens = list(R.gens())
    variables = {}
    for j, i in enumerate(free_points):
        variables[i] = (gens[2 * j], gens[2 * j + 1])

    one, zero = R(1), R(0)
    std = (
        (one, zero, zero),
        (zero, one, zero),
        (zero, zero, one),
        (one, one, one),
    )
    points = {frame[j]: std[j] for j in range(len(frame))}
    for i in free_points:
        x, y = variables[i]
        points[i] = (x, y, one)

    closure = rv_flat_closure_equations(model, points)
    forbidden = rv_forbidden_determinants(model, points)

    # Canonicalize and deduplicate equations up to nonzero scalar multiples.
    closure_polys = []
    closure_seen = set()
    for rec in closure["equations"]:
        f = R(rec["polynomial"])
        key = str(rv_canonical_poly(f)) if f != 0 else "0"
        if key not in closure_seen:
            closure_seen.add(key)
            closure_polys.append(f)

    # Keep the triple-to-polynomial records for auditing, while exposing a
    # deduplicated divisor list for saturation and diagnostics.
    forbidden_polys = []
    forbidden_seen = set()
    for rec in forbidden["nonzero"]:
        f = R(rec["polynomial"])
        key = str(rv_canonical_poly(f)) if f != 0 else "0"
        if key not in forbidden_seen:
            forbidden_seen.add(key)
            forbidden_polys.append(f)

    return {
        "model": model,
        "ring": R,
        "base_ring": base_ring,
        "frame": frame,
        "points": points,
        "variables_by_point": variables,
        "variables": tuple(R.gens()),
        "free_points": tuple(free_points),
        "closure": closure,
        "closure_polynomials": tuple(closure_polys),
        "forbidden": forbidden,
        "forbidden_polynomials": tuple(forbidden_polys),
        "identically_forbidden": tuple(forbidden["identically_zero"]),
        "chart_is_complete_for_model": True,
        "chart_note": (
            "The first two basis points form an ordinary pair and are sent to "
            "the line at infinity; every other point is normalized to z=1."
            if len(frame) == 3 else
            "The first two frame points form an ordinary pair and are sent to "
            "the line at infinity; the full four-point frame is fixed."
        ),
    }


def rv_q_chart_ideal(system):
    """The unsaturated incidence-closure ideal for a compiled chart."""
    R = system["ring"]
    return R.ideal(list(system["closure_polynomials"]))


def rv_q_chart_summary(system, print_report=True, compute_dimension=False):
    """Return chart-size and combinatorial data; compute ideal dimension only on request.

    Computing a dimension may require a costly Groebner basis in the complete
    high-variable chart. The default summary avoids triggering that computation.
    """
    model = system["model"]
    I = rv_q_chart_ideal(system)
    if compute_dimension:
        try:
            dimension = int(I.dimension())
        except Exception as exc:
            dimension = None
            dimension_error = str(exc)
        else:
            dimension_error = None
    else:
        dimension = None
        dimension_error = None
    summary = {
        "model_name": model["name"],
        "n_points": model["n"],
        "frame": system["frame"],
        "ordinary_pair": system["frame"][:2],
        "n_variables": int(system["ring"].ngens()),
        "n_closure_equations_raw": len(system["closure"]["equations"]),
        "n_closure_equations_deduplicated": len(system["closure_polynomials"]),
        "n_forbidden_triples": len(system["forbidden"]["nonzero"])
            + len(system["forbidden"]["identically_zero"]),
        "n_distinct_forbidden_divisors": len(system["forbidden_polynomials"]),
        "n_identically_forbidden": len(system["identically_forbidden"]),
        "ideal_dimension": dimension,
        "ideal_dimension_computed": bool(compute_dimension),
        "ideal_dimension_error": dimension_error,
        "metrics": rv_model_metrics(model),
    }
    if print_report:
        print("Q-realizability chart")
        print("  model:", summary["model_name"])
        print("  points:", summary["n_points"])
        print("  frame:", summary["frame"])
        print("  ordinary pair:", summary["ordinary_pair"])
        print("  variables:", summary["n_variables"])
        print("  closure equations (deduplicated):", summary["n_closure_equations_deduplicated"])
        print("  forbidden triples:", summary["n_forbidden_triples"])
        print("  distinct forbidden determinant polynomials:", summary["n_distinct_forbidden_divisors"])
        print("  identically forbidden triples:", summary["n_identically_forbidden"])
        print("  closure-ideal dimension:", summary["ideal_dimension"] if compute_dimension else "not computed")
        print("  Chern slope:", summary["metrics"]["slope"])
        if summary["ideal_dimension_error"]:
            print("  dimension diagnostic error:", summary["ideal_dimension_error"])
    return summary


# =============================================================================
# 10. EXACT REALIZATION CERTIFICATES AND MODEL VALIDATION
# =============================================================================

def rv_validate_model(model):
    """Strictly validate all internal combinatorial invariants of a model.

    The original v1 validator only checked that several keys were present.
    This version recomputes maximal flats, dependent triples, and pair ownership.
    """
    if callable(model):
        raise TypeError(
            "Expected a realization model, not a constructor. Call the constructor first."
        )
    if not isinstance(model, dict):
        raise TypeError("Expected realization model dict, got {}".format(type(model).__name__))
    required = {"n", "name", "flats", "dependent_triples", "dependent_set"}
    missing = required - set(model)
    if missing:
        raise ValueError("Malformed realization model; missing fields: {}".format(sorted(missing)))
    n = int(model["n"])
    if n < 3:
        raise ValueError("a model needs at least three points")
    flats = rv_normalize_flats(model["flats"])
    for F in flats:
        if min(F) < 0 or max(F) >= n:
            raise ValueError("flat index outside 0..{}: {}".format(n - 1, F))
    if tuple(model["flats"]) != tuple(flats):
        raise ValueError("model flats are not in canonical normalized form")
    expected = tuple(rv_dependent_triples_from_flats(flats))
    supplied = tuple(sorted(tuple(sorted(set(int(i) for i in T))) for T in model["dependent_triples"]))
    if supplied != expected:
        raise ValueError("dependent_triples do not agree exactly with the supplied maximal flats")
    if set(model["dependent_set"]) != set(expected):
        raise ValueError("dependent_set does not agree with dependent_triples / flats")
    expected_owner = {}
    for fid, F in enumerate(flats):
        for pair in combinations(F, 2):
            if pair in expected_owner:
                raise ValueError("pair {} belongs to two rich flats".format(pair))
            expected_owner[pair] = fid
    # pair_owner is a cached index, not part of the public minimal model schema.
    if "pair_owner" in model and model["pair_owner"] != expected_owner:
        raise ValueError("pair_owner is stale or inconsistent with flats")
    if "rv_type" in model and model["rv_type"] != "model":
        raise ValueError("object is tagged as {}, not model".format(model["rv_type"]))
    if "schema_version" in model and int(model["schema_version"]) > RV_SCHEMA_VERSION:
        raise ValueError("model schema {} is newer than engine schema {}".format(
            model["schema_version"], RV_SCHEMA_VERSION
        ))
    expected_fp = rv_model_fingerprint(model)
    if "fingerprint" in model and str(model["fingerprint"]) != expected_fp:
        raise ValueError("model fingerprint is stale or inconsistent with incidence data")
    return model


def rv_validate_realization(model, points, require_exact_matroid=True):
    """Check projective points against every intended and forbidden triple.

    `points` is a dict {index: (x,y,z)} or a sequence of homogeneous triples.
    This is an exact certificate checker when coordinates are in QQ or an exact
    field. For floating point input, use it only as a rough diagnostic.
    """
    rv_validate_model(model)
    if not isinstance(points, dict):
        points = {i: tuple(P) for i, P in enumerate(points)}
    missing = sorted(set(range(model["n"])) - set(points))
    extra = sorted(set(points) - set(range(model["n"])))
    if missing or extra:
        return {
            "valid": False,
            "missing_points": missing,
            "extra_points": extra,
            "zero_vectors": (),
            "coincident_pairs": (),
            "violated_incidence_triples": (),
            "extra_incidence_triples": (),
        }

    P = {i: tuple(points[i]) for i in range(model["n"])}
    malformed_vectors = [i for i, v in P.items() if len(v) != 3]
    zero_vectors = [i for i, v in P.items() if len(v) == 3 and rv_is_zero_vector(v)]
    coincident_pairs = []
    for i, j in combinations(range(model["n"]), 2):
        if i not in zero_vectors and j not in zero_vectors and i not in malformed_vectors and j not in malformed_vectors:
            if rv_projectively_equal(P[i], P[j]):
                coincident_pairs.append((i, j))

    violated = []
    extra = []
    if not malformed_vectors and not zero_vectors:
        for T in combinations(range(model["n"]), 3):
            det = rv_det(P[T[0]], P[T[1]], P[T[2]])
            is_dep = tuple(T) in model["dependent_set"]
            if is_dep and det != 0:
                violated.append((T, det))
            elif (not is_dep) and det == 0:
                extra.append((T, det))

    valid = not malformed_vectors and not zero_vectors and not coincident_pairs and not violated
    if require_exact_matroid:
        valid = valid and not extra
    return {
        "valid": bool(valid),
        "missing_points": [],
        "extra_points": [],
        "zero_vectors": tuple(zero_vectors),
        "malformed_vectors": tuple(malformed_vectors),
        "coincident_pairs": tuple(coincident_pairs),
        "violated_incidence_triples": tuple(violated),
        "extra_incidence_triples": tuple(extra),
    }


def rv_chart_solution_points(system, solution):
    """Evaluate the chart's projective point expressions at a variable assignment.

    `solution` may be a list aligned with system['variables'], or a Sage variety()
    dictionary keyed by the ring's generators.
    """
    R = system["ring"]
    if isinstance(solution, dict):
        values = [solution[v] if v in solution else solution[str(v)] for v in R.gens()]
    else:
        values = list(solution)
        if len(values) != R.ngens():
            raise ValueError("expected {} coordinate values".format(R.ngens()))
    subs = {R.gens()[i]: values[i] for i in range(R.ngens())}
    return {
        i: tuple(R(entry).subs(subs) for entry in P)
        for i, P in system["points"].items()
    }


def rv_validate_chart_solution(system, solution):
    """Evaluate and exactly certify a point of the compiled chart."""
    P = rv_chart_solution_points(system, solution)
    certificate = rv_validate_realization(system["model"], P, require_exact_matroid=True)
    return {"points": P, "certificate": certificate}


def rv_primal_lines_from_dual_points(points):
    """Interpret dual projective points as primal line coefficients (a,b,c)."""
    if isinstance(points, dict):
        return {i: tuple(P) for i, P in points.items()}
    return {i: tuple(P) for i, P in enumerate(points)}


def rv_save_model_json(model, path):
    """Save only canonical combinatorial data; no Sage objects are serialized."""
    import json
    rv_validate_model(model)
    payload = {
        "rv_type": "model_export",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "fingerprint": rv_model_fingerprint(model),
        "name": str(model["name"]),
        "n": int(model["n"]),
        "flats": [list(F) for F in model["flats"]],
        "dependent_triples": [list(T) for T in model["dependent_triples"]],
    }
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
    return path


def rv_load_model_json(path):
    """Load a canonical model produced by rv_save_model_json()."""
    import json
    with open(path, "r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if "flats" in payload:
        model = rv_make_model(payload["n"], flats=payload["flats"], name=payload.get("name", "loaded"))
    else:
        model = rv_make_model(
            payload["n"], dependent_triples=payload["dependent_triples"],
            name=payload.get("name", "loaded")
        )
    rv_validate_model(model)
    return model


# =============================================================================
# 11. SATURATION BY FINITE SETS OF NONVANISHING CONDITIONS
# =============================================================================

def rv_saturate_by_polynomials(equations, nonzero_polynomials, method="inverse_variables",
                               max_auxiliary_variables=80):
    """Saturate I=(equations) by the product of a finite list of polynomials.

    Mathematically this computes I : (g_1 ... g_r)^infinity, so every g_i is
    required to be nonzero. Available strategies:

      * 'product': one Rabinowitsch variable and 1 - z*prod(g_i). Few variables,
        but potentially an enormous product polynomial.
      * 'inverse_variables': one variable z_i with z_i*g_i - 1 for each g_i.
        Low-degree auxiliary equations, but potentially many variables.
      * 'sequential': repeated single-polynomial saturation. Avoids a huge
        product, but requires repeated Groebner-basis computations.

    Exact but potentially expensive. It is deliberately not run automatically
    on every forbidden triple in large models. Start with selected bad factors,
    compare strategies on a reduced model, and record resource use.
    """
    equations = list(equations)
    nonzero_polynomials = list(nonzero_polynomials)
    candidates = equations + nonzero_polynomials
    if not candidates:
        raise ValueError("need at least one equation or nonzero polynomial to infer the ring")
    R = parent(candidates[0])
    equations = [R(f) for f in equations]
    gs = []
    seen = set()
    for raw in nonzero_polynomials:
        g = R(raw)
        if g == 0:
            return {
                "ring": R, "ideal": R.ideal([R(1)]), "elimination": [R(1)],
                "method": method, "status": "empty_open_set",
                "reason": "one requested nonvanishing polynomial is identically zero",
                "aux_ring": None, "aux_groebner": [],
            }
        if g.is_constant():
            # A nonzero constant never restricts the open set over a field.
            continue
        key = str(rv_canonical_poly(g))
        if key not in seen:
            seen.add(key)
            gs.append(rv_canonical_poly(g))

    I = R.ideal(equations)
    if not gs:
        return {
            "ring": R, "ideal": I, "elimination": list(I.gens()),
            "method": method, "status": "no_saturation_needed",
            "reason": "all nonvanishing conditions are nonzero constants or absent",
            "aux_ring": None, "aux_groebner": [],
        }
    if method == "sequential":
        current = list(I.gens())
        history = []
        for index, g in enumerate(gs):
            result = rv_saturate_by_polynomial(current, g)
            current = list(result["elimination"])
            history.append({"index": index, "polynomial": g, "n_generators": len(current)})
            if len(current) == 1 and current[0] == 1:
                break
        J = R.ideal(current)
        return {
            "ring": R, "ideal": J, "elimination": list(J.gens()),
            "method": method,
            "status": "empty open realization space" if J.is_one() else "saturated",
            "history": tuple(history), "aux_ring": None, "aux_groebner": [],
        }
    if method not in ("product", "inverse_variables"):
        raise ValueError("method must be 'product', 'inverse_variables', or 'sequential'")

    original_names = tuple(str(x) for x in R.gens())
    if method == "product":
        aux_names = ("rv_sat_all",)
        g = R(1)
        for h in gs:
            g *= h
        if g == 0:
            return {
                "ring": R, "ideal": R.ideal([R(1)]), "elimination": [R(1)],
                "method": method, "status": "empty_open_set",
                "reason": "the product of nonvanishing conditions is zero",
                "aux_ring": None, "aux_groebner": [],
            }
        saturation_relations = (g,)
    else:
        if max_auxiliary_variables is not None and len(gs) > int(max_auxiliary_variables):
            raise ValueError(
                "{} distinct nonvanishing polynomials exceed max_auxiliary_variables={}; "
                "try method='product' or 'sequential', or saturate a smaller factor set".format(
                    len(gs), max_auxiliary_variables
                )
            )
        aux_names = tuple("rv_inv_{}".format(i) for i in range(len(gs)))
        saturation_relations = tuple(gs)

    # Ensure auxiliary variable names do not collide with coordinate variables.
    while set(aux_names).intersection(original_names):
        aux_names = tuple("_" + name for name in aux_names)
    S = PolynomialRing(R.base_ring(), names=tuple(aux_names) + original_names, order="lex")
    SG = list(S.gens())
    naux = len(aux_names)
    phi = R.hom(SG[naux:], S)
    equations_S = [phi(f) for f in equations]
    if method == "product":
        equations_S.append(S(1) - SG[0] * phi(saturation_relations[0]))
    else:
        equations_S.extend(
            S(1) - SG[i] * phi(gs[i]) for i in range(len(gs))
        )
    Iaux = S.ideal(equations_S)
    G = list(Iaux.groebner_basis())
    aux_set = set(SG[:naux])
    elim_S = [f for f in G if not (set(rv_poly_variables(f)) & aux_set)]
    psi = S.hom([R(0)] * naux + list(R.gens()), R)
    elim_R = []
    keys = set()
    for f in elim_S:
        h = psi(f)
        if h != 0:
            h = rv_canonical_poly(h)
        key = str(h)
        if key not in keys:
            keys.add(key)
            elim_R.append(h)
    J = R.ideal(elim_R)
    return {
        "ring": R, "ideal": J, "elimination": elim_R,
        "method": method,
        "status": "empty open realization space" if J.is_one() else "saturated",
        "n_nonzero_conditions": len(gs), "n_auxiliary_variables": naux,
        "aux_ring": S, "aux_groebner": G,
    }


def rv_saturate_chart(system, method="inverse_variables", max_auxiliary_variables=80,
                      nonzero_polynomials=None):
    """Saturate the chart incidence ideal by chosen forbidden determinants.

    By default this uses all distinct forbidden determinants. For anything but
    small examples, first pass an explicit shortlist in `nonzero_polynomials`;
    full exact-matroid saturation can dominate the computation.
    """
    if nonzero_polynomials is None:
        nonzero_polynomials = system["forbidden_polynomials"]
    return rv_saturate_by_polynomials(
        list(system["closure_polynomials"]), list(nonzero_polynomials),
        method=method, max_auxiliary_variables=max_auxiliary_variables
    )


# =============================================================================
# 12. VARIETY DIAGNOSTICS AND RATIONAL-POINT SEARCH
# =============================================================================

def rv_realization_variety_report(system, compute_groebner=True, compute_dimension=True):
    """Describe the closure ideal without confusing it with the open realization space.

    The reported dimension is the dimension of the incidence-closure variety,
    before removing degenerate components by saturation. Dimension and Groebner
    computations are both optional because they can be expensive in the complete chart.
    """
    R = system["ring"]
    I = rv_q_chart_ideal(system)
    report = {
        "ideal": I,
        "n_variables": int(R.ngens()),
        "n_equations": len(system["closure_polynomials"]),
        "n_forbidden_divisors": len(system["forbidden_polynomials"]),
        "identically_forbidden": tuple(system["identically_forbidden"]),
        "is_unit_ideal": bool(I.is_one()),
        "dimension": None,
        "codimension": None,
        "groebner_basis_size": None,
        "groebner_basis": None,
        "status": None,
    }
    if I.is_one():
        report["dimension"] = -1
        report["codimension"] = None
        report["status"] = "inconsistent incidence equations"
        return report
    if compute_dimension:
        try:
            report["dimension"] = int(I.dimension())
            report["codimension"] = int(R.ngens() - report["dimension"])
        except Exception as exc:
            report["status"] = "dimension computation failed: {}".format(exc)
    if compute_groebner:
        try:
            G = list(I.groebner_basis())
            report["groebner_basis"] = tuple(G)
            report["groebner_basis_size"] = len(G)
        except Exception as exc:
            report["groebner_error"] = str(exc)
    if report["status"] is None:
        if not compute_dimension:
            report["status"] = "dimension not computed"
        elif report["dimension"] == 0:
            report["status"] = "zero-dimensional closure; enumerate Q-points exactly"
        else:
            report["status"] = (
                "positive-dimensional closure; rational-point existence requires "
                "arithmetic analysis or a targeted search"
            )
    return report


def rv_forced_extra_incidence_report(system, radical=False, max_triples=None):
    """Detect forbidden determinants that vanish on the entire closure variety.

    If a forbidden determinant belongs to the incidence ideal, it vanishes on
    every point of the closure variety, proving that this chart has no exact
    realization of the requested matroid. With `radical=True`, membership is
    tested in the radical ideal, which detects more cases but can be expensive.

    A determinant merely being nonzero as a polynomial is not enough: it can
    still vanish on every solution of the closure equations.
    """
    I = rv_q_chart_ideal(system)
    if I.is_one():
        return {
            "status": "inconsistent incidence equations",
            "ideal": I, "tested_triples": 0, "forced_extra_triples": (),
            "radical_test": bool(radical),
        }
    J = I.radical() if radical else I
    records = list(system["forbidden"]["nonzero"])
    if max_triples is not None:
        records = records[:int(max_triples)]
    forced = []
    for rec in records:
        f = rec["polynomial"]
        try:
            if f in J:
                forced.append({"triple": rec["triple"], "determinant": f})
        except Exception as exc:
            return {
                "status": "ideal-membership test failed: {}".format(exc),
                "ideal": I, "tested_triples": len(forced),
                "forced_extra_triples": tuple(forced),
                "radical_test": bool(radical),
            }
    return {
        "status": "forced extra incidence found" if forced else
                  "none detected by this ideal-membership test",
        "ideal": J, "tested_triples": len(records),
        "forced_extra_triples": tuple(forced),
        "radical_test": bool(radical),
        "note": "No detected triple does not prove nondegeneracy; other components or determinants may still degenerate.",
    }


def rv_rational_points_zero_dimensional(system, max_solutions=None):
    """Exactly enumerate rational solutions when the closure ideal is zero-dimensional.

    Every enumerated point is checked against all forbidden determinants. If the
    closure ideal has positive dimension, this function returns a diagnostic
    rather than pretending that bounded search can prove nonexistence.
    """
    if system["base_ring"] != QQ:
        raise ValueError("exact rational-point search requires a chart over QQ")
    if system["identically_forbidden"]:
        return {
            "status": "no nondegenerate realization in this chart",
            "reason": "at least one forbidden determinant is identically zero",
            "dimension": None, "raw_Q_points": (), "valid_Q_points": (),
        }
    I = rv_q_chart_ideal(system)
    if I.is_one():
        return {
            "status": "inconsistent incidence equations",
            "reason": "the closure ideal is the unit ideal",
            "dimension": -1, "raw_Q_points": (), "valid_Q_points": (),
        }
    dim = int(I.dimension())
    if dim > 0:
        return {
            "status": "positive-dimensional; exact enumeration not applicable",
            "reason": "use targeted rational specialization or study the component arithmetic",
            "dimension": dim, "raw_Q_points": (), "valid_Q_points": (),
        }
    try:
        raw = list(I.variety(QQ))
    except Exception as exc:
        return {
            "status": "Sage rational-variety enumeration failed",
            "reason": str(exc), "dimension": dim,
            "raw_Q_points": (), "valid_Q_points": (),
        }
    if max_solutions is not None:
        raw = raw[:int(max_solutions)]
    valid = []
    rejected = []
    for sol in raw:
        out = rv_validate_chart_solution(system, sol)
        if out["certificate"]["valid"]:
            valid.append({"assignment": sol, "points": out["points"], "certificate": out["certificate"]})
        else:
            rejected.append({"assignment": sol, "certificate": out["certificate"]})
    if valid:
        status = "found exact nondegenerate rational realization(s)"
    elif raw:
        status = "zero-dimensional closure has rational points, but all are degenerate"
    else:
        status = "zero-dimensional closure has no rational points in this chart"
    return {
        "status": status,
        "reason": None,
        "dimension": dim,
        "raw_Q_points": tuple(raw),
        "valid_Q_points": tuple(valid),
        "degenerate_Q_points": tuple(rejected),
    }


def _rv_small_rationals(height):
    from math import gcd
    H = int(height)
    if H < 1:
        raise ValueError("height must be at least 1")
    vals = set([QQ(0)])
    for b in range(1, H + 1):
        for a in range(-H, H + 1):
            if gcd(abs(a), b) == 1:
                vals.add(QQ(a) / QQ(b))
    return sorted(vals, key=lambda q: (abs(q), q.denominator(), q))


def rv_search_rational_specializations(system, solve_variables=None, height=2,
                                       trials=500, seed=0, max_solutions=5,
                                       max_variable_orders=4):
    """Search positive-dimensional incidence varieties by rational specialization.

    The default heuristic treats `dimension(I)` variables as free parameters and
    the remaining variables as dependent, then tries several variable orders.
    Pass `solve_variables` explicitly when a construction/parameter analysis has
    identified a better dependent-variable set.

    A hit is an exact rational realization certificate. Failure to find a hit is
    only a bounded-search result, never a proof that Q-points do not exist.
    """
    import random
    if system["base_ring"] != QQ:
        raise ValueError("rational specialization requires a chart over QQ")
    if system["identically_forbidden"]:
        return {"status": "impossible chart", "solutions": (), "trials": 0}
    R = system["ring"]
    I = rv_q_chart_ideal(system)
    if I.is_one():
        return {"status": "inconsistent incidence equations", "solutions": (), "trials": 0}
    variables = list(R.gens())
    nvars = len(variables)
    dim = int(I.dimension())

    if dim >= nvars:
        qvals = _rv_small_rationals(height)
        rng = random.Random(seed)
        found = []
        for attempt in range(int(trials)):
            vals = tuple(rng.choice(qvals) for _ in variables)
            out = rv_validate_chart_solution(system, vals)
            if out["certificate"]["valid"]:
                found.append({
                    "assignment_tuple": vals,
                    "assignment": dict(zip(variables, vals)),
                    "points": out["points"],
                    "certificate": out["certificate"],
                    "free_indices": tuple(range(nvars)),
                    "solve_indices": (),
                })
                if len(found) >= int(max_solutions):
                    break
        return {
            "status": "found exact rational realization(s)" if found else
                      "no realization found within this bounded direct search",
            "solutions": tuple(found), "trials": min(int(trials), attempt + 1 if int(trials) else 0),
            "specialized_zero_dimensional_systems": 0, "height": int(height),
            "dimension_estimate": dim,
            "warning": None if found else "This is not a proof of nonexistence of rational points.",
        }

    def normalize_var(v):
        if v in variables:
            return variables.index(v)
        name = str(v)
        for j, x in enumerate(variables):
            if str(x) == name:
                return j
        raise ValueError("unknown solve variable: {}".format(v))

    if solve_variables is not None:
        solve_indices = sorted(set(normalize_var(v) for v in solve_variables))
        free_indices = [i for i in range(nvars) if i not in solve_indices]
        orders = [(free_indices, solve_indices)]
    else:
        nfree = min(max(0, dim), nvars - 1) if nvars > 1 else 0
        orders = []
        for shift in range(min(int(max_variable_orders), max(1, nvars))):
            permutation = list(range(nvars))
            if permutation:
                permutation = permutation[shift:] + permutation[:shift]
            free = permutation[:nfree]
            solve = permutation[nfree:]
            if solve:
                key = (tuple(free), tuple(solve))
                if key not in [(tuple(a), tuple(b)) for a, b in orders]:
                    orders.append((free, solve))
        if not orders:
            orders = [([], list(range(nvars)))]

    qvals = _rv_small_rationals(height)
    rng = random.Random(seed)
    solutions = []
    attempted = 0
    specialized_zero_dimensional = 0
    assignments_seen = set()

    for free_indices, solve_indices in orders:
        if not solve_indices:
            continue
        max_grid = len(qvals) ** len(free_indices) if len(free_indices) < 8 else trials + 1
        if max_grid <= trials:
            samples = product(qvals, repeat=len(free_indices))
        else:
            def random_samples():
                local_seen = set()
                while len(local_seen) < int(trials):
                    tup = tuple(rng.choice(qvals) for _ in free_indices)
                    if tup not in local_seen:
                        local_seen.add(tup)
                        yield tup
            samples = random_samples()

        solve_names = tuple("rv_s{}".format(i) for i in solve_indices)
        S = PolynomialRing(QQ, names=solve_names, order="degrevlex")
        solve_gens = list(S.gens())
        images_template = [None] * nvars
        for j, idx in enumerate(solve_indices):
            images_template[idx] = solve_gens[j]

        for free_values in samples:
            assignment_key = (tuple(free_indices), tuple(free_values))
            if assignment_key in assignments_seen:
                continue
            assignments_seen.add(assignment_key)
            attempted += 1
            images = list(images_template)
            for idx, value in zip(free_indices, free_values):
                images[idx] = QQ(value)
            phi = R.hom(images, S)
            specialized = [phi(f) for f in system["closure_polynomials"]]
            J = S.ideal(specialized)
            if J.is_one():
                continue
            try:
                sdim = int(J.dimension())
            except Exception:
                continue
            if sdim != 0:
                continue
            specialized_zero_dimensional += 1
            try:
                sols = J.variety(QQ)
            except Exception:
                continue
            for partial in sols:
                vals = [None] * nvars
                for idx, value in zip(free_indices, free_values):
                    vals[idx] = QQ(value)
                for j, idx in enumerate(solve_indices):
                    vals[idx] = partial[solve_gens[j]]
                out = rv_validate_chart_solution(system, vals)
                if out["certificate"]["valid"]:
                    key = tuple(QQ(v) for v in vals)
                    if key not in [S0["assignment_tuple"] for S0 in solutions]:
                        solutions.append({
                            "assignment_tuple": key,
                            "assignment": dict(zip(variables, vals)),
                            "points": out["points"],
                            "certificate": out["certificate"],
                            "free_indices": tuple(free_indices),
                            "solve_indices": tuple(solve_indices),
                        })
                        if len(solutions) >= int(max_solutions):
                            return {
                                "status": "found exact rational realization(s)",
                                "solutions": tuple(solutions), "trials": attempted,
                                "specialized_zero_dimensional_systems": specialized_zero_dimensional,
                                "height": int(height), "dimension_estimate": dim,
                            }
    return {
        "status": "no realization found within this bounded specialization search",
        "solutions": tuple(solutions), "trials": attempted,
        "specialized_zero_dimensional_systems": specialized_zero_dimensional,
        "height": int(height), "dimension_estimate": dim,
        "warning": "This is not a proof of nonexistence of rational points.",
    }


# =============================================================================
# 13. FINITE-FIELD SEARCH AS A LOCAL FILTER
# =============================================================================

def rv_finite_field_search(model, p, frame=None, max_assignments=1_000_000,
                           stop_after=1):
    """Exhaustively search this complete affine chart over GF(p), if feasible.

    The routine checks all assignments to the 2(n-r) affine variables, where r is
    the size (3 or 4) of the chosen basis/frame, enforcing
    every intended incidence and every forbidden-triple nonvanishing condition.
    If the search budget covers the whole space, a negative result is exhaustive
    for GF(p) in this matroid chart.  A negative result at one prime does NOT by
    itself prove non-realizability over Q: a rational realization may have bad
    reduction at that prime.
    """
    p = int(p)
    if p < 2 or not is_prime(p):
        raise ValueError("p must be prime")
    K = GF(p)
    system = rv_q_chart_system(model, frame=frame, base_ring=K)
    nvars = system["ring"].ngens()
    total = int(p ** nvars)
    report = {
        "prime": p,
        "field": K,
        "frame": system["frame"],
        "n_variables": nvars,
        "total_assignments": total,
        "max_assignments": int(max_assignments),
        "solutions": (),
        "status": None,
    }
    if system["identically_forbidden"]:
        report["status"] = "no realization in this chart: forbidden determinant is identically zero"
        report["exhaustive"] = True
        return report
    if total > int(max_assignments):
        report["status"] = "budget exceeded; no conclusion"
        report["exhaustive"] = False
        return report

    R = system["ring"]
    closure = list(system["closure_polynomials"])
    forbidden = [rec["polynomial"] for rec in system["forbidden"]["nonzero"]]
    vals = list(K)
    found = []
    examined = 0
    for assignment in product(vals, repeat=nvars):
        examined += 1
        if any(f(*assignment) != 0 for f in closure):
            continue
        if any(g(*assignment) == 0 for g in forbidden):
            continue
        out = rv_validate_chart_solution(system, assignment)
        if out["certificate"]["valid"]:
            found.append({"assignment": tuple(assignment), "points": out["points"], "certificate": out["certificate"]})
            if len(found) >= int(stop_after):
                break
    report["examined_assignments"] = examined
    report["solutions"] = tuple(found)
    report["exhaustive"] = (not found and examined == total)
    if found:
        report["status"] = "found exact GF({}) realization(s)".format(p)
    elif examined == total:
        report["status"] = "no exact GF({}) realization in this chart (exhaustive)".format(p)
    else:
        report["status"] = "no point found before search stopped"
    return report


# =============================================================================
# 14. NUMERICAL REAL-POINT SEARCH (HEURISTIC ONLY)
# =============================================================================

def rv_search_real_realizations(model, frame=None, starts=20, scale=2.0,
                                residual_tolerance=1e-8, determinant_tolerance=1e-7,
                                max_nfev=3000, seed=0):
    """Numerically search for a real realization of the incidence model.

    Uses scipy least_squares when available. A returned candidate is numerical
    evidence only, not a proof of real realizability; exact certification requires
    exact coordinates or a separate real-algebraic argument.
    """
    import random
    try:
        from scipy.optimize import least_squares
        from sage.ext.fast_callable import fast_callable
    except Exception as exc:
        return {"status": "numerical dependencies unavailable", "reason": str(exc)}

    system = rv_q_chart_system(model, frame=frame, base_ring=QQ)
    if system["identically_forbidden"]:
        return {"status": "impossible in this chart", "system": system}
    R = system["ring"]
    variables = tuple(R.gens())
    closure_fc = [fast_callable(f, vars=variables, domain=RDF) for f in system["closure_polynomials"]]
    forbidden_fc = [fast_callable(f, vars=variables, domain=RDF) for f in
                    [rec["polynomial"] for rec in system["forbidden"]["nonzero"]]
                    if f != 0]
    rng = random.Random(seed)
    best = None
    for start in range(int(starts)):
        x0 = [rng.uniform(-float(scale), float(scale)) for _ in variables]
        if closure_fc:
            def residual(x):
                try:
                    return [float(f(*x)) for f in closure_fc]
                except Exception:
                    return [1e100] * len(closure_fc)
            try:
                fit = least_squares(residual, x0, max_nfev=int(max_nfev))
                candidate = [float(v) for v in fit.x]
                residuals = residual(candidate)
                max_residual = max((abs(v) for v in residuals), default=0.0)
            except Exception:
                continue
        else:
            candidate = x0
            max_residual = 0.0
        try:
            det_values = [abs(float(f(*candidate))) for f in forbidden_fc]
            min_forbidden = min(det_values) if det_values else float("inf")
        except Exception:
            continue
        score = (max_residual, -min_forbidden)
        if best is None or score < best["score"]:
            best = {"score": score, "assignment": tuple(candidate),
                    "max_closure_residual": max_residual,
                    "min_abs_forbidden_determinant": min_forbidden,
                    "start": start}
        if max_residual <= float(residual_tolerance) and min_forbidden > float(determinant_tolerance):
            point_map = {
                i: tuple(
                    float(fast_callable(R(entry), vars=variables, domain=RDF)(*candidate))
                    for entry in P
                )
                for i, P in system["points"].items()
            }
            return {
                "status": "numerical real realization candidate found",
                "assignment": tuple(candidate),
                "points": point_map,
                "max_closure_residual": max_residual,
                "min_abs_forbidden_determinant": min_forbidden,
                "start": start,
                "warning": "Numerical evidence only; not an exact realization certificate.",
                "system": system,
            }
    return {
        "status": "no acceptable numerical candidate found",
        "best_candidate": best,
        "warning": "Failure of this randomized optimizer is not a proof of non-realizability.",
        "system": system,
    }


# =============================================================================
# 15. Q-REALIZABILITY WORKFLOW / REGRESSION TESTS
# =============================================================================

def rv_q_realizability_report(model, frame=None, compute_groebner=False,
                              compute_dimension=False, print_report=True):
    """One-call entry point; expensive algebraic diagnostics are opt-in."""
    system = rv_q_chart_system(model, frame=frame, base_ring=QQ)
    chart = rv_q_chart_summary(
        system, print_report=print_report, compute_dimension=compute_dimension
    )
    variety = rv_realization_variety_report(
        system, compute_groebner=compute_groebner, compute_dimension=compute_dimension
    )
    report = {"system": system, "chart": chart, "variety": variety}
    if print_report:
        print("  variety status:", variety["status"])
        print("  Groebner basis size:", variety["groebner_basis_size"])
        print("  Reminder: these are closure-variety diagnostics before full saturation.")
    return report






# End of v2 compatibility layer; v3 orchestration follows below


# =============================================================================
# 16. AUTOMATIC LOW-PARAMETER CONSTRUCTION CHARTS
# =============================================================================

def rv_symbolic_construction_chart(model, frame=None, seed_plan=None,
                                   max_seeds=4, plan_limit=100,
                                   one_parameter_only=False, chart_choices=None,
                                   base_ring=QQ, order="degrevlex", prefix="rvp"):
    """Build a symbolic parameter chart from a combinatorial seed plan.

    This complements rv_q_chart_system(): the latter is the robust, complete
    affine chart (usually 2(n-4) variables, or 2(n-3) with a three-point basis);
    this function attempts to reduce the number of
    variables by propagating line intersections and using one variable for a seed
    on a determined flat (two variables for a free P^2 seed).

    `seed_plan` may be one plan returned by rv_find_seed_plans(). If omitted, the
    first suitable plan is used. `chart_choices` optionally maps point indices to
    P^1 chart 0 or 1; chart 0 is normally complete on the nondegenerate locus
    because its omitted endpoint would coincide with an already indexed point.

    The plan is checked combinatorially before symbolic construction. On its
    nondegenerate locus, the parameterization covers every realization in the
    selected fixed frame: cost-one seeds use a P^1 chart whose omitted endpoint
    would duplicate an existing point, and cost-two seeds use the complete affine
    chart (s,t,1). The raw closure ideal can still contain degenerate boundary
    points, so forbidden determinants must be imposed when making conclusions.
    """
    rv_validate_model(model)
    if frame is None:
        frame = rv_find_q_chart_frame(model)
    if frame is None:
        raise ValueError("no complete ordinary-pair frame found")
    frame = tuple(int(i) for i in frame)
    if not rv_is_general_frame(model, frame):
        raise ValueError("frame is not in general position")
    if not rv_pair_is_ordinary(model, frame[0], frame[1]):
        raise ValueError("the first two frame points must form an ordinary pair")

    if seed_plan is None:
        plans = rv_find_seed_plans(
            model, frame, max_seeds=max_seeds,
            one_parameter_only=one_parameter_only, limit=plan_limit
        )
        if not plans:
            raise ValueError(
                "no seed plan found under these limits; increase max_seeds/plan_limit, "
                "or use rv_q_chart_system()"
            )
        seed_plan = plans[0]
    seed_plan = tuple(seed_plan)
    chart_choices = {} if chart_choices is None else dict(chart_choices)

    # Validate that this is a genuine seed plan for the selected frame.
    known, _ = rv_combinatorial_closure(model, frame)
    known = set(known)
    seeded = set()
    for seed in seed_plan:
        p = int(seed["point"])
        cost = int(seed["parameter_cost"])
        if p in known or p in seeded:
            raise ValueError("seed plan repeats or pre-constructs point {}".format(p))
        available = {C["point"]: C for C in rv_seed_candidates(model, known)}
        if p not in available:
            raise ValueError("point {} is not a valid seed at this stage".format(p))
        candidate = available[p]
        if int(candidate["parameter_cost"]) != cost:
            raise ValueError(
                "seed point {} has combinatorial cost {}, not {}".format(
                    p, candidate["parameter_cost"], cost
                )
            )
        if cost == 1:
            supplied_flats = tuple(int(fid) for fid in seed.get("flats", ()))
            if not set(supplied_flats).intersection(candidate["flats"]):
                raise ValueError("cost-one seed {} has no valid determined flat in its plan".format(p))
        seeded.add(p)
        known.add(p)
        known, _ = rv_combinatorial_closure(model, known)
        known = set(known)
    if len(known) != model["n"]:
        missing = sorted(set(range(model["n"])) - known)
        raise ValueError("seed plan does not generate the full model; missing {}".format(missing))

    variable_names = []
    seed_variables = {}
    for seed_number, seed in enumerate(seed_plan):
        p = int(seed["point"])
        cost = int(seed["parameter_cost"])
        if cost == 1:
            names = ("{}_s{}".format(prefix, p),)
        elif cost == 2:
            names = ("{}_s{}".format(prefix, p), "{}_t{}".format(prefix, p))
        else:
            raise ValueError("invalid seed parameter cost {} for point {}".format(cost, p))
        seed_variables[p] = names
        variable_names.extend(names)
    if not variable_names:
        raise ValueError("seed plan has no free parameters; use direct closure tests")
    if len(set(variable_names)) != len(variable_names):
        raise ValueError("generated parameter names are not unique")

    R = PolynomialRing(base_ring, names=tuple(variable_names), order=order)
    ring_variables = list(R.gens())
    name_to_variable = dict(zip(variable_names, ring_variables))
    points = rv_points_from_frame(R, frame)
    points, hist_initial = rv_symbolic_propagate(model, points)
    propagation_history = [hist_initial]
    seed_metadata = []

    for seed in seed_plan:
        p = int(seed["point"])
        cost = int(seed["parameter_cost"])
        points, hist = rv_symbolic_propagate(model, points)
        propagation_history.append(hist)
        if p in points:
            raise ValueError("seed point {} was already constructed before it was seeded".format(p))

        if cost == 1:
            t = name_to_variable[seed_variables[p][0]]
            candidate_flats = tuple(int(fid) for fid in seed.get("flats", ()))
            chosen_flat = candidate_flats[0] if candidate_flats else None
            X, metadata = rv_seed_on_determined_flat(
                model, points, p, t,
                chart=int(chart_choices.get(p, 0)), flat_id=chosen_flat
            )
            metadata["parameter_names"] = seed_variables[p]
            metadata["parameter_cost"] = 1
            seed_metadata.append(metadata)
        else:
            s, t = (name_to_variable[name] for name in seed_variables[p])
            X = rv_free_point_P2(s, t, chart=2)  # (s,t,1), compatible with the ordinary-pair chart
            seed_metadata.append({
                "point": p, "parameter_cost": 2, "chart": 2,
                "chart_description": "(s,t,1)",
                "parameter_names": seed_variables[p],
            })
        points[p] = tuple(X)
        points, hist = rv_symbolic_propagate(model, points)
        propagation_history.append(hist)

    points, hist_final = rv_symbolic_propagate(model, points)
    propagation_history.append(hist_final)
    missing = sorted(set(range(model["n"])) - set(points))
    if missing:
        raise ValueError(
            "the seed plan did not symbolically construct all points; missing {}. "
            "Try another plan/frame or use the complete affine chart.".format(missing)
        )

    closure = rv_flat_closure_equations(model, points)
    forbidden = rv_forbidden_determinants(model, points)
    closure_polys = []
    seen = set()
    for rec in closure["equations"]:
        f = R(rec["polynomial"])
        key = str(rv_canonical_poly(f)) if f != 0 else "0"
        if key not in seen:
            seen.add(key)
            closure_polys.append(f)
    forbidden_polys = []
    seen = set()
    for rec in forbidden["nonzero"]:
        f = R(rec["polynomial"])
        key = str(rv_canonical_poly(f)) if f != 0 else "0"
        if key not in seen:
            seen.add(key)
            forbidden_polys.append(f)

    system = {
        "model": model,
        "ring": R,
        "base_ring": base_ring,
        "frame": frame,
        "points": points,
        "variables": tuple(R.gens()),
        "variables_by_point": {
            p: tuple(name_to_variable[name] for name in names)
            for p, names in seed_variables.items()
        },
        "free_points": tuple(sorted(seed_variables)),
        "closure": closure,
        "closure_polynomials": tuple(closure_polys),
        "forbidden": forbidden,
        "forbidden_polynomials": tuple(forbidden_polys),
        "identically_forbidden": tuple(forbidden["identically_zero"]),
        "chart_is_complete_for_model": True,
        "chart_note": (
            "Validated seed plan covers nondegenerate realizations in this fixed frame; "
            "forbidden determinants exclude degenerate boundary points of the closure variety."
        ),
        "construction": {
            "seed_plan": seed_plan,
            "seed_metadata": tuple(seed_metadata),
            "propagation_history": tuple(propagation_history),
            "parameter_count": int(R.ngens()),
            "missing_points": tuple(missing),
        },
    }
    # Factor diagnosis is intentionally optional: multivariate factorization can
    # dominate runtime on large/high-degree construction charts.
    return system


def rv_construction_chart_report(system, run_factor_diagnostic=False, print_report=True):
    """Summarize a low-parameter chart and optionally factor its closure equations."""
    summary = rv_q_chart_summary(system, print_report=False)
    summary["chart_is_complete_for_model"] = bool(system.get("chart_is_complete_for_model", False))
    summary["construction"] = system.get("construction")
    if run_factor_diagnostic:
        if len(system["points"]) != system["model"]["n"]:
            raise ValueError("cannot factor-diagnose an incomplete symbolic point set")
        summary["factor_diagnostic"] = rv_closure_factor_diagnostic(system["model"], system["points"])
    if print_report:
        print("Construction chart")
        print("  model:", summary["model_name"])
        print("  frame:", summary["frame"])
        print("  free parameters:", summary["n_variables"])
        print("  closure equations:", summary["n_closure_equations_deduplicated"])
        print("  forbidden determinant divisors:", summary["n_distinct_forbidden_divisors"])
        print("  coverage note:", system["chart_note"])
        if run_factor_diagnostic:
            D = summary["factor_diagnostic"]
            print("  closure factors:", len(D["candidate_factors"]))
            print("  factors diagnosed as degeneracy:", len(D["degeneracy_factors"]))
            print("  essential candidate factors:", len(D["essential_factors"]))
    return summary


# End of v2 compatibility layer; v3 orchestration follows below




def rv_seed_plan_search_report(model, frame, max_seeds=4,
                               one_parameter_only=False, limit=200,
                               strategy="enumerate", beam_width=32,
                               retain_pruned=True):
    """Purely combinatorial seed-plan search with explicit provenance.

    No polynomial ring, symbolic point, closure equation, or forbidden
    determinant is constructed by this function.  The returned object records
    whether the search was exhaustive under the requested bounds, whether a
    plan limit or beam cutoff was reached, deterministic plan signatures, and
    (for beam search) the kept/pruned partial states at each depth.

    `strategy="enumerate"` wraps the legacy deterministic DFS planner and asks
    for one extra plan so truncation at `limit` is detectable.

    `strategy="beam"` is intentionally heuristic.  It is useful when the
    combinatorial branching factor itself becomes large, but a negative result
    from a pruned beam MUST NOT be interpreted as nonexistence of a plan.
    The full layer trace can be retained so discarded branches remain auditable.
    """
    rv_validate_model(model)
    frame = tuple(int(i) for i in frame)
    if not rv_is_general_frame(model, frame):
        raise ValueError("frame is not in general position")
    strategy = str(strategy).lower()
    if strategy not in ("enumerate", "beam"):
        raise ValueError("strategy must be 'enumerate' or 'beam'")
    limit = int(limit)
    max_seeds = int(max_seeds)
    if limit <= 0:
        raise ValueError("limit must be positive")
    if max_seeds < 0:
        raise ValueError("max_seeds must be nonnegative")

    base_closed, base_history = rv_combinatorial_closure(model, frame)
    search_parameters = {
        "frame": frame,
        "max_seeds": max_seeds,
        "one_parameter_only": bool(one_parameter_only),
        "limit": limit,
        "strategy": strategy,
        "beam_width": int(beam_width) if strategy == "beam" else None,
        "retain_pruned": bool(retain_pruned) if strategy == "beam" else None,
        "candidate_order": "parameter_cost, point, determined-flat tuple",
    }

    if strategy == "enumerate":
        raw = rv_find_seed_plans(
            model, frame, max_seeds=max_seeds,
            one_parameter_only=one_parameter_only, limit=limit + 1
        )
        truncated = len(raw) > limit
        plans = tuple(raw[:limit])
        rows = []
        for i, plan in enumerate(plans):
            preview = rv_plan_complexity_preview(model, frame, plan)
            audit = rv_validate_seed_plan(model, frame, plan, require_full_closure=True)
            rows.append({
                "search_index": i,
                "status": "complete plan",
                "seed_plan": tuple(plan),
                "signature": preview["signature"],
                "n_parameters": int(preview["parameter_count"]),
                "seed_count": int(preview["seed_count"]),
                "forced_counts": tuple(preview["forced_counts"]),
                "combinatorial_score": tuple(preview["combinatorial_score"]),
                "audit": audit,
            })
        rows.sort(key=lambda r: (r["combinatorial_score"], r["search_index"]))
        return {
            "rv_type": "seed_plan_search_report",
            "schema_version": RV_SCHEMA_VERSION,
            "engine_version": RV_ENGINE_VERSION,
            "model_fingerprint": rv_model_fingerprint(model),
            "search_parameters": search_parameters,
            "base_closure": tuple(base_closed),
            "base_propagation_history": tuple(base_history),
            "plans_found": len(plans),
            "truncated_by_plan_limit": bool(truncated),
            "beam_pruning_occurred": False,
            "exhaustive_under_requested_bounds": not bool(truncated),
            "ranked_rows": tuple(rows),
            "search_digest": rv_digest(tuple(r["signature"] for r in rows)),
            "evidence": rv_make_evidence(
                "EXACT_CERTIFICATE" if not truncated else "HEURISTIC_SEARCH",
                claim=(
                    "combinatorial seed-plan enumeration completed within requested bounds"
                    if not truncated else
                    "combinatorial seed-plan enumeration truncated at explicit plan limit"
                ),
                method="pure combinatorial propagation; no symbolic compilation",
                payload={"plans_found": len(plans), "truncated": bool(truncated)},
                exact=True,
                exhaustive=not bool(truncated),
                caveats=() if not truncated else (
                    "More seed plans may exist beyond the explicit plan limit.",
                ),
            ),
        }

    # ------------------------------------------------------------------
    # Beam strategy.  Partial states are entirely combinatorial.
    # ------------------------------------------------------------------
    beam_width = int(beam_width)
    if beam_width <= 0:
        raise ValueError("beam_width must be positive")

    def normalize_plan(plan):
        return tuple({
            "point": int(S["point"]),
            "parameter_cost": int(S["parameter_cost"]),
            "flats": tuple(int(fid) for fid in S.get("flats", ())),
        } for S in plan)

    def state_score(closed, plan):
        cost = sum(int(S["parameter_cost"]) for S in plan)
        return (
            cost,
            -len(closed),
            len(plan),
            rv_seed_plan_signature(plan),
        )

    frontier = ({"closed": tuple(base_closed), "plan": tuple()},)
    complete = []
    layer_trace = []
    any_pruned = False
    stopped_by_limit = False

    for depth in range(max_seeds + 1):
        layer_record = {
            "depth": depth,
            "frontier_size": len(frontier),
            "expanded_states": [],
            "complete_states": [],
            "kept_partial_states": [],
            "pruned_partial_states": [],
        }
        next_candidates = []

        for state in frontier:
            closed = tuple(state["closed"])
            plan = tuple(state["plan"])
            if len(closed) == model["n"]:
                rec = {
                    "closed": closed,
                    "seed_plan": normalize_plan(plan),
                    "signature": rv_seed_plan_signature(plan),
                    "score": state_score(closed, plan),
                }
                complete.append(rec)
                layer_record["complete_states"].append(rec)
                if len(complete) >= limit:
                    stopped_by_limit = True
                    break
                continue
            if depth >= max_seeds:
                continue

            candidates = [
                C for C in rv_seed_candidates(model, closed)
                if int(C["parameter_cost"]) > 0
            ]
            if one_parameter_only:
                candidates = [C for C in candidates if int(C["parameter_cost"]) == 1]
            candidates.sort(key=lambda C: (
                int(C["parameter_cost"]), int(C["point"]), tuple(C["flats"])
            ))

            expanded = {
                "closed": closed,
                "seed_signature": rv_seed_plan_signature(plan),
                "candidate_count": len(candidates),
                "candidate_records": [],
            }
            for C in candidates:
                seed = {
                    "point": int(C["point"]),
                    "parameter_cost": int(C["parameter_cost"]),
                    "flats": tuple(int(fid) for fid in C["flats"]),
                }
                raw_known = tuple(sorted(set(closed).union({seed["point"]})))
                new_closed, propagation = rv_combinatorial_closure(model, raw_known)
                new_plan = normalize_plan(plan + (seed,))
                rec = {
                    "closed": tuple(new_closed),
                    "seed_plan": new_plan,
                    "signature": rv_seed_plan_signature(new_plan),
                    "score": state_score(new_closed, new_plan),
                    "last_seed": seed,
                    "propagation": tuple(propagation),
                }
                expanded["candidate_records"].append(rec)
                if len(new_closed) == model["n"]:
                    complete.append(rec)
                    layer_record["complete_states"].append(rec)
                    if len(complete) >= limit:
                        stopped_by_limit = True
                        break
                else:
                    next_candidates.append(rec)
            layer_record["expanded_states"].append(expanded)
            if stopped_by_limit:
                break

        if stopped_by_limit:
            layer_trace.append(layer_record)
            break

        # Deduplicate identical (closure, plan-signature) states deterministically.
        unique = {}
        for rec in next_candidates:
            key = (tuple(rec["closed"]), tuple(rec["signature"]))
            if key not in unique or rec["score"] < unique[key]["score"]:
                unique[key] = rec
        ordered = sorted(unique.values(), key=lambda r: r["score"])
        kept = ordered[:beam_width]
        pruned = ordered[beam_width:]
        if pruned:
            any_pruned = True
        layer_record["kept_partial_states"] = tuple(kept)
        if retain_pruned:
            layer_record["pruned_partial_states"] = tuple(pruned)
        else:
            layer_record["pruned_partial_states"] = {
                "count": len(pruned),
                "digest": rv_digest(tuple(r["signature"] for r in pruned)),
            }
        layer_trace.append(layer_record)
        frontier = tuple({"closed": r["closed"], "plan": r["seed_plan"]} for r in kept)
        if not frontier:
            break

    complete = complete[:limit]
    rows = []
    seen = set()
    for rec in complete:
        sig = tuple(rec["signature"])
        if sig in seen:
            continue
        seen.add(sig)
        plan = tuple(rec["seed_plan"])
        preview = rv_plan_complexity_preview(model, frame, plan)
        rows.append({
            "search_index": len(rows),
            "status": "complete plan",
            "seed_plan": plan,
            "signature": preview["signature"],
            "n_parameters": int(preview["parameter_count"]),
            "seed_count": int(preview["seed_count"]),
            "forced_counts": tuple(preview["forced_counts"]),
            "combinatorial_score": tuple(preview["combinatorial_score"]),
            "audit": rv_validate_seed_plan(model, frame, plan, require_full_closure=True),
        })
    rows.sort(key=lambda r: (r["combinatorial_score"], r["search_index"]))
    exhaustive = (not any_pruned) and (not stopped_by_limit)
    return {
        "rv_type": "seed_plan_search_report",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "model_fingerprint": rv_model_fingerprint(model),
        "search_parameters": search_parameters,
        "base_closure": tuple(base_closed),
        "base_propagation_history": tuple(base_history),
        "plans_found": len(rows),
        "truncated_by_plan_limit": bool(stopped_by_limit),
        "beam_pruning_occurred": bool(any_pruned),
        "exhaustive_under_requested_bounds": bool(exhaustive),
        "ranked_rows": tuple(rows),
        "layer_trace": tuple(layer_trace),
        "search_digest": rv_digest(tuple(r["signature"] for r in rows)),
        "evidence": rv_make_evidence(
            "EXACT_CERTIFICATE" if exhaustive else "HEURISTIC_SEARCH",
            claim=(
                "beam search happened to be exhaustive under requested bounds"
                if exhaustive else
                "beam seed-plan search completed with explicit pruning/truncation provenance"
            ),
            method="pure combinatorial beam search; no symbolic compilation",
            payload={
                "plans_found": len(rows),
                "beam_width": beam_width,
                "beam_pruning_occurred": bool(any_pruned),
                "truncated_by_plan_limit": bool(stopped_by_limit),
            },
            exact=True,
            exhaustive=bool(exhaustive),
            caveats=() if exhaustive else (
                "Beam-pruned branches remain possible sources of better or qualitatively different plans.",
                "A negative beam result is not a proof that no construction plan exists.",
            ),
        ),
    }


def rv_rank_construction_plans_lightweight(model, frame=None, max_seeds=4,
                                           plan_limit=200,
                                           one_parameter_only=False,
                                           strategy="enumerate", beam_width=32,
                                           retain_pruned=True):
    """Rank construction plans without constructing symbolic charts.

    This is the preferred reconnaissance entry point on memory-constrained
    machines.  It preserves the exact combinatorial audit for every returned
    plan and makes any truncation or beam pruning explicit.  Symbolic degree,
    equation-count, and forbidden-divisor metrics are intentionally absent:
    obtaining those metrics requires compiling the chart and is therefore a
    separate, auditable step.
    """
    rv_validate_model(model)
    if frame is None:
        frame = rv_find_q_chart_frame(model)
    if frame is None:
        raise ValueError("no ordinary-pair frame found")
    report = rv_seed_plan_search_report(
        model, frame, max_seeds=max_seeds,
        one_parameter_only=one_parameter_only, limit=plan_limit,
        strategy=strategy, beam_width=beam_width,
        retain_pruned=retain_pruned,
    )
    report["rv_type"] = "lightweight_construction_ranking"
    report["interpretation"] = {
        "what_was_ranked": "purely combinatorial seed plans",
        "what_was_not_computed": (
            "symbolic coordinates", "closure polynomials", "open conditions",
            "polynomial degrees", "factorizations", "saturations",
        ),
        "research_warning": (
            "The ranking is a coordinate-construction heuristic, not a ranking of "
            "intrinsic realization-space geometry. Preserve alternate plans when "
            "looking for mathematical patterns."
        ),
    }
    return report


def rv_compile_ranked_plans(model, ranking, ranks=(0,), base_ring=QQ,
                            order="degrevlex", prefix="rvsel",
                            keep_systems=True, stop_on_error=False):
    """Compile only explicitly selected rows from a lightweight ranking.

    The returned report keeps the original combinatorial row, the exact rank
    selected by the caller, symbolic complexity metrics, chart fingerprint, and
    any compilation error.  It never silently substitutes another plan.
    """
    rv_validate_model(model)
    if not isinstance(ranking, dict) or "ranked_rows" not in ranking:
        raise TypeError("ranking must be a lightweight ranking/search report")
    rows = tuple(ranking["ranked_rows"])
    frame = tuple(ranking["search_parameters"]["frame"])
    requested_ranks = tuple(int(r) for r in ranks)
    outputs = []
    for rank in requested_ranks:
        if rank < 0 or rank >= len(rows):
            raise IndexError("rank {} outside ranking with {} rows".format(rank, len(rows)))
        source = rows[rank]
        plan = tuple(source["seed_plan"])
        plan_digest = rv_digest(source["signature"])[:12]
        try:
            S = rv_compile_chart(
                model, method="construction", frame=frame, seed_plan=plan,
                base_ring=base_ring, order=order,
                prefix="{}_r{}_{}".format(prefix, rank, plan_digest),
            )
            degrees = tuple(int(f.total_degree()) for f in S["closure_polynomials"])
            out = {
                "rank": rank,
                "status": "ok",
                "source_row": source,
                "seed_plan": plan,
                "chart_fingerprint": S["fingerprint"],
                "n_parameters": int(S["ring"].ngens()),
                "n_closure_equations": len(S["closure_polynomials"]),
                "closure_degrees": degrees,
                "max_closure_degree": max(degrees, default=0),
                "total_closure_degree": sum(degrees),
                "n_forbidden_divisors": len(S["forbidden_polynomials"]),
                "n_identically_forbidden": len(S["identically_forbidden"]),
            }
            if keep_systems:
                out["system"] = S
        except Exception as exc:
            out = {
                "rank": rank,
                "status": "construction failed",
                "source_row": source,
                "seed_plan": plan,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
            if stop_on_error:
                outputs.append(out)
                break
        outputs.append(out)
    return {
        "rv_type": "selected_plan_compilation_report",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "model_fingerprint": rv_model_fingerprint(model),
        "source_search_digest": ranking.get("search_digest"),
        "frame": frame,
        "requested_ranks": requested_ranks,
        "results": tuple(outputs),
        "evidence": rv_make_evidence(
            "EXACT_CERTIFICATE",
            claim="selected construction plans compiled with provenance preserved",
            method="explicit selected-plan symbolic compilation",
            payload={"attempted": len(outputs)}, exact=True,
        ),
    }

def rv_rank_construction_charts(model, frame=None, max_seeds=4, plan_limit=30,
                                one_parameter_only=False, keep_systems=True):
    """Generate and rank several seed-plan charts by symbolic complexity.

    Ranking is heuristic: first parameter count, then maximum closure degree,
    total closure degree, equation count, and forbidden-divisor count. Each
    successfully validated seed plan covers the nondegenerate realization locus
    in its fixed frame; the ranking does not analyze the degenerate boundary or
    determine the arithmetic of the resulting variety.

    IMPORTANT (v3.2): this legacy symbolic ranker compiles every candidate even
    when keep_systems=False, because its ranking uses polynomial degrees and
    equation counts.  For memory-safe reconnaissance use
    rv_rank_construction_plans_lightweight(), then compile only explicit choices
    with rv_compile_ranked_plans().
    """
    if frame is None:
        frame = rv_find_q_chart_frame(model)
    if frame is None:
        raise ValueError("no ordinary-pair frame found")
    plans = rv_find_seed_plans(
        model, frame, max_seeds=max_seeds,
        one_parameter_only=one_parameter_only, limit=plan_limit
    )
    reports = []
    for i, plan in enumerate(plans):
        if not plan:
            reports.append({"plan_index": i, "status": "skipped: zero-parameter plan"})
            continue
        try:
            # Compile through the unified v3 chart interface so systems returned
            # by this public ranking helper satisfy the same chart contract as
            # systems produced directly by rv_compile_chart().  In v3.0.1 this
            # function returned the raw legacy construction dictionary, which
            # made coverage/consistency audits fail even when the underlying
            # symbolic construction was correct.
            S = rv_compile_chart(
                model, method="construction", frame=frame, seed_plan=plan,
                base_ring=QQ, order="degrevlex",
                prefix="rvrank{}".format(i)
            )
            degrees = [int(f.total_degree()) for f in S["closure_polynomials"]]
            row = {
                "plan_index": i,
                "status": "ok",
                "seed_plan": plan,
                "n_parameters": int(S["ring"].ngens()),
                "n_closure_equations": len(S["closure_polynomials"]),
                "max_closure_degree": max(degrees, default=0),
                "total_closure_degree": sum(degrees),
                "n_forbidden_divisors": len(S["forbidden_polynomials"]),
                "n_identically_forbidden": len(S["identically_forbidden"]),
            }
            if keep_systems:
                row["system"] = S
        except Exception as exc:
            row = {"plan_index": i, "status": "construction failed", "error": str(exc), "seed_plan": plan}
        reports.append(row)
    reports.sort(key=lambda row: (
        0 if row["status"] == "ok" else 1,
        row.get("n_parameters", 10**9),
        row.get("max_closure_degree", 10**9),
        row.get("total_closure_degree", 10**9),
        row.get("n_closure_equations", 10**9),
        row.get("n_forbidden_divisors", 10**9),
    ))
    return tuple(reports)


def rv_save_realization_certificate(model, points, path, include_forbidden_determinants=True):
    """Save a JSON-verifiable exact rational realization certificate.

    Points are projectively normalized over QQ and serialized as exact strings.
    The export is refused unless every coordinate is rational and the complete
    incidence matroid is validated exactly.
    """
    import json
    rv_validate_model(model)
    if not isinstance(points, dict):
        points = {i: tuple(P) for i, P in enumerate(points)}
    normalized = {}
    for i in range(model["n"]):
        if i not in points:
            raise ValueError("missing point {}".format(i))
        rational_vector = []
        for value in points[i]:
            try:
                rational_vector.append(QQ(value))
            except Exception:
                raise ValueError("point {} contains a non-rational coordinate: {}".format(i, value))
        if len(rational_vector) != 3:
            raise ValueError("point {} does not have three homogeneous coordinates".format(i))
        normalized[i] = rv_projective_normalize(tuple(rational_vector))

    certificate = rv_validate_realization(model, normalized, require_exact_matroid=True)
    if not certificate["valid"]:
        raise ValueError("refusing to export invalid realization: {}".format(certificate))

    metrics = rv_model_metrics(model)
    payload = {
        "certificate_type": "projective_rank_3_matroid_realization_over_Q",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "sage_version": rv_sage_version(),
        "model_fingerprint": rv_model_fingerprint(model),
        "model_name": str(model["name"]),
        "n": int(model["n"]),
        "frame_convention": "dual point (a,b,c) represents primal line ax+by+cz=0",
        "points": {str(i): [str(v) for v in normalized[i]] for i in range(model["n"])},
        "dependent_triples": [list(T) for T in model["dependent_triples"]],
        "forbidden_triple_count": len(rv_forbidden_triples(model)),
        "exact_validation": "passed over QQ",
        "chern_metrics": {
            "t_k": {str(k): int(v) for k, v in metrics["tk"].items()},
            "pair_identity_holds": bool(metrics["pair_ok"]),
            "melchior_defect": int(metrics["defect"]),
            "c1bar_squared": int(metrics["c1sq"]),
            "c2bar": int(metrics["c2"]),
            "slope": str(metrics["slope"]) if metrics["slope"] is not None else None,
        },
    }
    if include_forbidden_determinants:
        payload["forbidden_determinants"] = {
            ",".join(map(str, T)): str(rv_det(normalized[T[0]], normalized[T[1]], normalized[T[2]]))
            for T in rv_forbidden_triples(model)
        }
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
    return {"path": path, "certificate": certificate, "payload": payload}


# =============================================================================
# 18. V3 UNIFIED OBJECT CONTRACTS
# =============================================================================


def rv_upgrade_model_contract(model, copy_model=False):
    """Attach v3 tags/fingerprint to a validated legacy or v3 model."""
    rv_validate_model(model)
    M = dict(model) if copy_model else model
    M["rv_type"] = "model"
    M["schema_version"] = RV_SCHEMA_VERSION
    M["fingerprint"] = rv_model_fingerprint(M)
    return M


def rv_upgrade_chart_contract(system, chart_kind=None, coverage=None,
                              open_conditions=None, provenance=None,
                              copy_system=False):
    """Normalize a legacy chart dictionary into the v3 chart-system contract."""
    if not isinstance(system, dict):
        raise TypeError("chart/system must be a dict")
    required = {
        "model", "ring", "frame", "points", "variables",
        "closure_polynomials", "forbidden_polynomials",
    }
    missing = required - set(system)
    if missing:
        raise ValueError("chart system missing fields: {}".format(sorted(missing)))
    rv_validate_model(system["model"])
    S = dict(system) if copy_system else system
    if chart_kind is None:
        chart_kind = S.get("chart_kind")
        if chart_kind is None:
            chart_kind = "construction" if "construction" in S else "ordinary_pair"
    if coverage is None:
        coverage = {
            "scope": "fixed_frame",
            "complete_on_exact_locus": bool(S.get("chart_is_complete_for_model", False)),
            "justification": S.get("chart_note", "legacy chart; inspect provenance"),
            "atlas_complete": False,
        }
    if open_conditions is None:
        open_conditions = tuple(S.get("forbidden_polynomials", ()))
    S["rv_type"] = "chart_system"
    S["schema_version"] = RV_SCHEMA_VERSION
    S["chart_kind"] = str(chart_kind)
    S["coverage"] = dict(coverage)
    S["open_conditions"] = tuple(open_conditions)
    S["provenance"] = dict(provenance or S.get("provenance", {}))
    S["model_fingerprint"] = rv_model_fingerprint(S["model"])
    S["fingerprint"] = rv_system_fingerprint(S)
    return S


def rv_validate_chart_contract(system, strict_fingerprint=True):
    if not isinstance(system, dict):
        raise TypeError("expected chart system dict")
    required = {
        "model", "ring", "frame", "points", "variables",
        "closure_polynomials", "forbidden_polynomials",
    }
    missing = required - set(system)
    if missing:
        raise ValueError("malformed chart system; missing {}".format(sorted(missing)))
    rv_validate_model(system["model"])
    if set(system["points"]) != set(range(system["model"]["n"])):
        raise ValueError("chart point dictionary does not contain exactly 0..n-1")
    R = system["ring"]
    for f in system["closure_polynomials"]:
        try:
            R(f)
        except Exception as exc:
            raise TypeError("closure polynomial is not coercible to chart ring: {}".format(exc))
    for g in system["forbidden_polynomials"]:
        try:
            R(g)
        except Exception as exc:
            raise TypeError("open-condition polynomial is not coercible to chart ring: {}".format(exc))
    if strict_fingerprint and "fingerprint" in system:
        expected = rv_system_fingerprint(system)
        if str(system["fingerprint"]) != expected:
            raise ValueError("chart-system fingerprint is stale")
    return system


def rv_make_variety_problem(system, saturation=None, evidence=None):
    """Package closure ideal + open exact-matroid locus without conflating them."""
    rv_validate_chart_contract(system, strict_fingerprint=False)
    R = system["ring"]
    I = R.ideal(list(system["closure_polynomials"]))
    problem = {
        "rv_type": "realization_variety_problem",
        "schema_version": RV_SCHEMA_VERSION,
        "system": system,
        "ring": R,
        "incidence_ideal": I,
        "open_conditions": tuple(system.get("open_conditions", system["forbidden_polynomials"])),
        "saturation": saturation,
        "model_fingerprint": rv_model_fingerprint(system["model"]),
        "system_fingerprint": rv_system_fingerprint(system),
        "evidence": evidence,
        "interpretation": {
            "closure_variety": "V(I_inc): prescribed incidences only",
            "exact_locus": "V(I_inc) minus union of zero loci of forbidden determinants",
            "saturated_closure": "closure of exact locus if saturation was computed against all required open conditions",
        },
    }
    return problem


def rv_validate_result(result, allowed_types=None):
    if not isinstance(result, dict):
        raise TypeError("engine result must be a dict")
    if allowed_types is not None:
        if result.get("rv_type") not in set(allowed_types):
            raise ValueError("unexpected result type {}".format(result.get("rv_type")))
    return result


# =============================================================================
# 19. V3 CHART ATLAS AND FRAME/PLAN RANKING
# =============================================================================


def rv_find_q_chart_frames(model, limit=20):
    """Enumerate ordinary-pair four-point frames instead of returning only one."""
    rv_validate_model(model)
    n = model["n"]
    rich_pairs = {P for F in model["flats"] for P in combinations(F, 2)}
    out = []
    for a, b in combinations(range(n), 2):
        if (a, b) in rich_pairs:
            continue
        rest = [i for i in range(n) if i not in (a, b)]
        for c, d in combinations(rest, 2):
            frame = (a, b, c, d)
            if rv_is_general_frame(model, frame):
                out.append(frame)
                if limit is not None and len(out) >= int(limit):
                    return tuple(out)
    return tuple(out)


def rv_frame_combinatorial_score(model, frame):
    """Cheap frame score before any polynomial ring is constructed."""
    rv_validate_model(model)
    frame = tuple(frame)
    closed, history = rv_combinatorial_closure(model, frame)
    candidates = rv_seed_candidates(model, closed)
    costs = sorted(int(C["parameter_cost"]) for C in candidates)
    incidence_gain = len(closed) - len(frame)
    return {
        "frame": frame,
        "initial_closure_size": len(closed),
        "forced_points": incidence_gain,
        "n_seed_candidates": len(candidates),
        "minimum_seed_cost": min(costs) if costs else 0,
        "seed_cost_profile": tuple(costs),
        "history": history,
        "score": (
            -len(closed),
            min(costs) if costs else 0,
            sum(costs[:min(4, len(costs))]),
            frame,
        ),
    }


def rv_rank_frames(model, limit_frames=100, ordinary_pair_only=True):
    rv_validate_model(model)
    if ordinary_pair_only:
        frames = rv_find_q_chart_frames(model, limit=limit_frames)
    else:
        frames = rv_find_general_frames(model, limit=limit_frames)
    rows = [rv_frame_combinatorial_score(model, F) for F in frames]
    rows.sort(key=lambda r: r["score"])
    return tuple(rows)


def rv_seed_plan_signature(plan):
    return tuple(
        (
            int(S["point"]),
            int(S["parameter_cost"]),
            tuple(int(fid) for fid in S.get("flats", ())),
        )
        for S in plan
    )


def rv_validate_seed_plan(model, frame, seed_plan, require_full_closure=True):
    rv_validate_model(model)
    if not rv_is_general_frame(model, frame):
        raise ValueError("seed-plan validator currently requires a four-point general frame")
    known, _ = rv_combinatorial_closure(model, frame)
    known = set(known)
    audit = []
    for step_index, seed in enumerate(seed_plan):
        p = int(seed["point"])
        if p in known:
            raise ValueError("seed {} is already forced before step {}".format(p, step_index))
        candidates = {C["point"]: C for C in rv_seed_candidates(model, known)}
        if p not in candidates:
            raise ValueError("seed {} is not a valid candidate".format(p))
        C = candidates[p]
        supplied_cost = int(seed.get("parameter_cost", C["parameter_cost"]))
        if supplied_cost != int(C["parameter_cost"]):
            raise ValueError("seed {} has stale parameter cost".format(p))
        supplied_flats = tuple(seed.get("flats", C["flats"]))
        if tuple(supplied_flats) != tuple(C["flats"]):
            raise ValueError("seed {} has stale determined-flat list".format(p))
        audit.append({
            "step": step_index,
            "point": p,
            "parameter_cost": int(C["parameter_cost"]),
            "flats": tuple(C["flats"]),
            "known_before": tuple(sorted(known)),
        })
        known.add(p)
        closed, history = rv_combinatorial_closure(model, known)
        known = set(closed)
        audit[-1]["forced_after"] = history
        audit[-1]["known_after"] = tuple(sorted(known))
    if require_full_closure and len(known) != model["n"]:
        raise ValueError("seed plan does not generate all points; missing {}".format(
            sorted(set(range(model["n"])) - known)
        ))
    return {
        "valid": True,
        "signature": rv_seed_plan_signature(seed_plan),
        "audit": tuple(audit),
        "final_known": tuple(sorted(known)),
        "full_closure": len(known) == model["n"],
    }


def rv_plan_complexity_preview(model, frame, plan):
    audit = rv_validate_seed_plan(model, frame, plan, require_full_closure=True)
    parameter_count = sum(int(S["parameter_cost"]) for S in plan)
    forced_counts = tuple(len(A.get("forced_after", ())) for A in audit["audit"])
    return {
        "frame": tuple(frame),
        "seed_plan": tuple(plan),
        "signature": audit["signature"],
        "parameter_count": parameter_count,
        "seed_count": len(plan),
        "forced_counts": forced_counts,
        "combinatorial_score": (
            parameter_count,
            len(plan),
            tuple(-x for x in forced_counts),
            audit["signature"],
        ),
    }


def rv_compile_chart(model, method="ordinary_pair", frame=None, seed_plan=None,
                     base_ring=QQ, order="degrevlex", prefix="rv",
                     chart_choices=None):
    """Single public chart compiler used by experiments in v3."""
    rv_validate_model(model)
    method = str(method).lower()
    if method in ("ordinary_pair", "complete", "q"):
        S = rv_q_chart_system(
            model, frame=frame, base_ring=base_ring, order=order, prefix=prefix
        )
        coverage = {
            "scope": "fixed_labeled_model",
            "complete_on_exact_locus": True,
            "atlas_complete": True,
            "justification": S.get("chart_note", "ordinary-pair affine chart"),
        }
        return rv_upgrade_chart_contract(
            S, chart_kind="ordinary_pair_complete", coverage=coverage,
            provenance={"compiler": "rv_q_chart_system"}
        )
    if method in ("construction", "seed", "propagation"):
        if frame is None:
            ranked = rv_rank_frames(model, limit_frames=50, ordinary_pair_only=True)
            if not ranked:
                raise ValueError("no four-point ordinary-pair frame available for construction chart")
            frame = ranked[0]["frame"]
        if seed_plan is None:
            plans = rv_find_seed_plans(
                model, frame, max_seeds=5, one_parameter_only=False, limit=100
            )
            if not plans:
                raise ValueError("no construction seed plan found under current planner bounds")
            previews = [rv_plan_complexity_preview(model, frame, P) for P in plans]
            previews.sort(key=lambda X: X["combinatorial_score"])
            seed_plan = previews[0]["seed_plan"]
        audit = rv_validate_seed_plan(model, frame, seed_plan, require_full_closure=True)
        S = rv_symbolic_construction_chart(
            model, frame=frame, seed_plan=seed_plan,
            chart_choices=chart_choices, base_ring=base_ring,
            max_seeds=max(5, len(seed_plan)), one_parameter_only=False,
        )
        coverage = {
            "scope": "fixed_frame_and_seed_chart",
            "complete_on_exact_locus": bool(S.get("chart_is_complete_for_model", False)),
            "atlas_complete": False,
            "justification": S.get("chart_note", "construction chart"),
            "boundary_warning": (
                "Seed affine charts can expose degenerate boundary components; use alternate seed charts "
                "or the ordinary-pair complete chart for global cross-checking."
            ),
        }
        return rv_upgrade_chart_contract(
            S, chart_kind="construction_low_parameter", coverage=coverage,
            provenance={
                "compiler": "rv_symbolic_construction_chart",
                "seed_plan_audit": audit,
            }
        )
    raise ValueError("unknown chart compilation method: {}".format(method))


def rv_build_chart_atlas(model, ordinary_frame_limit=4, construction_frame_limit=4,
                         plans_per_frame=5, build_construction_systems=True,
                         base_ring=QQ, order="degrevlex"):
    """Build a bounded atlas with independent complete and low-parameter charts.

    The ordinary-pair chart for any chosen ordinary pair is already complete for
    the fixed labeled exact-matroid locus. Multiple frames are still useful as
    computational cross-checks. Construction charts are treated as secondary
    low-variable charts and never as the sole global formulation by default.
    """
    rv_validate_model(model)
    atlas = {
        "rv_type": "chart_atlas",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "model": model,
        "model_fingerprint": rv_model_fingerprint(model),
        "complete_charts": [],
        "construction_charts": [],
        "errors": [],
    }
    frames = rv_find_q_chart_frames(model, limit=ordinary_frame_limit)
    if not frames:
        three = rv_find_q_chart_three_frame(model)
        if three is not None:
            frames = (three,)
    for frame in frames:
        try:
            C = rv_compile_chart(
                model, method="ordinary_pair", frame=frame,
                base_ring=base_ring, order=order,
                prefix="rv_o{}".format(len(atlas["complete_charts"]))
            )
            atlas["complete_charts"].append(C)
        except Exception as exc:
            atlas["errors"].append({"stage": "complete_chart", "frame": frame, "error": str(exc)})
    if build_construction_systems:
        cframes = [F for F in frames if len(F) == 4][:int(construction_frame_limit)]
        for frame in cframes:
            try:
                plans = rv_find_seed_plans(
                    model, frame, max_seeds=5, one_parameter_only=False,
                    limit=max(int(plans_per_frame) * 5, int(plans_per_frame))
                )
                previews = [rv_plan_complexity_preview(model, frame, P) for P in plans]
                previews.sort(key=lambda X: X["combinatorial_score"])
                for preview in previews[:int(plans_per_frame)]:
                    try:
                        C = rv_compile_chart(
                            model, method="construction", frame=frame,
                            seed_plan=preview["seed_plan"], order=order,
                        )
                        atlas["construction_charts"].append(C)
                    except Exception as exc:
                        atlas["errors"].append({
                            "stage": "construction_chart", "frame": frame,
                            "plan": preview["signature"], "error": str(exc)
                        })
            except Exception as exc:
                atlas["errors"].append({"stage": "construction_planning", "frame": frame, "error": str(exc)})
    atlas["atlas_complete_for_exact_locus"] = bool(atlas["complete_charts"])
    atlas["fingerprint"] = rv_digest({
        "model": atlas["model_fingerprint"],
        "complete": [C["fingerprint"] for C in atlas["complete_charts"]],
        "construction": [C["fingerprint"] for C in atlas["construction_charts"]],
    })
    return atlas


def rv_chart_complexity(system):
    rv_validate_chart_contract(system, strict_fingerprint=False)
    degrees = []
    terms = []
    for f in system["closure_polynomials"]:
        try:
            degrees.append(int(f.total_degree()))
        except Exception:
            degrees.append(None)
        try:
            terms.append(len(f.monomials()))
        except Exception:
            terms.append(None)
    return {
        "fingerprint": rv_system_fingerprint(system),
        "chart_kind": system.get("chart_kind"),
        "n_variables": int(system["ring"].ngens()),
        "n_equations": len(system["closure_polynomials"]),
        "n_open_conditions": len(system.get("open_conditions", ())),
        "max_degree": max((d for d in degrees if d is not None), default=None),
        "total_degree": sum(d for d in degrees if d is not None),
        "max_terms": max((t for t in terms if t is not None), default=None),
        "total_terms": sum(t for t in terms if t is not None),
    }


def rv_rank_chart_atlas(atlas):
    rows = []
    for family in ("complete_charts", "construction_charts"):
        for C in atlas.get(family, ()):
            row = rv_chart_complexity(C)
            row["family"] = family
            row["system"] = C
            rows.append(row)
    rows.sort(key=lambda r: (
        r["n_variables"],
        10**9 if r["max_degree"] is None else r["max_degree"],
        r["total_degree"], r["n_equations"], r["n_open_conditions"]
    ))
    return tuple(rows)


# =============================================================================
# 20. V3 EXACT ALGEBRA / VARIETY ORCHESTRATION
# =============================================================================


def rv_ideal_dimension_safe(I):
    try:
        return {"status": "ok", "dimension": int(I.dimension()), "error": None}
    except Exception as exc:
        return {"status": "error", "dimension": None, "error": str(exc)}


def rv_ideal_groebner_safe(I, max_basis_size=None):
    try:
        G = list(I.groebner_basis())
        truncated = False
        if max_basis_size is not None and len(G) > int(max_basis_size):
            G = G[:int(max_basis_size)]
            truncated = True
        return {"status": "ok", "basis": tuple(G), "truncated": truncated, "error": None}
    except Exception as exc:
        return {"status": "error", "basis": (), "truncated": False, "error": str(exc)}


def rv_select_open_conditions(system, policy="all", max_count=None, diagnostic=None):
    """Select nonvanishing constraints without pretending a shortlist is complete."""
    policy = str(policy).lower()
    all_open = tuple(system.get("open_conditions", system.get("forbidden_polynomials", ())))
    if policy == "all":
        chosen = all_open
        complete = True
    elif policy == "first":
        if max_count is None:
            raise ValueError("max_count required for policy='first'")
        chosen = all_open[:int(max_count)]
        complete = len(chosen) == len(all_open)
    elif policy == "diagnostic_factors":
        if diagnostic is None:
            diagnostic = rv_closure_factor_diagnostic(system["model"], system["points"])
        chosen = tuple(diagnostic.get("degeneracy_factors", ()))
        complete = False
    else:
        raise ValueError("unknown open-condition selection policy")
    return {
        "policy": policy,
        "chosen": tuple(chosen),
        "all_count": len(all_open),
        "chosen_count": len(chosen),
        "complete": bool(complete),
    }


def rv_compute_saturated_problem(system, policy="all", method="inverse_variables",
                                 max_count=None, max_auxiliary_variables=80,
                                 diagnostic=None):
    rv_validate_chart_contract(system, strict_fingerprint=False)
    selection = rv_select_open_conditions(
        system, policy=policy, max_count=max_count, diagnostic=diagnostic
    )
    sat = rv_saturate_by_polynomials(
        list(system["closure_polynomials"]), list(selection["chosen"]),
        method=method, max_auxiliary_variables=max_auxiliary_variables,
    )
    exact = bool(selection["complete"])
    evidence = rv_make_evidence(
        "EXACT_CERTIFICATE" if exact else "SYMBOLIC_EVIDENCE",
        claim=(
            "computed saturation by every recorded exact-matroid open condition"
            if exact else
            "computed a partial/diagnostic saturation"
        ),
        method="Rabinowitsch saturation: {}".format(method),
        payload={"selection": selection, "elimination_count": len(sat.get("elimination", ()))},
        exact=True, exhaustive=exact,
        caveats=() if exact else ("Not every forbidden determinant was saturated.",),
    )
    return rv_make_variety_problem(system, saturation={
        "selection": selection,
        "method": method,
        "result": sat,
        "exact_for_recorded_open_locus": exact,
    }, evidence=evidence)


def rv_variety_diagnostics(problem, compute_dimension=False, compute_groebner=False,
                           factor_equations=False):
    if problem.get("rv_type") != "realization_variety_problem":
        raise TypeError("expected realization_variety_problem")
    I = problem["incidence_ideal"]
    report = {
        "rv_type": "variety_diagnostics",
        "schema_version": RV_SCHEMA_VERSION,
        "system_fingerprint": problem["system_fingerprint"],
        "n_variables": int(problem["ring"].ngens()),
        "n_incidence_generators": len(problem["system"]["closure_polynomials"]),
        "n_open_conditions": len(problem["open_conditions"]),
        "dimension": None,
        "groebner": None,
        "factorizations": None,
    }
    if compute_dimension:
        report["dimension"] = rv_ideal_dimension_safe(I)
    if compute_groebner:
        report["groebner"] = rv_ideal_groebner_safe(I)
    if factor_equations:
        report["factorizations"] = tuple(
            tuple((rv_canonical_poly(g), int(e)) for g, e in rv_factor_list(f))
            for f in problem["system"]["closure_polynomials"] if f != 0
        )
    report["evidence"] = rv_make_evidence(
        "SYMBOLIC_EVIDENCE", claim="exact symbolic diagnostics computed",
        method="Sage polynomial/ideal arithmetic", exact=True,
        payload={"dimension_requested": compute_dimension, "groebner_requested": compute_groebner}
    )
    return report


def rv_tangent_space_report(polys, values, codomain=None):
    J = rv_jacobian_at(polys, values, codomain=codomain)
    rank = int(J.rank())
    nvars = int(J.ncols())
    return {
        "rv_type": "tangent_space_report",
        "schema_version": RV_SCHEMA_VERSION,
        "jacobian": J,
        "rank": rank,
        "ambient_parameter_dimension": nvars,
        "tangent_dimension": nvars - rank,
        "warning": (
            "Tangent dimension equals local variety dimension only at a smooth point; "
            "do not silently identify the two."
        ),
        "evidence": rv_make_evidence(
            "EXACT_CERTIFICATE", claim="exact Zariski tangent-space dimension",
            method="exact Jacobian rank", exact=True,
        ),
    }


# =============================================================================
# 21. V3 CERTIFICATES, EVIDENCE, AND CROSS-CHECKS
# =============================================================================


def rv_realization_evidence(model, points, field_label=None):
    certificate = rv_validate_realization(model, points, require_exact_matroid=True)
    if certificate["valid"]:
        return rv_make_evidence(
            "EXACT_CERTIFICATE",
            claim="nondegenerate realization satisfies the complete incidence matroid",
            method="exact determinant validation",
            payload={"field": field_label, "validation": certificate},
            exact=True, exhaustive=True,
        )
    return rv_make_evidence(
        "INCONCLUSIVE",
        claim="candidate failed exact realization validation",
        method="exact determinant validation",
        payload=certificate, exact=True,
    )


def rv_classify_search_result(result, search_kind="generic"):
    """Attach conservative evidence semantics to heterogeneous search outputs."""
    status = str(result.get("status", "unknown")).lower()
    exhaustive = bool(result.get("exhaustive", False))
    exact = bool(result.get("exact", False))
    if result.get("certificate", {}).get("valid") is True or result.get("valid") is True and exact:
        level = "EXACT_CERTIFICATE"
    elif exhaustive and ("no" in status or "none" in status or "impossible" in status):
        level = "EXHAUSTIVE_FINITE_SEARCH"
    elif "numerical" in status or search_kind == "numerical":
        level = "NUMERICAL_EVIDENCE"
    elif "found" in status and exact:
        level = "EXACT_CERTIFICATE"
    elif "found" in status:
        level = "HEURISTIC_SEARCH"
    else:
        level = "INCONCLUSIVE"
    return rv_make_evidence(
        level,
        claim=result.get("status"),
        method=search_kind,
        payload=result,
        exact=exact,
        exhaustive=exhaustive,
        caveats=result.get("warning", ()) if isinstance(result.get("warning", ()), (tuple, list)) else (result.get("warning"),) if result.get("warning") else (),
    )


def rv_cross_chart_candidate_check(charts, assignments):
    """Validate candidate point sets from multiple charts against the same matroid.

    This does not prove chart ideals are birational/isomorphic. It gives an
    independent exact-matroid consistency check whenever assignments are supplied.
    `assignments` maps chart fingerprint -> variable assignment dictionary.
    """
    rows = []
    for C in charts:
        rv_validate_chart_contract(C, strict_fingerprint=False)
        fp = rv_system_fingerprint(C)
        if fp not in assignments:
            rows.append({"chart": fp, "status": "no assignment supplied"})
            continue
        sol = assignments[fp]
        try:
            points = rv_chart_solution_points(C, sol)
            cert = rv_validate_realization(C["model"], points, require_exact_matroid=True)
            rows.append({"chart": fp, "status": "checked", "certificate": cert})
        except Exception as exc:
            rows.append({"chart": fp, "status": "error", "error": str(exc)})
    return {
        "rv_type": "cross_chart_candidate_check",
        "schema_version": RV_SCHEMA_VERSION,
        "results": tuple(rows),
        "evidence": rv_make_evidence(
            "EXACT_CERTIFICATE" if rows and all(r.get("certificate", {}).get("valid") for r in rows if r["status"] == "checked") else "INCONCLUSIVE",
            claim="candidate realizations checked across supplied charts",
            method="exact matroid validation",
            exact=True,
        ),
    }


# =============================================================================
# 21B. V3.1 PRINCIPAL-CURVE AND CROSS-CHART CERTIFICATION
# =============================================================================


def rv_expand_poly(f):
    """Version-safe polynomial canonicalization/"expansion".

    Sage multivariate polynomial elements are already expanded internally and
    (notably in Sage 9.5) need not expose a SymPy-style .expand() method.
    """
    try:
        return f.parent()(f)
    except Exception:
        return f


def rv_fraction_mod_principal_report(z, ring, polynomial):
    """Analyze a rational function in Frac(ring)/(polynomial).

    The denominator must remain nonzero modulo the principal ideal before the
    rational function is interpreted in the curve function field.
    """
    R = ring
    F = R(polynomial)
    K = FractionField(R)
    z = K(z)
    num = R(z.numerator())
    den = R(z.denominator())
    I = R.ideal([F])
    num_zero = rv_ideal_membership(num, I)
    den_zero = rv_ideal_membership(den, I)
    return {
        "rational_function": z,
        "numerator": num,
        "denominator": den,
        "numerator_zero_mod_curve": bool(num_zero),
        "denominator_zero_mod_curve": bool(den_zero),
        "defined_in_function_field": not bool(den_zero),
        "zero_mod_curve": bool(num_zero) and not bool(den_zero),
    }


def rv_zero_mod_principal_curve(z, ring, polynomial):
    report = rv_fraction_mod_principal_report(z, ring, polynomial)
    return bool(report["zero_mod_curve"])


def rv_principal_exact_locus_certificate(system, polynomial):
    """Certify saturation of an irreducible principal curve by all open conditions.

    If R is a polynomial ring over a field, F is irreducible, and no recorded
    open-condition polynomial belongs to (F), then (F) is prime and

        (F) : (product g_i)^infinity = (F).

    This proves that removing the exact-matroid boundary does not change the
    Zariski closure of this principal component.
    """
    rv_validate_chart_contract(system, strict_fingerprint=False)
    R = system["ring"]
    F = rv_canonical_poly(R(polynomial))
    irreducible = bool(rv_is_irreducible(F))
    try:
        base_is_field = bool(R.base_ring().is_field())
    except Exception:
        base_is_field = False
    opens = tuple(R(g) for g in system.get("open_conditions", ()))
    membership_reports = tuple(
        rv_principal_membership_report(g, F)
        for g in opens
    )
    forced = tuple(
        (i, g) for i, (g, rep) in enumerate(zip(opens, membership_reports))
        if rep["belongs"]
    )
    certified = bool(base_is_field and irreducible and not forced)
    return {
        "rv_type": "principal_exact_locus_certificate",
        "schema_version": RV_SCHEMA_VERSION,
        "system_fingerprint": rv_system_fingerprint(system),
        "polynomial": F,
        "base_ring_is_field": base_is_field,
        "irreducible": irreducible,
        "open_count": len(opens),
        "forced_zero_open_conditions": forced,
        "open_membership_methods": tuple(rep["method"] for rep in membership_reports),
        "full_saturation_identity_certified": certified,
        "evidence": rv_make_evidence(
            "PROOF" if certified else "INCONCLUSIVE",
            claim=(
                "principal exact-locus saturation identity certified"
                if certified else
                "principal exact-locus saturation identity not certified"
            ),
            method="irreducible principal ideal + exact principal divisibility checks",
            exact=True,
            exhaustive=True,
            payload={"open_count": len(opens), "forced_zero_count": len(forced)},
            caveats=() if certified else (
                "Certification requires a polynomial ring over a field, irreducible F, and no open condition in (F).",
            ),
        ),
    }




def rv_polynomial_term_count(f):
    """Version-safe term count for Sage polynomial elements."""
    try:
        return int(f.number_of_terms())
    except Exception:
        try:
            return len(f.monomials())
        except Exception:
            return None




def rv_principal_membership_report(polynomial, generator):
    """Exact membership test in a principal polynomial ideal.

    Polynomial quotient/remainder is tried first because it avoids repeatedly
    constructing Gröbner bases for hundreds of open conditions.  The generic
    ideal-membership wrapper is retained as a conservative fallback, and the
    method used is returned for auditability.
    """
    R = generator.parent()
    g = R(polynomial)
    F = R(generator)
    if F == 0:
        raise ValueError("principal generator must be nonzero")
    try:
        q, r = g.quo_rem(F)
        return {
            "belongs": bool(r == 0),
            "method": "exact quotient/remainder",
            "quotient": q,
            "remainder": r,
        }
    except Exception as exc:
        belongs = bool(rv_ideal_membership(g, R.ideal([F])))
        return {
            "belongs": belongs,
            "method": "ideal-membership fallback",
            "quotient": None,
            "remainder": None,
            "fallback_reason": str(exc),
        }

def rv_streaming_closure_gcd(system, factor=True, record_polynomials=True):
    """Compute the common closure factor one equation at a time.

    This is an exact diagnostic intended to precede Gröbner saturation on
    high-degree low-parameter charts.  It preserves a step-by-step audit of the
    GCD evolution and separately certifies whether the entire closure ideal is
    actually principal.  A nonconstant GCD alone is *not* treated as the closure
    ideal unless the divisibility/unit-generator checks prove equality.
    """
    rv_validate_chart_contract(system, strict_fingerprint=False)
    R = system["ring"]
    source = tuple(system.get("closure_polynomials", ()))
    nonzero = tuple((i, R(f)) for i, f in enumerate(source) if R(f) != 0)
    if not nonzero:
        raise ValueError("chart has no nonzero closure polynomials")

    steps = []
    first_i, first_f = nonzero[0]
    G = rv_canonical_poly(first_f)
    steps.append({
        "step": 0,
        "equation_index": int(first_i),
        "equation": first_f if record_polynomials else None,
        "equation_digest": rv_digest(str(first_f)),
        "equation_degree": int(first_f.total_degree()),
        "equation_terms": rv_polynomial_term_count(first_f),
        "gcd": G if record_polynomials else None,
        "gcd_digest": rv_digest(str(G)),
        "gcd_degree": int(G.total_degree()),
        "gcd_terms": rv_polynomial_term_count(G),
    })

    for step_index, (i, f) in enumerate(nonzero[1:], start=1):
        G = rv_canonical_poly(G.gcd(f))
        steps.append({
            "step": int(step_index),
            "equation_index": int(i),
            "equation": f if record_polynomials else None,
            "equation_digest": rv_digest(str(f)),
            "equation_degree": int(f.total_degree()),
            "equation_terms": rv_polynomial_term_count(f),
            "gcd": G if record_polynomials else None,
            "gcd_digest": rv_digest(str(G)),
            "gcd_degree": int(G.total_degree()),
            "gcd_terms": rv_polynomial_term_count(G),
        })
        if G.is_constant():
            break

    divisibility = []
    all_divisible = True
    has_unit_generator = False
    for i, f in nonzero:
        q, r = f.quo_rem(G)
        divides = bool(r == 0)
        unit_q = bool(divides and q != 0 and q.is_constant())
        all_divisible = all_divisible and divides
        has_unit_generator = has_unit_generator or unit_q
        divisibility.append({
            "equation_index": int(i),
            "divisible_by_gcd": divides,
            "quotient": q if record_polynomials else None,
            "quotient_digest": rv_digest(str(q)),
            "quotient_degree": int(q.total_degree()) if q != 0 else None,
            "unit_quotient": unit_q,
            "remainder": r if record_polynomials else None,
            "remainder_digest": rv_digest(str(r)),
        })

    principal = bool(all_divisible and has_unit_generator)
    FAC = None
    factors = ()
    if factor and not G.is_constant():
        FAC = G.factor()
        factor_rows = []
        for f, e in FAC:
            f = rv_canonical_poly(R(f))
            factor_rows.append({
                "polynomial": f,
                "digest": rv_digest(str(f)),
                "multiplicity": int(e),
                "degree": int(f.total_degree()),
                "terms": rv_polynomial_term_count(f),
                "irreducible": bool(rv_is_irreducible(f)),
            })
        factors = tuple(factor_rows)

    return {
        "rv_type": "streaming_closure_gcd_report",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "system_fingerprint": rv_system_fingerprint(system),
        "n_source_closure_polynomials": len(source),
        "n_nonzero_closure_polynomials": len(nonzero),
        "steps": tuple(steps),
        "gcd": G,
        "gcd_digest": rv_digest(str(G)),
        "gcd_degree": int(G.total_degree()),
        "gcd_terms": rv_polynomial_term_count(G),
        "factorization": FAC,
        "factors": factors,
        "divisibility_audit": tuple(divisibility),
        "all_closure_equations_divisible_by_gcd": bool(all_divisible),
        "has_unit_multiple_of_gcd": bool(has_unit_generator),
        "closure_ideal_principal_certified": principal,
        "interpretation": {
            "gcd_only": "A common factor is a diagnostic until ideal equality is certified.",
            "principal_certificate": (
                "All closure equations lie in (G) and one is a nonzero scalar multiple of G."
                if principal else
                "The streaming GCD did not by itself certify I_closure=(G)."
            ),
        },
        "evidence": rv_make_evidence(
            "PROOF" if principal else "SYMBOLIC_EVIDENCE",
            claim=(
                "closure ideal is exactly principal with generator equal to the streaming GCD"
                if principal else
                "streaming closure GCD computed exactly; principal ideal equality not certified"
            ),
            method="iterated exact polynomial GCD + quotient/remainder audit",
            payload={
                "gcd_degree": int(G.total_degree()),
                "factor_count": len(factors),
                "all_divisible": bool(all_divisible),
                "has_unit_generator": bool(has_unit_generator),
            },
            exact=True,
            exhaustive=principal,
        ),
    }


def rv_open_component_screen(system, components, multiplicities=None,
                             record_all_open_tests=False):
    """Screen irreducible principal components against exact-matroid opens.

    A component F=0 is *excluded* only when at least one required open
    polynomial belongs to (F), i.e. vanishes identically on the component.
    If F is irreducible over a field and no open vanishes identically, then the
    exact-matroid locus is a dense open subset of that component.  This function
    deliberately uses the neutral labels `excluded` and `survives_generically`;
    it does not call a surviving component mathematically "essential".
    """
    rv_validate_chart_contract(system, strict_fingerprint=False)
    R = system["ring"]
    comps = tuple(rv_canonical_poly(R(f)) for f in components)
    if multiplicities is None:
        multiplicities = (1,) * len(comps)
    multiplicities = tuple(int(e) for e in multiplicities)
    if len(multiplicities) != len(comps):
        raise ValueError("multiplicities must match components")
    opens = tuple(R(g) for g in system.get("open_conditions", system.get("forbidden_polynomials", ())))
    try:
        base_is_field = bool(R.base_ring().is_field())
    except Exception:
        base_is_field = False

    rows = []
    for comp_index, (F, exponent) in enumerate(zip(comps, multiplicities)):
        irreducible = bool(rv_is_irreducible(F))
        killers = []
        tests = []
        for open_index, g in enumerate(opens):
            membership = rv_principal_membership_report(g, F)
            belongs = bool(membership["belongs"])
            if belongs:
                killers.append((int(open_index), g))
            if record_all_open_tests:
                tests.append({
                    "open_index": int(open_index),
                    "open_polynomial": g,
                    "open_digest": rv_digest(str(g)),
                    "zero_identically_on_component": belongs,
                    "membership_method": membership["method"],
                })
        survives = len(killers) == 0
        dense_open_certified = bool(base_is_field and irreducible and survives)
        rows.append({
            "component_index": int(comp_index),
            "polynomial": F,
            "digest": rv_digest(str(F)),
            "multiplicity": int(exponent),
            "degree": int(F.total_degree()),
            "irreducible": irreducible,
            "killer_open_conditions": tuple(killers),
            "killer_count": len(killers),
            "status": "survives_generically" if survives else "excluded",
            "dense_exact_open_certified": dense_open_certified,
            "open_tests": tuple(tests) if record_all_open_tests else None,
            "evidence": rv_make_evidence(
                "PROOF" if (killers or dense_open_certified) else "INCONCLUSIVE",
                claim=(
                    "component is entirely excluded by exact-matroid open conditions"
                    if killers else
                    "exact-matroid locus is dense open in this irreducible component"
                    if dense_open_certified else
                    "component open-condition status not fully certified"
                ),
                method="exact principal divisibility tests against every recorded open condition",
                payload={"killer_count": len(killers), "open_count": len(opens)},
                exact=True,
                exhaustive=True,
            ),
        })
    return {
        "rv_type": "open_component_screen",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "system_fingerprint": rv_system_fingerprint(system),
        "open_count": len(opens),
        "components": tuple(rows),
        "excluded_component_indices": tuple(r["component_index"] for r in rows if r["status"] == "excluded"),
        "surviving_component_indices": tuple(r["component_index"] for r in rows if r["status"] == "survives_generically"),
    }


def rv_gcd_exact_locus_decomposition(system, gcd_report=None,
                                     record_all_open_tests=False):
    """Exact GCD-first component decomposition for principal closure ideals.

    Workflow:
      1. stream the closure GCD;
      2. prove I_closure=(G), rather than assuming it;
      3. factor G exactly;
      4. test every irreducible component against every recorded open condition;
      5. derive the saturated principal generator by removing exactly those
         factors that divide the product of open conditions.

    All source equations remain in the chart; all GCD and component provenance
    remains in the returned report.  No component is silently discarded.
    """
    rv_validate_chart_contract(system, strict_fingerprint=False)
    R = system["ring"]
    if gcd_report is None:
        gcd_report = rv_streaming_closure_gcd(system, factor=True, record_polynomials=True)
    if not gcd_report.get("closure_ideal_principal_certified", False):
        return {
            "rv_type": "gcd_exact_locus_decomposition",
            "schema_version": RV_SCHEMA_VERSION,
            "engine_version": RV_ENGINE_VERSION,
            "system_fingerprint": rv_system_fingerprint(system),
            "gcd_report": gcd_report,
            "certified": False,
            "status": "principal closure ideal not certified",
            "evidence": rv_make_evidence(
                "INCONCLUSIVE",
                claim="GCD-first exact-locus decomposition not certified",
                method="principal closure prerequisite failed",
                exact=True,
                caveats=("Do not discard any GCD factor or replace saturation from this report.",),
            ),
        }
    factors = tuple(gcd_report.get("factors", ()))
    if not factors and not gcd_report["gcd"].is_constant():
        # Factorization may have been disabled in the supplied report.
        FAC = gcd_report["gcd"].factor()
        factors = tuple({
            "polynomial": rv_canonical_poly(R(f)),
            "digest": rv_digest(str(rv_canonical_poly(R(f)))),
            "multiplicity": int(e),
            "degree": int(R(f).total_degree()),
            "terms": rv_polynomial_term_count(R(f)),
            "irreducible": bool(rv_is_irreducible(R(f))),
        } for f, e in FAC)
    comps = tuple(row["polynomial"] for row in factors)
    mults = tuple(row["multiplicity"] for row in factors)
    screen = rv_open_component_screen(
        system, comps, multiplicities=mults,
        record_all_open_tests=record_all_open_tests,
    )
    surviving_rows = tuple(
        screen["components"][i] for i in screen["surviving_component_indices"]
    )
    excluded_rows = tuple(
        screen["components"][i] for i in screen["excluded_component_indices"]
    )

    surviving_generator = R(1)
    for row in surviving_rows:
        surviving_generator *= row["polynomial"] ** int(row["multiplicity"])
    surviving_generator = rv_canonical_poly(R(surviving_generator))

    all_irreducible = all(bool(r["irreducible"]) for r in screen["components"])
    try:
        base_is_field = bool(R.base_ring().is_field())
    except Exception:
        base_is_field = False
    exact_saturation_certified = bool(base_is_field and all_irreducible)
    return {
        "rv_type": "gcd_exact_locus_decomposition",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "system_fingerprint": rv_system_fingerprint(system),
        "gcd_report": gcd_report,
        "component_screen": screen,
        "excluded_components": excluded_rows,
        "surviving_components": surviving_rows,
        "saturated_generator": surviving_generator,
        "all_components_irreducible": bool(all_irreducible),
        "base_ring_is_field": bool(base_is_field),
        "principal_saturation_certified": exact_saturation_certified,
        "certified": exact_saturation_certified,
        "interpretation": {
            "excluded": "At least one required open condition vanishes identically on the component.",
            "survives_generically": "No required open vanishes identically; the exact locus is dense open on an irreducible component.",
            "no_silent_discard": "Every factor of the certified closure generator is represented in component_screen.",
        },
        "evidence": rv_make_evidence(
            "PROOF" if exact_saturation_certified else "INCONCLUSIVE",
            claim=(
                "principal exact-locus saturation decomposed factor-by-factor"
                if exact_saturation_certified else
                "component decomposition computed but exact principal saturation not certified"
            ),
            method="principal UFD factorization + exhaustive open-condition divisibility tests",
            payload={
                "factor_count": len(factors),
                "excluded_count": len(excluded_rows),
                "surviving_count": len(surviving_rows),
            },
            exact=True,
            exhaustive=True,
        ),
    }

def rv_standardize_chart_to_frame(system, target_frame):
    """Projectively standardize a symbolic realization to target_frame.

    Sends target_frame=(a,b,c,d) projectively to e1,e2,e3,(1,1,1).
    Coordinates are returned in the fraction field of the source chart ring.
    """
    R = system["ring"]
    K = FractionField(R)
    pts = {
        i: vector(K, [K(c) for c in system["points"][i]])
        for i in range(system["model"]["n"])
    }
    a, b, c, d = tuple(int(x) for x in target_frame)
    first = (a, b, c)
    B = matrix(K, 3, 3, lambda i, j: pts[first[j]][i])
    detB = K(B.det())
    if detB == 0:
        raise ValueError("target frame is generically singular in source chart")
    Binv = B.inverse()
    q = Binv * pts[d]
    if any(q[i] == 0 for i in range(3)):
        raise ValueError("fourth target-frame point lies on a coordinate line")
    D = diagonal_matrix(K, [1 / q[0], 1 / q[1], 1 / q[2]])
    T = D * Binv
    return {
        "ring": R,
        "field": K,
        "matrix": T,
        "matrix_denominator_reports": (),
        "points": {i: tuple(T * pts[i]) for i in range(system["model"]["n"])},
        "target_frame": (a, b, c, d),
    }


def rv_projective_p1_parameter(X, P, Q, chart=0):
    """Recover a P1 seed parameter from X ~ P+tQ or X ~ tP+Q."""
    K = parent(X[0])
    for i, j in ((0, 1), (0, 2), (1, 2)):
        den = P[i] * Q[j] - P[j] * Q[i]
        if den == 0:
            continue
        alpha = (X[i] * Q[j] - X[j] * Q[i]) / den
        beta = (P[i] * X[j] - P[j] * X[i]) / den
        if int(chart) == 0 and alpha != 0:
            return K(beta / alpha)
        if int(chart) == 1 and beta != 0:
            return K(alpha / beta)
        if int(chart) not in (0, 1):
            raise ValueError("P1 seed chart must be 0 or 1")
    raise ValueError("unable to recover projective seed parameter")


def rv_extract_construction_chart_map(source, target, source_curve=None):
    """Recover target construction parameters as functions on a source chart.

    Current generic implementation supports cost-one P1 seeds.  This is enough
    for propagation charts and deliberately errors rather than
    guessing for higher-cost seeds.
    """
    rv_validate_chart_contract(source, strict_fingerprint=False)
    rv_validate_chart_contract(target, strict_fingerprint=False)
    if source["model"]["fingerprint"] != target["model"]["fingerprint"]:
        raise ValueError("source and target charts belong to different models")
    Rs, Rt = source["ring"], target["ring"]
    Ks = FractionField(Rs)
    standardized = rv_standardize_chart_to_frame(source, target["frame"])
    Xsource = standardized["points"]
    parameter_map = {}
    steps = []
    seed_metadata = tuple(target.get("construction", {}).get("seed_metadata", ()))
    if not seed_metadata:
        raise ValueError("target chart has no construction seed metadata")
    for step, meta in enumerate(seed_metadata):
        p = int(meta["point"])
        cost = int(meta["parameter_cost"])
        if cost != 1:
            raise NotImplementedError("cross-chart extraction currently supports cost-one seeds only")
        anchor_a, anchor_b = tuple(int(x) for x in meta["anchors"])
        target_var = target["variables_by_point"][p][0]
        allowed = set(parameter_map)
        for anchor in (anchor_a, anchor_b):
            for coord in target["points"][anchor]:
                unknown = set(rv_poly_variables(Rt(coord))) - allowed
                if unknown:
                    raise ValueError("anchor {} depends on future parameters {}".format(anchor, unknown))
        values = [parameter_map.get(g, Ks(0)) for g in Rt.gens()]
        phi_partial = Rt.hom(values, Ks)
        P = tuple(Ks(phi_partial(c)) for c in target["points"][anchor_a])
        Q = tuple(Ks(phi_partial(c)) for c in target["points"][anchor_b])
        t = rv_projective_p1_parameter(Xsource[p], P, Q, meta["chart"])
        parameter_map[target_var] = t
        steps.append({
            "step": step, "point": p, "target_variable": target_var,
            "anchors": (anchor_a, anchor_b), "chart": int(meta["chart"]), "map": t,
        })
    if set(parameter_map) != set(Rt.gens()):
        raise ValueError("not every target parameter was recovered")
    phi = Rt.hom([parameter_map[g] for g in Rt.gens()], Ks)
    denominator_reports = ()
    if source_curve is not None:
        denominator_reports = tuple(
            rv_fraction_mod_principal_report(parameter_map[g], Rs, source_curve)
            for g in Rt.gens()
        )
    return {
        "rv_type": "construction_chart_map",
        "source_fingerprint": rv_system_fingerprint(source),
        "target_fingerprint": rv_system_fingerprint(target),
        "source": source, "target": target,
        "source_curve": None if source_curve is None else Rs(source_curve),
        "map": parameter_map, "hom": phi, "steps": tuple(steps),
        "frame_change": standardized,
        "parameter_denominator_reports": denominator_reports,
    }


def rv_apply_fraction_map(z, domain_ring, variable_map, codomain_field):
    Kd = FractionField(domain_ring)
    z = Kd(z)
    phi = domain_ring.hom([variable_map[g] for g in domain_ring.gens()], codomain_field)
    return codomain_field(phi(z.numerator()) / phi(z.denominator()))


def rv_birational_chart_certificate(chart_a, chart_b, curve_a, curve_b):
    """Derive and certify inverse rational maps between two construction curves."""
    RA, RB = chart_a["ring"], chart_b["ring"]
    KA, KB = FractionField(RA), FractionField(RB)
    FA, FB = RA(curve_a), RB(curve_b)
    AB = rv_extract_construction_chart_map(chart_a, chart_b, source_curve=FA)
    BA = rv_extract_construction_chart_map(chart_b, chart_a, source_curve=FB)

    fb_pull = KA(AB["hom"](FB))
    fa_pull = KB(BA["hom"](FA))
    fb_report = rv_fraction_mod_principal_report(fb_pull, RA, FA)
    fa_report = rv_fraction_mod_principal_report(fa_pull, RB, FB)

    comp_a = []
    for x in RA.gens():
        back = rv_apply_fraction_map(BA["map"][x], RB, AB["map"], KA)
        rep = rv_fraction_mod_principal_report(KA(back - KA(x)), RA, FA)
        comp_a.append({"variable": x, "residual": KA(back - KA(x)), "report": rep})
    comp_b = []
    for x in RB.gens():
        back = rv_apply_fraction_map(AB["map"][x], RA, BA["map"], KB)
        rep = rv_fraction_mod_principal_report(KB(back - KB(x)), RB, FB)
        comp_b.append({"variable": x, "residual": KB(back - KB(x)), "report": rep})

    denom_ok = all(r["defined_in_function_field"] for r in AB["parameter_denominator_reports"]) and \
               all(r["defined_in_function_field"] for r in BA["parameter_denominator_reports"])
    certified = bool(
        denom_ok and fb_report["zero_mod_curve"] and fa_report["zero_mod_curve"] and
        all(row["report"]["zero_mod_curve"] for row in comp_a) and
        all(row["report"]["zero_mod_curve"] for row in comp_b)
    )
    return {
        "rv_type": "birational_chart_certificate",
        "schema_version": RV_SCHEMA_VERSION,
        "map_a_to_b": AB, "map_b_to_a": BA,
        "curve_b_pullback_to_a": {"value": fb_pull, "report": fb_report},
        "curve_a_pullback_to_b": {"value": fa_pull, "report": fa_report},
        "composition_a": tuple(comp_a), "composition_b": tuple(comp_b),
        "parameter_denominators_defined": denom_ok,
        "certified_birational": certified,
        "evidence": rv_make_evidence(
            "PROOF" if certified else "INCONCLUSIVE",
            claim="construction charts have inverse rational maps on dense opens" if certified else "birationality not certified",
            method="projective frame standardization + seed-coordinate recovery + exact principal-ideal reduction",
            exact=True, exhaustive=True,
            caveats=() if certified else ("At least one pullback/composition/denominator check failed.",),
        ),
    }


# =============================================================================
# 22. V3 HIGH-LEVEL RESEARCH SESSION API
# =============================================================================


def rv_prepare_experiment(model, label=None, build_atlas=True,
                          ordinary_frame_limit=3, construction_frame_limit=3,
                          plans_per_frame=3, load_satellites=False):
    """Prepare, but do not run expensive algebraic/arithmetic experiments."""
    model = rv_upgrade_model_contract(model)
    if load_satellites:
        rv_load_satellites(print_report=False)
    manifest = rv_new_manifest(model, label=label or model["name"])
    metrics = rv_model_metrics(model)
    rv_manifest_record(
        manifest, "validate_model", result={"valid": True, "metrics": metrics},
        evidence=rv_make_evidence(
            "EXACT_CERTIFICATE", claim="combinatorial model is internally consistent",
            method="maximal-flat and pair-budget validation", exact=True, exhaustive=True,
        )
    )
    atlas = None
    if build_atlas:
        atlas = rv_build_chart_atlas(
            model,
            ordinary_frame_limit=ordinary_frame_limit,
            construction_frame_limit=construction_frame_limit,
            plans_per_frame=plans_per_frame,
            build_construction_systems=True,
        )
        rv_manifest_record(
            manifest, "build_chart_atlas",
            result={
                "fingerprint": atlas["fingerprint"],
                "complete_charts": len(atlas["complete_charts"]),
                "construction_charts": len(atlas["construction_charts"]),
                "errors": atlas["errors"],
            },
            evidence=rv_make_evidence(
                "SYMBOLIC_EVIDENCE",
                claim="chart atlas compiled",
                method="ordinary-pair and construction chart compilers",
                exact=True,
                caveats=("Compilation alone does not solve the realization variety.",),
            )
        )
    return {
        "rv_type": "research_session",
        "schema_version": RV_SCHEMA_VERSION,
        "engine_version": RV_ENGINE_VERSION,
        "model": model,
        "metrics": metrics,
        "atlas": atlas,
        "manifest": manifest,
        "capabilities": rv_capabilities(print_report=False),
    }


def rv_session_best_charts(session, count=5):
    atlas = session.get("atlas")
    if atlas is None:
        return ()
    ranked = rv_rank_chart_atlas(atlas)
    return ranked[:int(count)]


def rv_session_dispatch(session, action, *args, **kwargs):
    """Run a specialized satellite action and record it in the manifest."""
    t0 = time.time()
    try:
        result = rv_dispatch(action, *args, **kwargs)
        elapsed = time.time() - t0
        evidence = result.get("evidence") if isinstance(result, dict) else None
        rv_manifest_record(
            session["manifest"], action,
            result=result, evidence=evidence,
            parameters={"elapsed_seconds": elapsed, "kwargs": kwargs},
        )
        return result
    except Exception as exc:
        elapsed = time.time() - t0
        rv_manifest_record(
            session["manifest"], action,
            result={"status": "error", "error": str(exc)},
            evidence=rv_make_evidence("INCONCLUSIVE", claim="satellite action failed", method=action),
            parameters={"elapsed_seconds": elapsed, "kwargs": kwargs},
        )
        raise


def rv_engine_status(print_report=True):
    status = {
        "engine_version": RV_ENGINE_VERSION,
        "schema_version": RV_SCHEMA_VERSION,
        "sage_version": rv_sage_version(),
        "capabilities": rv_capabilities(print_report=False),
        "satellites": rv_list_satellites(print_report=False),
        "research_policy": "optimize execution, not evidence",
    }
    if print_report:
        print("Realization Engine v{}".format(RV_ENGINE_VERSION))
        print("Sage version =", status["sage_version"])
        print("schema version =", RV_SCHEMA_VERSION)
        print("loaded satellites =", tuple(S["name"] for S in status["satellites"]))
    return status


# =============================================================================
# 23. GENERIC REGRESSION / INTEGRATION TESTS
# =============================================================================





















def rv_test_v3_gcd_component_pipeline(verbose=True):
    M = rv_make_model(4, flats=[(0, 1, 2)], name="gcd pipeline toy")
    R = PolynomialRing(QQ, names=("rv_gc_x", "rv_gc_y"))
    x, y = R.gens()
    G = (x - 1) * (x + y)
    S = {
        "model": M,
        "ring": R,
        "base_ring": QQ,
        "frame": (0, 1, 2, 3),
        "points": {
            0: (R(1), R(0), R(0)),
            1: (R(0), R(1), R(0)),
            2: (R(1), R(1), R(0)),
            3: (R(0), R(0), R(1)),
        },
        "variables": tuple(R.gens()),
        "closure_polynomials": (G, G * (x + 2), 2 * G * (y + 3)),
        "forbidden_polynomials": (x - 1, y + 2),
        "identically_forbidden": (),
        "chart_is_complete_for_model": True,
        "chart_note": "synthetic regression chart for GCD/open-component logic",
    }
    S = rv_upgrade_chart_contract(
        S, chart_kind="synthetic_regression",
        open_conditions=S["forbidden_polynomials"],
        coverage={
            "scope": "synthetic regression",
            "complete_on_exact_locus": True,
            "atlas_complete": False,
            "justification": "unit test only",
        },
    )
    GR = rv_streaming_closure_gcd(S, factor=True)
    assert GR["closure_ideal_principal_certified"]
    assert len(GR["factors"]) == 2
    DR = rv_gcd_exact_locus_decomposition(S, gcd_report=GR)
    assert DR["certified"]
    assert len(DR["excluded_components"]) == 1
    assert len(DR["surviving_components"]) == 1
    assert rv_canonical_poly(DR["saturated_generator"]) == rv_canonical_poly(x + y)
    if verbose:
        print("V3 GCD/component pipeline..... PASS")
    return True



def rv_test_v3_satellite_registry(verbose=True):
    name = "__rv_test_satellite__"
    rv_unregister_satellite(name)
    rv_register_satellite(
        name, "0", {"echo": lambda x: x}, description="registry self-test"
    )
    assert rv_dispatch("echo", 7, provider=name) == 7
    assert rv_unregister_satellite(name)
    if verbose:
        print("V3 satellite registry........ PASS")
    return True







def rv_initialize(load_satellites=True, test_level=None, satellite_directory=None):
    """Recommended notebook entry point."""
    status = rv_engine_status(print_report=True)
    if load_satellites:
        status["satellite_load"] = rv_load_satellites(
            directory=satellite_directory, strict=False, print_report=True
        )
    if test_level is not None:
        rv_run_v3_tests(level=test_level, load_satellites=False)
    return status


# End of Realization Engine v3 core.


# =============================================================================
# 24. V3 INTERPRETABILITY / AUDIT HELPERS
# =============================================================================


def rv_explain_model(model, print_report=True):
    """Human-readable explanation of how the engine interprets a model."""
    rv_validate_model(model)
    metrics = rv_model_metrics(model)
    pair_owner = model.get("pair_owner", {})
    ordinary_pairs = tuple(
        P for P in combinations(range(model["n"]), 2)
        if P not in pair_owner
    )
    report = {
        "name": model["name"],
        "fingerprint": rv_model_fingerprint(model),
        "n_points_dual": model["n"],
        "maximal_rich_flats": model["flats"],
        "rich_flat_count": len(model["flats"]),
        "dependent_triple_count": len(model["dependent_triples"]),
        "ordinary_pair_count": len(ordinary_pairs),
        "ordinary_pairs_sample": ordinary_pairs[:20],
        "metrics": metrics,
        "interpretation": (
            "Dual points represent primal lines; each maximal rich flat represents one primal "
            "intersection point of multiplicity equal to the flat size. Pairs not owned by a rich "
            "flat are inferred double points in the primal arrangement."
        ),
    }
    if print_report:
        print("Model:", report["name"])
        print("  fingerprint:", report["fingerprint"])
        print("  dual points / primal lines:", report["n_points_dual"])
        print("  maximal rich flats:", report["rich_flat_count"])
        print("  dependent triples:", report["dependent_triple_count"])
        print("  ordinary pairs:", report["ordinary_pair_count"])
        print("  t_k:", metrics["tk"])
        print("  defect:", metrics["defect"], "slope:", metrics["slope"])
    return report


def rv_explain_chart(system, print_report=True):
    rv_validate_chart_contract(system, strict_fingerprint=False)
    complexity = rv_chart_complexity(system)
    report = {
        "chart_kind": system.get("chart_kind"),
        "fingerprint": rv_system_fingerprint(system),
        "frame": tuple(system["frame"]),
        "coverage": system.get("coverage"),
        "provenance": system.get("provenance"),
        "complexity": complexity,
        "identically_forbidden": tuple(system.get("identically_forbidden", ())),
        "closure_meaning": "required collinearities not already identities in the chosen coordinates",
        "open_meaning": "forbidden collinearities/nondegeneracy determinants that must stay nonzero",
    }
    if print_report:
        print("Chart kind:", report["chart_kind"])
        print("  fingerprint:", report["fingerprint"])
        print("  frame:", report["frame"])
        print("  variables:", complexity["n_variables"])
        print("  closure equations:", complexity["n_equations"])
        print("  open conditions:", complexity["n_open_conditions"])
        print("  max closure degree:", complexity["max_degree"])
        print("  coverage:", report["coverage"])
        if report["identically_forbidden"]:
            print("  WARNING: identically forbidden triples:", report["identically_forbidden"])
    return report


def rv_chart_coverage_audit(system):
    """Check the internal justification attached to a chart coverage claim."""
    rv_validate_chart_contract(system, strict_fingerprint=False)
    model = system["model"]
    kind = system.get("chart_kind")
    frame = tuple(system["frame"])
    checks = []
    if kind == "ordinary_pair_complete":
        checks.append(("ordinary_pair", len(frame) >= 2 and rv_pair_is_ordinary(model, frame[0], frame[1])))
        if len(frame) == 4:
            checks.append(("general_four_frame", rv_is_general_frame(model, frame)))
        elif len(frame) == 3:
            checks.append(("noncollinear_three_frame", tuple(sorted(frame)) not in model["dependent_set"]))
        else:
            checks.append(("frame_size_3_or_4", False))
        free = set(range(model["n"])) - set(frame)
        z_is_one = True
        for p in free:
            try:
                z_is_one = z_is_one and system["points"][p][2] == system["ring"](1)
            except Exception:
                z_is_one = False
        checks.append(("all_nonframe_points_affine_z1", z_is_one))
    elif kind == "construction_low_parameter":
        checks.append(("ordinary_pair", rv_pair_is_ordinary(model, frame[0], frame[1])))
        checks.append(("general_four_frame", len(frame) == 4 and rv_is_general_frame(model, frame)))
        construction = system.get("construction", {})
        plan = construction.get("seed_plan", ())
        try:
            audit = rv_validate_seed_plan(model, frame, plan, require_full_closure=True)
            checks.append(("seed_plan_full_closure", bool(audit["full_closure"])))
        except Exception:
            checks.append(("seed_plan_full_closure", False))
        seed_meta = construction.get("seed_metadata", ())
        charts_supported = all(int(M.get("chart", -1)) in (0, 1, 2) for M in seed_meta)
        checks.append(("seed_chart_metadata_valid", charts_supported))
    else:
        checks.append(("known_chart_kind", False))
    passed = all(ok for _, ok in checks)
    return {
        "rv_type": "chart_coverage_audit",
        "chart_fingerprint": rv_system_fingerprint(system),
        "checks": tuple(checks),
        "passed": bool(passed),
        "evidence": rv_make_evidence(
            "EXACT_CERTIFICATE" if passed else "INCONCLUSIVE",
            claim="internal chart coverage assumptions are consistent with the recorded combinatorics",
            method="chart-contract audit", exact=True,
            caveats=(
                "This audits the engine's coverage hypotheses; it is not a substitute for a formal proof of any new chart construction theorem.",
            ),
        ),
    }


def rv_system_consistency_audit(system, recompute_equations=True):
    """Deep audit that re-derives chart equations from the recorded point formulas."""
    rv_validate_chart_contract(system, strict_fingerprint=False)
    model = system["model"]
    rows = []
    rows.append(("model_valid", True))
    rows.append(("point_index_set", set(system["points"]) == set(range(model["n"]))))
    rows.append(("no_identically_forbidden", len(system.get("identically_forbidden", ())) == 0))
    if recompute_equations:
        closure = rv_flat_closure_equations(model, system["points"])
        forbidden = rv_forbidden_determinants(model, system["points"])
        R = system["ring"]
        def canon_set(polys):
            return {
                str(rv_canonical_poly(R(f)))
                for f in polys if R(f) != 0
            }
        stored_closure = canon_set(system["closure_polynomials"])
        recomputed_closure = canon_set(rec["polynomial"] for rec in closure["equations"])
        stored_open = canon_set(system.get("forbidden_polynomials", ()))
        recomputed_open = canon_set(rec["polynomial"] for rec in forbidden["nonzero"])
        rows.append(("closure_equations_rederive", stored_closure == recomputed_closure))
        rows.append(("forbidden_divisors_rederive", stored_open == recomputed_open))
        rows.append(("recomputed_identically_forbidden", not forbidden["identically_zero"]))
    coverage = rv_chart_coverage_audit(system)
    rows.append(("coverage_audit", coverage["passed"]))
    passed = all(ok for _, ok in rows)
    return {
        "rv_type": "system_consistency_audit",
        "system_fingerprint": rv_system_fingerprint(system),
        "checks": tuple(rows),
        "coverage": coverage,
        "passed": bool(passed),
        "evidence": rv_make_evidence(
            "EXACT_CERTIFICATE" if passed else "INCONCLUSIVE",
            claim="chart system is internally self-consistent",
            method="independent re-derivation of incidence/open equations", exact=True,
            exhaustive=True,
        ),
    }



# =============================================================================
# PUBLIC-CORE TESTS: ONLY SYNTHETIC EXAMPLES
# =============================================================================


def rv_test_q_chart_and_certificates(verbose=True):
    """Check an exact five-point toy configuration; make no research claims."""
    toy = rv_make_model(5, flats=[(1, 3, 4)], name="five-point toy")
    chart = rv_q_chart_system(toy, frame=(0, 1, 2, 3), base_ring=QQ)
    assert chart["chart_is_complete_for_model"]
    assert len(chart["variables"]) == 2
    assert not chart["identically_forbidden"]
    points = rv_chart_solution_points(chart, [QQ(1), QQ(2)])
    assert rv_validate_realization(toy, points, require_exact_matroid=True)["valid"]
    if verbose:
        print("Toy exact chart / certificate.. PASS")
    return True


def rv_test_v3_schemas(verbose=True):
    toy = rv_make_model(5, flats=[(1, 3, 4)], name="schema toy")
    assert toy["rv_type"] == "model"
    assert toy["schema_version"] == RV_SCHEMA_VERSION
    assert toy["fingerprint"] == rv_model_fingerprint(toy)
    e = rv_make_evidence("SYMBOLIC_EVIDENCE", claim="toy")
    assert rv_evidence_at_least(e, "NUMERICAL_EVIDENCE")
    manifest = rv_new_manifest(toy, label="toy")
    rv_manifest_record(manifest, "noop", result={"ok": True}, evidence=e)
    assert len(manifest["steps"]) == 1
    if verbose:
        print("Generic schema/evidence....... PASS")
    return True


def rv_test_v3_research_ledger(verbose=True):
    toy = rv_make_model(5, flats=[(1, 3, 4)], name="ledger toy")
    ledger = rv_new_research_ledger(toy, label="toy")
    a = rv_ledger_record(ledger, "raw", "toy input", payload={"x": 1})
    b = rv_ledger_record(ledger, "derived", "toy expression", payload={"x": 2}, dependencies=(a["entry_id"],))
    summary = rv_ledger_summary(ledger)
    assert summary["entry_count"] == 2
    assert b["dependencies"] == (a["entry_id"],)
    if verbose:
        print("Generic evidence ledger....... PASS")
    return True


def rv_test_v3_builtin_satellites(verbose=True):
    status = rv_load_satellites(strict=True, print_report=False)
    expected = {"arithmetic", "curves", "elliptic", "finite_fields", "genus2", "numerical", "padic"}
    assert expected <= set(RV_SATELLITES)
    assert not status["errors"]
    if verbose:
        print("Satellite registration........ PASS")
    return True


def rv_run_v3_tests(level="smoke", load_satellites=False, strict_satellites=False):
    """Toy-model checks; passing does not establish mathematical correctness.

    smoke: compatibility, schema, ledger, satellite dispatch registration.
    integration: also check toy rational chart and synthetic GCD pipeline.
    full: also verify all bundled satellite modules register successfully.
    """
    level = str(level).lower()
    if level not in ("smoke", "integration", "full"):
        raise ValueError("level must be smoke, integration, or full")
    if load_satellites:
        rv_load_satellites(strict=strict_satellites, print_report=True)
    rv_test_compatibility()
    rv_test_v3_schemas()
    rv_test_v3_research_ledger()
    rv_test_v3_satellite_registry()
    if level in ("integration", "full"):
        rv_test_q_chart_and_certificates()
        rv_test_v3_gcd_component_pipeline()
    if level == "full":
        rv_test_v3_builtin_satellites()
    print("Generic tests passed at level:", level)
    return True


def rv_run_base_tests(full=False):
    """Backward-compatible test entry point using only generic fixtures."""
    return rv_run_v3_tests(level="full" if full else "smoke")


def rv_run_q_tests(verbose=True):
    """Legacy entry point, now using only a generic rational toy."""
    rv_test_compatibility(verbose=verbose)
    rv_test_q_chart_and_certificates(verbose=verbose)
    return True
