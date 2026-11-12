#!/usr/bin/env python3
"""Self-checking tests of the VHDL operators with GHDL.

Every adder, multiplier and converter of rtl/ is simulated on random and
directed operands and each output word is compared with the reference model
(model/hrfp.py), which gives the expected result bit for bit.

    python tb/run_tests.py                 # all radices, about 20 seconds
    python tb/run_tests.py --quick         # ten times fewer vectors
    python tb/run_tests.py --radix 6       # only radix 2^6
    python tb/run_tests.py --seed 7        # other random operands

Test groups:

  add_random        every exponent difference, additions and subtractions,
                    random and "sparse" significands (runs of zeros and ones)
  add_cancellation  subtractions in which leading digits cancel
  add_rounding      carries out, rounding overflows, results near powers of
                    the radix
  add_special       zeros, infinities, NaNs, exponent overflow and underflow
  mul_random        products of random and sparse significands
  mul_rounding      products just below and above a power of the radix
  mul_special       zeros, infinities, NaNs, exponent overflow and underflow
  ieee_to_hr        IEEE-754 single to radix 64, every IEEE exponent
  hr_to_ieee        radix 64 to IEEE-754 single, every exponent, special values

PASS means that every output is the one given by the model.  For the adders
the model is also compared with the ideal result (the exact sum rounded with
Eq. (23) of the paper): they must coincide unless the leading digit cancels
in a subtraction of operands with different exponents, which is the
documented limitation of the adders (README.md).  The number of such results
and their largest relative error are reported.

Exit status 0 if no group fails.  Requires GHDL (tested with 4.1.0).

Copyright (C) 2022 Javier Hormigo, Universidad de Malaga
SPDX-License-Identifier: LGPL-3.0-or-later
"""
import argparse
import os
import random
import shutil
import subprocess
import sys
from collections import Counter
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
from hrfp import Format, NORMAL, ZERO, INF, NAN, floor_log2   # noqa: E402

# The sources use the Synopsys packages std_logic_arith / std_logic_unsigned.
GHDL = ["--std=08", "-frelaxed", "-fsynopsys", "-fexplicit"]

# digit bits -> folder, adder (file, entity), multiplier (file, entity)
DESIGNS = {
    4:  ("radix16",   ("miFPadder4Rnd.vhd", "miFPAdder4Rnd"),   ("miFPmult4.vhd", "miFPmult4")),
    6:  ("radix64",   ("miFPadder6Rnd.vhd", "miFPAdder6Rnd"),   ("miFPmult6.vhd", "miFPmult6")),
    8:  ("radix256",  ("miFPadder8Rnd.vhd", "miFPAdder8Rnd"),   ("miFPmult8.vhd", "miFPmult8")),
    12: ("radix4096", ("miFPadder12Rnd.vhd", "miFPAdder12Rnd"), ("miFPmult12.vhd", "miFPmult12")),
    24: ("radix2p24", ("miFPadderRnd.vhd", "miFPAdderRnd"),     ("miFPmult.vhd", "miFPmult")),
}
CONVERTERS = ["IEEE2miFP.vhd", "miFP2IEEE.vhd"]      # radix 64 only

# Test bench: reads two hexadecimal operands per line, writes the result in binary.
TB = """library ieee; use ieee.std_logic_1164.all; use std.textio.all; use std.env.all;
entity tb is end entity;
architecture sim of tb is
  signal x, y : std_logic_vector({wi}-1 downto 0);
  signal r : std_logic_vector({wo}-1 downto 0);
begin
  u : entity work.{dut} port map ({ports});
  process
    file fi : text open read_mode is "{name}_in.txt";
    file fo : text open write_mode is "{name}_out.txt";
    variable l, lo : line; variable a, b : std_logic_vector({wh}-1 downto 0); variable c : character;
  begin
    while not endfile(fi) loop
      readline(fi, l); hread(l, a); read(l, c); hread(l, b);
      x <= a({wi}-1 downto 0); y <= b({wi}-1 downto 0); wait for 1 ns;
      write(lo, to_string(r)); writeline(fo, lo);
    end loop;
    finish;
  end process;
end architecture;
"""


