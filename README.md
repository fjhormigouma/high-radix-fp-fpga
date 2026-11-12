# high-radix-fp-fpga

Synthesizable VHDL floating-point adders, multipliers and IEEE-754 converters for **high-radix
floating-point formats** on FPGAs, with a Python reference model and self-checking tests.

In a high-radix format the significand is a string of radix-2^r digits and the exponent is a power of 2^r.
Alignment and normalization then shift whole digits instead of bits, so the barrel shifters and the
leading-zero counter of a conventional floating-point adder, which dominate its delay on an FPGA, shrink to
multiplexers with a handful of inputs.  The formats implemented here hold at least the precision of IEEE-754
single precision.  The formats and the architectures are described in

> J. Villalba and J. Hormigo, "High-Radix Formats for Enhancing Floating-Point FPGA Implementations",
> *Circuits, Systems, and Signal Processing* 41, 1683-1703, 2022.
> https://doi.org/10.1007/s00034-021-01855-x (open access)

## What is in the repository

```
rtl/
  common/sOR.vhd                                   OR-reduction (sticky bits, zero detection)
  radix16/    parametros.vhd  miFPadder4Rnd.vhd   miFPmult4.vhd
  radix64/    parametros.vhd  miFPadder6Rnd.vhd   miFPmult6.vhd   IEEE2miFP.vhd  miFP2IEEE.vhd
  radix256/   parametros.vhd  miFPadder8Rnd.vhd   miFPmult8.vhd
  radix4096/  parametros.vhd  miFPadder12Rnd.vhd  miFPmult12.vhd
  radix2p24/  parametros.vhd  miFPadderRnd.vhd    miFPmult.vhd
model/hrfp.py      reference model of the operators (Python, exact arithmetic)
tb/run_tests.py    self-checking tests: GHDL simulation against the model
```

| Folder | Radix | Digit bits (R) | Exponent bits (E) | Digits | Word bits | Range | Adder | Multiplier |
|---|---|---|---|---|---|---|---|---|
| `radix16` | 16 | 4 | 6 | 7 | 37 | 2^-128 .. 2^128 | `miFPAdder4Rnd` | `miFPmult4` |
| `radix64` | 64 | 6 | 6 | 5 | 39 | 2^-192 .. 2^192 | `miFPAdder6Rnd` | `miFPmult6` |
| `radix256` | 256 | 8 | 5 | 4 | 40 | 2^-128 .. 2^128 | `miFPAdder8Rnd` | `miFPmult8` |
| `radix4096` | 4096 | 12 | 5 | 3 | 44 | 2^-192 .. 2^192 | `miFPAdder12Rnd` | `miFPmult12` |
| `radix2p24` | 2^24 | 24 | 4 | 2 | 55 | 2^-192 .. 2^192 | `miFPAdderRnd` | `miFPmult` |

All the operators are combinational; add your own pipeline registers around or between them.  Converters from
and to IEEE-754 single precision are provided for radix 64 (`IEEE2miFP`, `miFP2IEEE`).

## Number format

```
value = (-1)^s * M' * (2^R)^(E' - bias)        1 <= M' < 2^R,    bias = 2^(E-1)

word  = [ exc (2) | s (1) | E' (E bits) | M' (R + 24 bits) ]      2 + 1 + E + R + 24 bits, MSB first
```

* `M'` is the significand: one integer digit of R bits, which is never zero in a number, followed by
  24 fractional bits.  There is no hidden bit.  Depending on the position of the leading one inside the
  integer digit, a number has between 25 and R + 24 significant bits.
* `exc` is an explicit class field (the convention of FloPoCo): `00` zero, `01` number, `10` infinity,
  `11` NaN.  The other fields of a zero, an infinity or a NaN are ignored on input and meaningless on output.
