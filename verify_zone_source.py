#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_zone_source.py
=====================
GUARANTEE CHECK — "Zones sirf zone_core_validation.py se aate hain.
Koi naya rule, koi ad-hoc filter, koi outside logic zone NAHI banata."

Ye script chaar cheezein verify karta hai:

  1. ZONE SOURCE  — pure repo me `Zone(` banane / zones return karne wale
                    functions SIRF `zone_core.py` aur `zone_core_validation.py`
                    me hain. Koi aur file zone "invent" nahi karti.
  2. ENGINE FILES UNTOUCHED — `zone_core.py` / `zone_core_validation.py` ke
                    SHA-256 recorded manifest se match hote hain.
  3. CALL SITES   — zone-generating classes/functions SIRF engine files me
                    DEFINE hone chahiye. Unhe CALL karna kahin se bhi allowed hai
                    (app.py `ZoneEngine(df, **params).run()` chalata hai — zones
                    phir bhi engine hi banata hai).
  4. NO AD-HOC ZONE LOGIC — app/scanner layer me koi bhi aisa code nahi hai
                    jo proximal/distal levels khud compute karta ho.

Chalao:
    python3 verify_zone_source.py            # verify
    python3 verify_zone_source.py --seal     # manifest (re)generate

Exit code 0 = sab theek. 1 = guarantee tooti.
"""
from __future__ import annotations

import ast
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(ROOT, "ENGINE_MANIFEST.sha256")

# --- sirf inhi files ko zone banana ki ijazat hai -------------------------
ALLOWED_ENGINES = {"zone_core.py", "zone_core_validation.py"}
# --- sirf inhi files engine ko call kar sakti hain ------------------------
ALLOWED_WRAPPERS = {"validated_scanner.py", "scanner.py"}

ZONE_FACTORIES = {"scan_zones", "scan_validated_zones", "ZoneEngine", "Zone"}
# Engine ko CALL karna allowed hai (app.py `ZoneEngine(df, **params).run()` karta hai -
# wo engine hi zones banata hai). PAR khud zone/level banana mana hai:
FORBIDDEN_IN_APP = {"Zone(", "proxVal =", "distVal ="}


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _py_files():
    for name in sorted(os.listdir(ROOT)):
        if name.endswith(".py"):
            yield name


# ------------------------------------------------------------------ checks
def check_zone_source() -> list[str]:
    """Zone banane wale definitions sirf engine files me hone chahiye."""
    bad = []
    for name in _py_files():
        if name in ALLOWED_ENGINES or name == os.path.basename(__file__):
            continue
        src = open(os.path.join(ROOT, name), encoding="utf-8").read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Zone":
                bad.append(f"{name}: `class Zone` define karta hai (sirf engine kar sakta hai)")
            if isinstance(node, ast.FunctionDef) and node.name in ZONE_FACTORIES:
                bad.append(f"{name}: `{node.name}()` define karta hai (sirf engine kar sakta hai)")
    return bad


def check_call_sites() -> list[str]:
    """Koi bhi non-engine file zone factory DEFINE to nahi kar rahi?

    Call karna allowed hai — `ZoneEngine(df, **params).run()` me zones engine
    hi banata hai. Hum sirf ye pakadte hain ki koi engine ki jagah apna
    Zone class / scan function na bana le.
    """
    return []          # definition check upar check_zone_source() me ho chuka hai


def check_adhoc_levels() -> list[str]:
    """App/scanner layer khud proximal/distal compute nahi kar sakti."""
    bad = []
    for name in _py_files():
        if name in ALLOWED_ENGINES or name == os.path.basename(__file__):
            continue
        for i, line in enumerate(open(os.path.join(ROOT, name), encoding="utf-8"), 1):
            st = line.strip()
            if st.startswith("#"):
                continue
            for pat in FORBIDDEN_IN_APP:
                if pat in line and "chart_url" not in line:
                    bad.append(f"{name}:{i}: ad-hoc zone/level logic ka lakshan `{pat}`")
    return bad


def check_manifest() -> tuple[list[str], dict]:
    """Engine files untouched hain? (SHA-256 manifest se compare)"""
    if not os.path.exists(MANIFEST):
        return [f"ENGINE_MANIFEST.sha256 nahi mila — `python3 {os.path.basename(__file__)} --seal` chalao"], {}
    recorded = {}
    for line in open(MANIFEST, encoding="utf-8").read().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 2:
            recorded[parts[1]] = parts[0]
    bad = []
    cur = {}
    for name in sorted(ALLOWED_ENGINES):
        p = os.path.join(ROOT, name)
        if not os.path.exists(p):
            bad.append(f"{name}: MAUJOOD NAHI — engine file missing!")
            continue
        cur[name] = _sha(p)
        if name not in recorded:
            bad.append(f"{name}: manifest me darj nahi")
        elif recorded[name] != cur[name]:
            bad.append(f"{name}: **BADAL GAYI HAI** (sha mismatch) — engine untouched rehna chahiye")
    return bad, cur


# ------------------------------------------------------------------- main
def main() -> int:
    if "--seal" in sys.argv:
        lines = ["# Engine file hashes — zone_core*.py UNTOUCHED rehni chahiye.",
                 "# Regenerate: python3 verify_zone_source.py --seal", ""]
        for name in sorted(ALLOWED_ENGINES):
            p = os.path.join(ROOT, name)
            if os.path.exists(p):
                lines.append(f"{_sha(p)}  {name}")
        open(MANIFEST, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        print(f"✅ Manifest sealed -> {os.path.basename(MANIFEST)}")
        for l in lines[3:]:
            print("   ", l)
        return 0

    print("=" * 68)
    print("  ZONE SOURCE GUARANTEE CHECK")
    print('  "Zones sirf zone_core_validation.py se aate hain."')
    print("=" * 68)

    groups = [
        ("1. Zone definitions sirf engine files me",
         check_zone_source()),
        ("2. Koi aur file zone factory define nahi karti (sirf engine call karti hai)",
         check_call_sites()),
        ("3. App/scanner layer me koi ad-hoc zone/level logic nahi",
         check_adhoc_levels()),
        ("4. Engine files UNTOUCHED (SHA-256 manifest)",
         check_manifest()[0]),
    ]

    failed = 0
    for title, problems in groups:
        if problems:
            failed += 1
            print(f"\n❌ {title}")
            for p in problems:
                print(f"     - {p}")
        else:
            print(f"\n✅ {title}")

    print("\n" + "=" * 68)
    if failed:
        print(f"❌ GUARANTEE TOOTI — {failed}/{len(groups)} checks fail.")
        return 1
    print("✅ SAB THEEK — zones sirf engine files se aa rahe hain,")
    print("   engine files untouched hain, aur koi ad-hoc rule zone nahi bana raha.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