def ghdl(args, cwd):
    return subprocess.run(["ghdl"] + args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def compile_radix(r, build):
    """Analyse the files of one radix into their own library (the package
    'parametros' has the same name in every radix).  Returns (dir, errors)."""
    folder, add, mul = DESIGNS[r]
    lib = os.path.join(build, folder)
    shutil.rmtree(lib, ignore_errors=True)
    os.makedirs(lib)
    src = os.path.join(ROOT, "rtl")
    files = [os.path.join(src, folder, "parametros.vhd"), os.path.join(src, "common", "sOR.vhd"),
             os.path.join(src, folder, add[0]), os.path.join(src, folder, mul[0])]
    if r == 6:
        files += [os.path.join(src, folder, f) for f in CONVERTERS]
    errors = {}
    for f in files:
        p = ghdl(["-a"] + GHDL + [f], lib)
        if p.returncode:
            errors[os.path.basename(f)] = p.stdout.strip().split("\n")[0]
    return lib, errors


def simulate(lib, name, dut, ports, wi, wo, vectors):
    wh = 4 * ((wi + 3) // 4)
    open(os.path.join(lib, "tb_%s.vhd" % name), "w").write(
        TB.format(dut=dut, ports=ports, wi=wi, wo=wo, wh=wh, name=name))
    with open(os.path.join(lib, name + "_in.txt"), "w") as f:
        for a, b in vectors:
            f.write("%0*X %0*X\n" % (wh // 4, a, wh // 4, b))
    for args in (["-a"] + GHDL + ["tb_%s.vhd" % name], ["-r"] + GHDL + ["tb", "--ieee-asserts=disable"]):
        p = ghdl(args, lib)
        if p.returncode:
            return None, p.stdout.strip().split("\n")[-1]
    return [l.strip() for l in open(os.path.join(lib, name + "_out.txt"))], None


# ------------------------------------------------------------------ operands
def normal(fmt, rng, exp=None, sign=None, kind="rand"):
    if exp is None:
        exp = rng.randrange(1 << fmt.e)
    if sign is None:
        sign = rng.randrange(2)
    top = rng.randrange(1, 1 << fmt.r)
    low = rng.randrange(1 << fmt.w)
    if kind == "sparse":      # long runs of zeros / ones, powers of the radix
        top = rng.choice([1, (1 << fmt.r) - 1, top])
        low = rng.choice([0, 1, (1 << fmt.w) - 1, 1 << (fmt.w - 1), low & ~((1 << rng.randrange(fmt.w)) - 1)])
    return fmt.pack(NORMAL, sign, exp, (top << fmt.w) | low)


def special(fmt, rng, exc):
    """Zero, infinity or NaN.  Their exponent and significand fields have no
    meaning: they are filled with zeros, with ones or with random bits."""
    fill = rng.randrange(4)
    if fill == 0:
        e, m = 0, 0
    elif fill == 1:
        e, m = (1 << fmt.e) - 1, (1 << fmt.sig_bits) - 1
    else:
        e, m = rng.randrange(1 << fmt.e), rng.randrange(1 << fmt.sig_bits)
    return fmt.pack(exc, rng.randrange(2), e, m)


def vectors_add(fmt, rng, n):
    """Random pairs for every exponent difference and both effective operations."""
    out = []
    for d in range(fmt.f + 4):
        for op in (0, 1):
            for kind in ("rand", "sparse"):
                for _ in range(n):
                    ex = rng.randrange(fmt.f + 4, (1 << fmt.e) - 2)
                    sx = rng.randrange(2)
                    a = normal(fmt, rng, ex, sx, kind)
                    b = normal(fmt, rng, ex - d, sx ^ op, kind)
                    out.append((b, a) if rng.random() < 0.5 else (a, b))
    return out


def vectors_cancel(fmt, rng, n):
    """Subtractions in which leading digits cancel (exponent difference 0, 1, 2)."""
    out = []
    for _ in range(n):
        ex = rng.randrange(fmt.f + 3, (1 << fmt.e) - 2)
        sx = rng.randrange(2)
        d = rng.choice([0, 0, 1, 1, 1, 2])
        if d == 0:
            sig = rng.randrange(1 << fmt.w, 1 << fmt.sig_bits)
            other = sig ^ rng.randrange(1 << rng.randrange(1, fmt.sig_bits))
            if other >> fmt.w == 0:
                other |= 1 << fmt.w
            a, b = fmt.pack(NORMAL, sx, ex, sig), fmt.pack(NORMAL, sx ^ 1, ex, other)
        else:
            # X just above a power of the radix, Y just below it, d digits lower
            a = fmt.pack(NORMAL, sx, ex, (1 << fmt.w) | (rng.randrange(1 << fmt.w) >> rng.randrange(fmt.w)))
            b = fmt.pack(NORMAL, sx ^ 1, ex - d,
                         (((1 << fmt.r) - 1 - (rng.randrange(1 << fmt.r) >> rng.randrange(fmt.r + 1))) << fmt.w)
                         | rng.randrange(1 << fmt.w))
        out.append((b, a) if rng.random() < 0.5 else (a, b))
    return out


def vectors_add_rounding(fmt, rng, n):
    """Significands at the ends of their range: carries out of the adder,
    rounding overflows (all ones plus a small operand), exact powers."""
    ones = (1 << fmt.sig_bits) - 1
    edge = [ones, ones - 1, ones ^ 1 << fmt.w, 1 << fmt.w, (1 << fmt.w) + 1, (1 << fmt.sig_bits) - (1 << fmt.w),
            1 << (fmt.sig_bits - 1), (1 << (fmt.sig_bits - 1)) - 1]
    out = []
    for _ in range(n):
        ex = rng.randrange(fmt.f + 4, (1 << fmt.e) - 2)
        d = rng.randrange(fmt.f + 4)
        sx, op = rng.randrange(2), rng.randrange(2)
        ma = rng.choice(edge)
        mb = rng.choice(edge + [rng.randrange(1 << fmt.w, 1 << fmt.sig_bits)] * 4)
        a, b = fmt.pack(NORMAL, sx, ex, ma), fmt.pack(NORMAL, sx ^ op, ex - d, mb)
        out.append((b, a) if rng.random() < 0.5 else (a, b))
    return out


def vectors_special(fmt, rng, n):
    """Zeros, infinities, NaNs and numbers at both ends of the exponent range."""
    def word(kind):
        if kind in (ZERO, INF, NAN):
            return special(fmt, rng, kind)
        if kind == "big":
            return normal(fmt, rng, rng.randrange((1 << fmt.e) - 3, 1 << fmt.e))
        if kind == "small":
            return normal(fmt, rng, rng.randrange(0, 3))
        return normal(fmt, rng)
    kinds = [ZERO, INF, NAN, "big", "small", "num"]
    return [(word(a), word(b)) for a in kinds for b in kinds for _ in range(n)]


def vectors_mul(fmt, rng, n):
    out = []
    half = 1 << (fmt.e - 2)
    for kind in ("rand", "sparse"):
        for _ in range(n):
            ea, eb = (rng.randrange(fmt.bias - half + 1, fmt.bias + half - 1) for _ in range(2))
            out.append((normal(fmt, rng, ea, None, kind), normal(fmt, rng, eb, None, kind)))
    return out


def vectors_mul_rounding(fmt, rng, n):
    """Products next to a power of the radix: the normalization decision and
    the rounding overflow (significand all ones that rounds up to 1.0)."""
    lo, hi = 1 << fmt.w, 1 << fmt.sig_bits
    half = 1 << (fmt.e - 2)
    k = fmt.w + fmt.r // 2                      # 2^(2k) is the limit between one and two integer digits
    pairs = [((1 << k) - 1, (1 << k) + 1), ((1 << k) + 1, (1 << k) - 1), (1 << k, 1 << k),
             (hi - 1, hi - 1), (lo, lo), (lo, hi - 1), (hi - 1, lo + 1)]
    target = 1 << (2 * fmt.sig_bits - fmt.r)
    for _ in range(n):
        x = rng.randrange(lo, hi)
        y = (target - 1) // x
        pairs += [(x, yy) for yy in (y - 1, y, y + 1) if lo <= yy < hi]
    return [(fmt.pack(NORMAL, rng.randrange(2), rng.randrange(fmt.bias - half + 1, fmt.bias + half - 1), x),
             fmt.pack(NORMAL, rng.randrange(2), rng.randrange(fmt.bias - half + 1, fmt.bias + half - 1), y))
            for x, y in pairs]


# ------------------------------------------------------------------ checking
def decode(fmt, bits):
    """Class and value of an output word; the unused fields of zeros,
    infinities and NaNs are ignored."""
    if set(bits) - set("01"):
        return ("undefined",)
    exc, s, e, m = fmt.unpack(int(bits, 2))
    return {ZERO: ("zero",), NAN: ("nan",), INF: ("inf", s)}.get(exc, ("num", s, e, m))


def run_group(fmt, lib, name, dut, op, vectors):
    outs, err = simulate(lib, name, dut, "x, y, r", fmt.width, fmt.width, vectors)
    if outs is None:
        return "FAIL", "simulation failed: " + err
    bad = Counter()
    inexact, worst, zeros = 0, Fraction(0), 0
    for (a, b), bits in zip(vectors, outs):
        got = decode(fmt, bits)
        exp = fmt.add(a, b) if op == "add" else fmt.mul(a, b)
        if got != exp:
            bad["expected %s, got %s" % (exp[0], got[0]) if exp[0] != got[0] else "wrong " +
                ("sign of infinity" if exp[0] == "inf" else "value")] += 1
            continue
        if op == "add":
            ideal = fmt.add_exact(a, b)
            if exp != ideal:
                # the model may only leave the ideal result when the leading
                # digit cancels and the exponents differ
                (_, _, ea, _), (_, _, eb, _) = fmt.unpack(a), fmt.unpack(b)
                if not (ideal[0] == "num" and ea != eb and ideal[2] < max(ea, eb)):
                    bad["model differs from the ideal result without a cancellation"] += 1
                    continue
                inexact += 1
                if exp[0] == "zero":
                    zeros += 1
                else:
                    exact = fmt.value(a) + fmt.value(b)
                    worst = max(worst, abs(fmt.value(fmt.word(exp)) - exact) / abs(exact))
    detail = "%d/%d as the model" % (len(vectors) - sum(bad.values()), len(vectors))
    if op == "add":
        detail += "; %d correctly rounded" % (len(vectors) - sum(bad.values()) - inexact)
        if inexact:
            detail += ", %d cancellations with reduced accuracy" % inexact
            if worst:
                detail += " (relative error up to 2^%d)" % floor_log2(worst)
            if zeros:
                detail += ", %d of them returned as zero" % zeros
    if bad:
        detail += "; " + ", ".join("%s: %d" % kv for kv in sorted(bad.items(), key=lambda kv: -kv[1]))
    return ("FAIL" if bad else "PASS"), detail


def run_converters(fmt, lib, rng, n):
    res = []
    # IEEE -> high radix: every exponent, random fractions
    xs = [(s << 31) | (e << 23) | f for e in range(256) for s in (0, 1)
          for f in [0, 1, 0x7FFFFF] + [rng.randrange(1 << 23) for _ in range(n)]]
    outs, err = simulate(lib, "ieee2hr", "IEEE2miFP", "X => x, Result => r", 32, fmt.width, [(x, 0) for x in xs])
    if outs is None:
        res.append(("ieee_to_hr", "FAIL", "simulation failed: " + err))
    else:
        bad = Counter()
        for x, bits in zip(xs, outs):
            e, g = fmt.from_ieee(x), decode(fmt, bits)
            if e != g:
                bad["expected %s, got %s" % (e[0], g[0]) if e[0] != g[0] else "wrong value"] += 1
        res.append(("ieee_to_hr", "FAIL" if bad else "PASS", "%d/%d as the model (exact conversion)"
                    % (len(xs) - sum(bad.values()), len(xs))
                    + ("; " + ", ".join("%s: %d" % kv for kv in bad.items()) if bad else "")))
    # high radix -> IEEE: every exponent, random and sparse significands, special values
    ws = [normal(fmt, rng, e, None, k) for e in range(1 << fmt.e) for k in ("rand", "sparse") for _ in range(4 * n)]
    ws += [special(fmt, rng, k) for k in (ZERO, INF, NAN) for _ in range(20)]
    outs, err = simulate(lib, "hr2ieee", "miFP2IEEE", "X => x, result => r", fmt.width, 32, [(w, 0) for w in ws])
    if outs is None:
        res.append(("hr_to_ieee", "FAIL", "simulation failed: " + err))
    else:
        bad = Counter()
        for w, bits in zip(ws, outs):
            e = fmt.to_ieee(w)
            if set(bits) - set("01"):
                bad["undefined bits"] += 1
                continue
            g = int(bits, 2)
            ge, gf = (g >> 23) & 0xFF, g & 0x7FFFFF
            gc = ("zero",) if ge == 0 and gf == 0 else ("nan",) if ge == 255 and gf else \
                 ("inf", g >> 31) if ge == 255 else ("num", g)
            if e != gc:
                bad["expected %s, got %s" % (e[0], gc[0]) if e[0] != gc[0] else "wrong value"] += 1
        res.append(("hr_to_ieee", "FAIL" if bad else "PASS", "%d/%d as the model (round to nearest even)"
                    % (len(ws) - sum(bad.values()), len(ws))
                    + ("; " + ", ".join("%s: %d" % kv for kv in bad.items()) if bad else "")))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quick", action="store_true", help="about ten times fewer vectors")
    ap.add_argument("--radix", type=int, nargs="+", choices=sorted(DESIGNS), default=sorted(DESIGNS),
                    help="digit sizes (bits) to test: 4, 6, 8, 12, 24 (default: all)")
    ap.add_argument("--seed", type=int, default=2022)
    args = ap.parse_args()
    if shutil.which("ghdl") is None:
        sys.exit("GHDL not found on the PATH")
    n = 40 if args.quick else 400
    build = os.path.join(ROOT, "build", "ghdl")
    results = []
    for r in args.radix:
        fmt = Format(r)
        rng = random.Random(args.seed + r)
        folder, add, mul = DESIGNS[r]
        lib, errors = compile_radix(r, build)
        for f, e in errors.items():
            results.append((folder, "compile " + f, "FAIL", e))
        groups = [("add_random", add[1], "add", vectors_add(fmt, rng, n)),
                  ("add_cancellation", add[1], "add", vectors_cancel(fmt, rng, 10 * n)),
                  ("add_rounding", add[1], "add", vectors_add_rounding(fmt, rng, 10 * n)),
                  ("add_special", add[1], "add", vectors_special(fmt, rng, n // 4)),
                  ("mul_random", mul[1], "mul", vectors_mul(fmt, rng, 4 * n)),
                  ("mul_rounding", mul[1], "mul", vectors_mul_rounding(fmt, rng, 5 * n)),
                  ("mul_special", mul[1], "mul", vectors_special(fmt, rng, n // 4))]
        for name, dut, op, vec in groups:
            verdict, detail = run_group(fmt, lib, name, dut, op, vec)
            results.append((folder, name, verdict, detail))
        if r == 6:
            for name, verdict, detail in run_converters(fmt, lib, rng, max(2, n // 40)):
                results.append((folder, name, verdict, detail))
    for folder, name, verdict, detail in results:
        print("%-5s %-10s %-17s %s" % (verdict, folder, name, detail))
    c = Counter(v for _, _, v, _ in results)
    print("%d groups: %d pass, %d fail" % (len(results), c["PASS"], c["FAIL"]))
    return 1 if c["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