* There are no subnormal numbers and no signed zeros.  Overflow gives infinity and underflow gives zero.
* **Rounding** is not round-to-nearest: the result is truncated to 24 fractional bits and, when the discarded
  part is not zero, its least significant bit is added to itself (Eq. (23) of the paper).

Example, radix 64 (R = 6, E = 6, bias 32): 1.5 is `exc = 01, s = 0, E' = 32, M' = 000001.100000...0`, i.e. the
39-bit word `0x2801800000`.

## Using the operators

1. Pick a radix and add to your project `rtl/common/sOR.vhd` and the files of that folder, with
   `parametros.vhd` first.
2. Instantiate the entities.  The adders compute `X + Y`; to subtract, invert the sign bit of `Y`
   (bit `E+M+R` of the word).

```vhdl
library ieee;
use ieee.std_logic_1164.all;
use work.parametros.all;          -- R, M, E of the radix that was compiled

entity axpy is                    -- res = a*x + y
   port ( a, x, y : in  std_logic_vector(2+1+E+M+R-1 downto 0);
          res     : out std_logic_vector(2+1+E+M+R-1 downto 0) );
end entity;

architecture rtl of axpy is
   signal p : std_logic_vector(2+1+E+M+R-1 downto 0);
begin
   mul : entity work.miFPmult6     port map ( X => a, Y => x, result => p );
   add : entity work.miFPAdder6Rnd port map ( X => p, Y => y, result => res );
end architecture;
```

Things to know:

* **One radix per library.**  The package `parametros` has the same name in every folder, so two radices
  cannot be compiled into the same VHDL library.
* The digit structure is written out in each adder (the alignment and normalization multiplexers have one
  input per digit), so a different radix needs its own adder file; editing the constants of the package is
  not enough.  The multipliers are generic in R, M and E.
* The files use the Synopsys packages `ieee.std_logic_arith` and `ieee.std_logic_unsigned`, which the FPGA
  vendor tools accept.  With GHDL use `--std=08 -frelaxed -fsynopsys -fexplicit`.
* The significand product of the multipliers is written with `*`, so that the synthesis tool maps it onto the
  embedded multipliers (DSP blocks).
* Data enters and leaves the high-radix domain through the converters (radix 64) or directly in the format
  above.  `IEEE2miFP` is exact; `miFP2IEEE` rounds to nearest even, gives zero below 2^-126 (no subnormals are
  produced) and infinity above the IEEE range.
* Identifiers keep the names of the original design, partly in Spanish: `miFP` ("my FP") is the high-radix
  format, `parametros` = parameters, `desp` = shift amount.

Each file starts with a description of its architecture, and the code is commented step by step.

## Limitations

**Catastrophic cancellation in the adders.**  As in a radix-2 adder, the aligned operand keeps only two extra
bits below the significand: a guard bit and a sticky bit.  With digits of R bits this is not always enough.
When the exponents of the operands differ by one digit and the subtraction cancels the leading digit(s), the
result is shifted left by whole digits, and the bits of the smaller operand that were dropped in the alignment
(up to R - 2 per digit) would be needed to fill it in.  In that situation:

* the result is a valid, normalized number, but it is not the correctly rounded difference.  Its absolute
  error stays below one unit in the last place *of the larger operand*; relative to the small result, however,
  the error grows by a factor 2^R for every digit that cancels, and it can reach the order of the result
  itself when nearly all the digits cancel;
* a difference that is tiny but not zero may be returned as zero.

Example in radix 16 (significands in hexadecimal):

```
X =  1.000000 * 16^1  = 16
Y = -F.FFFFE5 * 16^0  = -15.99999839...
exact  X + Y = 1.B00000 * 16^-5 = 1.609e-6      the adder returns 2.000000 * 16^-5 = 1.907e-6

Y = -F.FFFFF5 * 16^0:   exact  X + Y = B.000000 * 16^-6 = 6.557e-7      the adder returns zero
```

