--------------------------------------------------------------------------------
-- File    : IEEE2miFP.vhd
-- Project : high-radix-fp-fpga
--
-- Entity:
--   IEEE2miFP - IEEE-754 single precision to the radix-64 format
--
-- Architecture:
--   Direct conversion of Fig. 2 of the paper (Eq. 18-19).  An IEEE number
--   1.F * 2^e is rewritten as M' * 64^q, with e = 6*q + k and 0 <= k < 6:
--
--     - a look-up table addressed by the 8-bit IEEE exponent gives the
--       high-radix exponent q + bias and the shift amount;
--     - the significand 1.F is placed in digit D0 with its leading one at
--       bit k of the digit, i.e. shifted right R-1-k bits from the top.
--
--   The table is computed at elaboration time by the function init_rom.
--   The conversion is exact: no rounding is needed.
--
-- Parameters:
--   Package work.parametros of this folder: R = 6, M = 24, E = 6, D = 3.
--   The shifter is written for R = 6.
--
-- Ports:
--   X      : IEEE-754 single-precision word (32 bits)
--   Result : high-radix word,
--     [ exc (2) | sign (1) | exponent (E) | significand (R+M) ]
--       exc         : "00" zero, "01" number, "10" infinity, "11" NaN
--       exponent    : power of 2^R, biased by 2^(E-1)
--       significand : one integer digit D0 (R bits, not zero in a number)
--                     followed by M fractional bits (digits D1 .. Df)
--
-- Special cases:
--   IEEE zeros and subnormal numbers give zero.  Infinities and NaNs keep
--   their class.
--
-- Latency:
--   0 (combinational).
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
use ieee.std_logic_arith.all;
use ieee.std_logic_unsigned.all;

library work;
use work.parametros.all;

entity IEEE2miFP is
   port ( X      : in  std_logic_vector(1+8+23-1 downto 0);
          Result : out std_logic_vector(2+1+E+M+R-1 downto 0) );
end entity;

architecture arch of IEEE2miFP is

   signal fracX      : std_logic_vector(23+R downto 0);       -- 1.F left-aligned in the significand
   signal fracresult : std_logic_vector(23+R downto 0);
   signal expydesp   : std_logic_vector(E+D-1+3 downto 0);    -- table output
   signal exc        : std_logic_vector(1 downto 0);
   signal ORfrac     : std_logic;                             -- the IEEE fraction is not zero

   -- Look-up table, one word per IEEE exponent:
   --   [ special (2) | number (1) | high-radix exponent (E) | shift (D) ]
   -- special = "01" for exponent 255 (infinity or NaN); number = '1' for
   -- exponents 1 .. 254; exponent 0 (zero, subnormals) gives all zeros.
   type rom_type is array (255 downto 0) of std_logic_vector(E+D-1+3 downto 0);
   function init_rom return rom_type is
      variable t    : rom_type;
      variable q, k : integer;
   begin
      for i in 0 to 255 loop
         k := (i - 127) mod R;            -- position of the leading one inside digit D0
         q := (i - 127 - k) / R;          -- exponent of the radix (floor division)
         if i = 0 then
            t(i) := (others => '0');
         elsif i = 255 then
            t(i) := "010" & CONV_STD_LOGIC_VECTOR(0, E+D);
         else
            t(i) := "001" & CONV_STD_LOGIC_VECTOR(q + 2**(E-1), E) & CONV_STD_LOGIC_VECTOR(R-1-k, D);
         end if;
      end loop;
      return t;
   end function;
   constant ROM : rom_type := init_rom;

begin

   expydesp <= ROM(CONV_INTEGER(X(30 downto 23)));

   -- Exception field: "01" number, "10" infinity, "11" NaN (exponent 255 and a
   -- non-zero fraction), "00" zero.
   ORfrac <= '0' when X(22 downto 0) = CONV_STD_LOGIC_VECTOR(0,23) else '1';
   exc(1) <= expydesp(E+D+1);
   exc(0) <= expydesp(E+D) or (expydesp(E+D+1) and ORfrac);

   -- Hidden one and fraction at the top of the significand, then shifted
   -- right 0 .. R-1 bits so that the leading one falls at bit k of digit D0.
   fracX <= '1' & X(22 downto 0) & CONV_STD_LOGIC_VECTOR(0,R);

   with CONV_INTEGER(expydesp(D-1 downto 0)) select
      fracresult <= fracX                                               when 0,
                    CONV_STD_LOGIC_VECTOR(0,1) & fracX(23+R downto 1)   when 1,
                    CONV_STD_LOGIC_VECTOR(0,2) & fracX(23+R downto 2)   when 2,
                    CONV_STD_LOGIC_VECTOR(0,3) & fracX(23+R downto 3)   when 3,
                    CONV_STD_LOGIC_VECTOR(0,4) & fracX(23+R downto 4)   when 4,
                    CONV_STD_LOGIC_VECTOR(0,5) & fracX(23+R downto 5)   when others;

   Result <= exc & X(31) & expydesp(E+D-1 downto D) & fracresult;

end arch;
