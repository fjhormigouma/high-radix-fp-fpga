"""Reference model of the high-radix floating-point operators of this
repository (Python, exact rational arithmetic).

Format (J. Villalba and J. Hormigo, "High-Radix Formats for Enhancing
Floating-Point FPGA Implementations", Circuits, Systems, and Signal
Processing 41, 1683-1703, 2022, https://doi.org/10.1007/s00034-021-01855-x):

    x = (-1)^s * M' * (2^r)^(E' - bias),   1 <= M' < 2^r,   bias = 2^(E-1)

M' has one integer digit of r bits and 24 fractional bits.  Word layout of
the VHDL: [exc(2) | s | E'(E bits) | M'(r + 24 bits)], with exc = 00 zero,
01 number, 10 infinity, 11 NaN.

    from hrfp import Format, NORMAL
    fmt = Format(6)                         # radix 64
    a = fmt.from_float(1.5)
    b = fmt.from_float(-0.375)
    print(fmt.add(a, b), fmt.to_float(fmt.word(fmt.add(a, b))))

Format.add, Format.mul, Format.from_ieee and Format.to_ieee return what the
VHDL entities return, bit for bit (tb/run_tests.py checks it);
Format.add_exact is the ideal, correctly rounded sum, used to measure the
accuracy of the adders.

Copyright (C) 2022 Javier Hormigo, Universidad de Malaga
SPDX-License-Identifier: LGPL-3.0-or-later
"""
from fractions import Fraction
import math
import struct

#: Exponent width for each r: ceil(8 - log2 r).
EXPONENT_BITS = {r: math.ceil(8 - math.log2(r)) for r in range(2, 25)}

ZERO, NORMAL, INF, NAN = 0, 1, 2, 3