All other cases are computed exactly as the format defines: additions, subtractions in which the leading
digit does not cancel, and subtractions of operands with the same exponent (which are exact) give the
correctly rounded result, and so do all the multiplications.  This is the high-radix counterpart of the
catastrophic cancellation of any floating-point subtraction, except that here part of the lost accuracy comes
from the adder and not only from the operands.  Avoiding it would take a full guard digit (R bits) in the
alignment, at the cost of a wider adder.  If your algorithm subtracts nearly equal numbers and relies on the
result, take this into account; `model/hrfp.py` lets you evaluate it (`Format.add` reproduces the adder bit
for bit and `Format.add_exact` gives the ideal result).

Other limitations:

* Single-precision flavour only (24 fractional bits).
* Converters only for radix 64, and only from/to IEEE-754 single precision.
* No subnormal numbers, no signed zeros, no rounding modes, no exception flags other than the class field.
* Combinational operators only.

## Tests

The tests need Python 3.8 or later (standard library only) and [GHDL](https://github.com/ghdl/ghdl) on the
PATH (tested with GHDL 4.1.0).

```
python tb/run_tests.py            # all radices, about 20 seconds
python tb/run_tests.py --quick    # ten times fewer vectors
python tb/run_tests.py --radix 6  # one radix (digit bits: 4, 6, 8, 12, 24)
python tb/run_tests.py --seed 7   # other random operands
```

The script compiles each radix into its own library under `build/`, simulates every adder, multiplier and
converter on about 190,000 random and directed operations and compares each output word with the reference
model:

* additions and subtractions for every exponent difference, with random and sparse significands;
* subtractions in which leading digits cancel; carries out and rounding overflows;
* products of random significands and products next to a power of the radix;
* zeros, infinities and NaNs (with their unused fields at zero, at one and random), exponent overflow and
  underflow;
* conversions from and to IEEE-754 for every exponent.

`PASS` means that every result is the one given by the model.  For the adders the script also checks that the
model coincides with the ideal, correctly rounded sum in every case other than the cancellation described
above, and reports how many results fall in that case and their largest relative error.

## Reference model

`model/hrfp.py` describes the format and the operators with exact rational arithmetic and no dependencies:

```python
import sys; sys.path.insert(0, "model")
from hrfp import Format

fmt = Format(6)                                  # digits of 6 bits: radix 64
a, b = fmt.from_float(1.5), fmt.from_float(-0.375)
print(hex(a))                                    # 0x2801800000
s = fmt.add(a, b)                                # ('num', sign, exponent, significand), as the VHDL adder
print(fmt.to_float(fmt.word(s)))                 # 1.125
print(fmt.to_float(fmt.word(fmt.mul(a, b))))     # -0.5625
```

`add`, `mul`, `from_ieee` and `to_ieee` return what the corresponding VHDL entities return, bit for bit;
`add_exact` returns the ideal sum.

## Licence

GNU Lesser General Public License, version 3 or later (`COPYING.LESSER`, `COPYING`).

The adders and multipliers are derived from VHDL generated by [FloPoCo](https://flopoco.org)
(F. de Dinechin and B. Pasca), which is distributed under the LGPL.

Copyright (C) 2022 Javier Hormigo, Universidad de Málaga.

## How to cite

If you use this code, please cite the article that describes the formats and the architectures:

```bibtex
@article{villalba2022highradix,
  author  = {Villalba, Julio and Hormigo, Javier},
  title   = {High-Radix Formats for Enhancing Floating-Point {FPGA} Implementations},
  journal = {Circuits, Systems, and Signal Processing},
  volume  = {41},
  pages   = {1683--1703},
  year    = {2022},
  doi     = {10.1007/s00034-021-01855-x}
}
```

The metadata of the repository itself is in `CITATION.cff`.

## Contact

Javier Hormigo, Departamento de Arquitectura de Computadores, Universidad de Málaga, Spain.  Please use the
issue tracker of the repository for questions and error reports.
