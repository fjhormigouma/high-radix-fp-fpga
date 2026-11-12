--------------------------------------------------------------------------------
-- File    : parametros.vhd
-- Project : high-radix-fp-fpga
--
-- Package:
--   parametros - parameters of the radix-16 format
--
-- Purpose:
--   Constants shared by the operators of this folder.  Every radix has its
--   own package with the same name: compile each folder of rtl/ into a
--   separate library (see README.md).
--
-- Format:
--   Radix 2^R = 16.  The significand has 7 digits of 4 bits: one integer
--   digit and 6 fractional digits (M = 24 fractional bits).  A word has
--   2 + 1 + E + R + M = 37 bits.
--
-- Reference:
--   J. Villalba and J. Hormigo, "High-Radix Formats for Enhancing Floating-Point
--   FPGA Implementations", Circuits, Systems, and Signal Processing 41,
--   1683-1703, 2022.  https://doi.org/10.1007/s00034-021-01855-x
--
-- Copyright (C) 2022 Javier Hormigo, Universidad de Malaga
--
-- This file is part of high-radix-fp-fpga.  It is free software: you can
-- redistribute it and/or modify it under the terms of the GNU Lesser General
-- Public License as published by the Free Software Foundation, either
-- version 3 of the License, or (at your option) any later version.  It is
-- distributed WITHOUT ANY WARRANTY; without even the implied warranty of
-- MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the files
-- COPYING and COPYING.LESSER.
--
-- SPDX-License-Identifier: LGPL-3.0-or-later
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

package parametros is
  constant R : natural := 4;    -- bits per digit: the radix is 2^R
  constant M : natural := 24;   -- fractional bits of the significand
  constant E : natural := 6;    -- exponent bits, ceil(8 - log2(R)); bias 2^(E-1)
end parametros;