def parameters(r):
    """Parameters of the format with digits of r bits: number of fractional
    digits f, fractional bits w, exponent bits E, word width, and the powers
    of two of the smallest and largest numbers."""
    f = -(-24 // r)
    w = r * f
    e = EXPONENT_BITS[r]
    return dict(r=r, f=f, w=w, E=e, word_bits=3 + e + r + w,
                min_exp2=-r * 2 ** (e - 1), max_exp2=r * (2 ** (e - 1) - 1) + r - 1)


class Format:
    """High-radix format with digits of ``r`` bits and 24 fractional bits
    (r must divide 24: r = 2, 3, 4, 6, 8, 12 or 24)."""

    def __init__(self, r):
        if 24 % r:
            raise ValueError("this model only supports digit sizes that divide 24")
        self.r = r
        self.w = 24
        self.f = 24 // r
        self.e = EXPONENT_BITS[r]
        self.bias = 1 << (self.e - 1)
        self.sig_bits = r + 24
        self.width = 3 + self.e + self.sig_bits

    # ---- words -----------------------------------------------------------
    def pack(self, exc, sign, exp, sig):
        return (exc << (1 + self.e + self.sig_bits)) | (sign << (self.e + self.sig_bits)) \
            | (exp << self.sig_bits) | sig

    def unpack(self, word):
        return ((word >> (1 + self.e + self.sig_bits)) & 3, (word >> (self.e + self.sig_bits)) & 1,
                (word >> self.sig_bits) & ((1 << self.e) - 1), word & ((1 << self.sig_bits) - 1))

    def value(self, word):
        """Exact value of a word (Fraction); None for infinity and NaN."""
        exc, sign, exp, sig = self.unpack(word)
        if exc == ZERO:
            return Fraction(0)
        if exc != NORMAL:
            return None
        v = Fraction(sig, 1 << self.w) * Fraction(2) ** (self.r * (exp - self.bias))
        return -v if sign else v

    def word(self, res):
        """Pack a result tuple ('zero',), ('inf', s), ('nan',) or
        ('num', s, exp, sig) into a word."""
        if res[0] == "num":
            return self.pack(NORMAL, res[1], res[2], res[3])
        if res[0] == "inf":
            return self.pack(INF, res[1], 0, 0)
        return self.pack(NAN if res[0] == "nan" else ZERO, 0, 0, 0)

    def from_float(self, x):
        """Word for a Python float (through IEEE single precision)."""
        return self.word(self.from_ieee(float_to_ieee(x)))

    def to_float(self, word):
        """Python float nearest to the value of a word."""
        exc, sign, _, _ = self.unpack(word)
        if exc == NAN:
            return float("nan")
        if exc == INF:
            return float("-inf") if sign else float("inf")
        return float(self.value(word))

    # ---- rounding --------------------------------------------------------
    def round(self, v):
        """Normalize the exact value ``v`` and round it with Eq. (23): the
        significand is truncated to w fractional bits and, if the discarded
        part is not zero, its LSB is added to itself.
        Returns (sign, biased exponent, significand); the exponent may fall
        outside 0 .. 2**E - 1 (overflow / underflow)."""
        sign = int(v < 0)
        a = abs(v)
        k = floor_log2(a) // self.r
        m = a / Fraction(2) ** (self.r * k) * (1 << self.w)
        t = m.numerator // m.denominator
        if m != t and (t & 1):
            t += 1
        if t >> self.sig_bits:              # rounding overflow: 2^r -> 1.0, exponent + 1
            t >>= self.r
            k += 1
        return sign, k + self.bias, t

    def result(self, v, sign_of_zero=0):
        """Word for the exact value ``v`` (rounded), with overflow to
        infinity and underflow to zero.  Returns (exc, sign, exp, sig)."""
        if v == 0:
            return (ZERO, sign_of_zero, 0, 0)
        s, e, m = self.round(v)
        if e >= (1 << self.e):
            return (INF, s, 0, 0)
        if e < 0:
            return (ZERO, s, 0, 0)
        return (NORMAL, s, e, m)

    # ---- operations ------------------------------------------------------
    def add_exact(self, a, b):
        """Ideal result of a + b: the exact sum, normalized and rounded with
        Eq. (23).  Returns ('nan',), ('inf', sign), ('zero',) or
        ('num', sign, exp, sig)."""
        (ea, sa, _, _), (eb, sb, _, _) = self.unpack(a), self.unpack(b)
        if NAN in (ea, eb) or (ea == INF and eb == INF and sa != sb):
            return ("nan",)
        if ea == INF:
            return ("inf", sa)
        if eb == INF:
            return ("inf", sb)
        return self._classify(self.value(a) + self.value(b))

    def add(self, a, b):
        """Result of the VHDL adders, bit for bit.  It follows the datapath
        of the hardware: alignment by digits keeping one guard bit and one
        sticky bit, addition, rounding (Eq. 23) and normalization by digits.

        It is equal to add_exact() except when the leading digit cancels in
        a subtraction of operands whose exponents differ (the guard and
        sticky bits do not hold enough information then)."""
        ex = self.add_exact(a, b)
        if ex[0] in ("nan", "inf"):
            return ex
        (ca, sa, xa, ma), (cb, sb, xb, mb) = self.unpack(a), self.unpack(b)
        if ca == ZERO and cb == ZERO:
            return ("zero",)
        # swap: X is the operand with the larger (class, exponent)
        if (ca, xa) < (cb, xb):
            (ca, sa, xa, ma), (cb, sb, xb, mb) = (cb, sb, xb, mb), (ca, sa, xa, ma)
        if cb == ZERO:
            mb, d = 0, 0
        else:
            d = xa - xb
        n, nd = self.sig_bits, self.f + 1
        # alignment: significand of Y, guard bit and sticky bit
        if self.r == 24:
            if d == 0:
                y = mb << 2
            elif d == 1:
                y = ((mb >> self.r) << 2) | (((mb >> (self.r - 1)) & 1) << 1) | int(mb & ((1 << (self.r - 1)) - 1) != 0)
            elif d == 2:
                y = ((mb >> (n - 1)) << 1) | int(mb & ((1 << (n - 1)) - 1) != 0)
            else:
                y = int(mb != 0)
        else:
            dd = min(d, nd)
            y = (((mb << 1) >> (self.r * dd)) << 1) | int(mb & ((1 << (self.r * dd)) - 1) != 0)
        sub = sa != sb
        total = (ma << 2) - y if sub else (ma << 2) + y
        sign = sa
        if total < 0:                        # only with equal exponents: nothing was shifted out
            total, sign = -total, sa ^ 1
        over = total >> (n + 2)              # carry out of an addition
        if over:
            kept = total >> (self.r + 2)
            lost = total & ((1 << (self.r + 2)) - 1)
        else:
            kept = total >> 2
            lost = total & 3
        if lost and (kept & 1):              # Eq. (23)
            kept += 1
        exp = xa + over
        if kept >> n:                        # rounding overflow: 1.0, exponent + 1
            kept, exp = 1 << self.w, exp + 1
        elif kept == 0:
            return ("zero",)
        else:
            while kept >> (n - self.r) == 0:   # normalization by digits
                kept <<= self.r
                exp -= 1
        if exp >= (1 << self.e):
            return ("inf", sign)
        if exp < 0:
            return ("zero",)
        return ("num", sign, exp, kept)

    def mul(self, a, b):
        """Result of a * b: the exact product, normalized and rounded with
        Eq. (23).  The VHDL multipliers give exactly this."""
        (ea, sa, _, _), (eb, sb, _, _) = self.unpack(a), self.unpack(b)
        if NAN in (ea, eb) or {ea, eb} == {INF, ZERO}:
            return ("nan",)
        if INF in (ea, eb):
            return ("inf", sa ^ sb)
        return self._classify(self.value(a) * self.value(b))

    def _classify(self, v):
        exc, s, e, m = self.result(v)
        return {ZERO: ("zero",), INF: ("inf", s)}.get(exc, ("num", s, e, m))

    # ---- conversions (Sect. 2.3) ----------------------------------------
    def from_ieee(self, x):
        """Expected conversion of an IEEE-754 single word (Eq. 18-19):
        exact.  Zeros and subnormals give zero."""
        s, e, f = x >> 31, (x >> 23) & 0xFF, x & 0x7FFFFF
        if e == 0:
            return ("zero",)
        if e == 255:
            return ("nan",) if f else ("inf", s)
        v = Fraction((1 << 23) | f, 1 << 23) * Fraction(2) ** (e - 127)
        return self._classify(-v if s else v)

    def to_ieee(self, word):
        """Expected conversion to IEEE-754 single (Eq. 21), round to nearest
        even.  No subnormals: values below 2**-126 give zero."""
        exc, s, _, _ = self.unpack(word)
        if exc == ZERO:
            return ("zero",)
        if exc == INF:
            return ("inf", s)
        if exc == NAN:
            return ("nan",)
        a = abs(self.value(word))
        e2 = floor_log2(a)
        m = a / Fraction(2) ** e2 * (1 << 23)
        t = m.numerator // m.denominator
        rem = m - t
        if rem > Fraction(1, 2) or (rem == Fraction(1, 2) and (t & 1)):
            t += 1
        if t >> 24:
            t >>= 1
            e2 += 1
        if e2 > 127:
            return ("inf", s)
        if e2 < -126 or floor_log2(a) < -126:      # the range test is done before rounding
            return ("zero",)
        return ("num", (s << 31) | ((e2 + 127) << 23) | (t & 0x7FFFFF))


def floor_log2(a):
    """floor(log2(a)) of a positive Fraction, exactly."""
    k = a.numerator.bit_length() - a.denominator.bit_length()
    while Fraction(2) ** k > a:
        k -= 1
    while Fraction(2) ** (k + 1) <= a:
        k += 1
    return k


def float_to_ieee(x):
    return struct.unpack(">I", struct.pack(">f", x))[0]


def ieee_to_float(w):
    return struct.unpack(">f", struct.pack(">I", w))[0]
