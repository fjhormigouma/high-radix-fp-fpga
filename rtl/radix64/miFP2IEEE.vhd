--------------------------------------------------------------------------------
-- File    : miFP2IEEE.vhd
-- Project : high-radix-fp-fpga
--
-- Entity:
--   miFP2IEEE - radix-64 format to IEEE-754 single precision
--
-- Architecture:
--   Inverse conversion of Fig. 3 of the paper (Eq. 21):
--
--     - a leading-one detector on digit D0 gives the position k of the
--       leading one (0 <= k < 6);
--     - the significand is shifted so that the leading one becomes the
--       IEEE hidden bit, and it is rounded to 23 fraction bits (round to
--       nearest, ties to even: the radix-64 significand has up to 30 bits);
--     - a look-up table addressed by the high-radix exponent gives
--       6*(E' - bias) + 127, to which k is added.  Exponent and fraction
--       share one adder, so that a rounding overflow increments the
--       exponent.
--
--   The tables are computed at elaboration time (init_rom, init_range).
--
-- Parameters:
--   Package work.parametros of this folder: R = 6, M = 24, E = 6, D = 3.
--   The leading-one detector and the shifter are written for R = 6.
--
-- Ports:
--   X      : high-radix word,
--     [ exc (2) | sign (1) | exponent (E) | significand (R+M) ]
--       exc         : "00" zero, "01" number, "10" infinity, "11" NaN
--       exponent    : power of 2^R, biased by 2^(E-1)
--       significand : one integer digit D0 (R bits, not zero in a number)
--                     followed by M fractional bits (digits D1 .. Df)
--   result : IEEE-754 single-precision word (32 bits)
--
-- Special cases:
--   The exponent range of the radix-64 format (2^-192 .. 2^191) is wider
--   than the IEEE one: larger values give infinity, and values below
--   2^-126 give zero (no subnormal numbers are produced; the range test is
--   done before rounding).  NaN is returned as a quiet NaN.
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

entity miFP2IEEE is
   port ( X      : in  std_logic_vector(2+1+E+M+R-1 downto 0);
          result : out std_logic_vector(1+8+23-1 downto 0) );
end entity;

architecture arch of miFP2IEEE is

   signal fracX     : std_logic_vector(M+R+R-2 downto 0);     -- significand extended with R-1 zeros
   signal fracdesp  : std_logic_vector(M+R-2 downto 0);       -- [23 fraction bits | round bit | R-1 lower bits]
   signal desp      : std_logic_vector(D-1 downto 0);         -- position k of the leading one in D0
   signal exp0      : std_logic_vector(7 downto 0);           -- IEEE exponent for k = 0
   signal under, over, inf, inf0, rnd, stk : std_logic;
   signal sel       : std_logic_vector(3 downto 0);
   signal expfracrd : std_logic_vector(31 downto 0);          -- [carry | exponent (8) | fraction (23)]

   -- Exponent table (T2): IEEE biased exponent of M' = 1, R*(E' - bias) + 127.
   type rom_type is array (natural range 2**E-1 downto 0) of std_logic_vector(7 downto 0);
   function init_rom return rom_type is
      variable t : rom_type;
      variable v : integer;
   begin
      for i in t'range loop
         v := R*(i - 2**(E-1)) + 127;
         if v < 0 or v > 255 then v := 0; end if;     -- out of range: flagged by the tables below
         t(i) := CONV_STD_LOGIC_VECTOR(v, 8);
      end loop;
      return t;
   end function;
   -- Range tables: high-radix exponents whose numbers are all below (low) or
   -- all above (not low) the range of the IEEE normal numbers.
   function init_range(low : boolean) return std_logic_vector is
      variable t : std_logic_vector(2**E-1 downto 0);
      variable v : integer;
   begin
      for i in t'range loop
         v := R*(i - 2**(E-1)) + 127;
         t(i) := '0';
         if low and v + R - 1 < 1 then t(i) := '1'; end if;
         if not low and v > 254 then t(i) := '1'; end if;
      end loop;
      return t;
   end function;
   constant ROM    : rom_type := init_rom;
   constant under0 : std_logic_vector(2**E-1 downto 0) := init_range(true);
   constant over0  : std_logic_vector(2**E-1 downto 0) := init_range(false);

begin

   exp0  <= ROM(CONV_INTEGER(X(M+R+E-1 downto M+R)));
   under <= under0(CONV_INTEGER(X(M+R+E-1 downto M+R)));
   over  <= over0(CONV_INTEGER(X(M+R+E-1 downto M+R)));

   -- Leading-one detector of digit D0: desp = k, the weight of the number is
   -- 2^k * 64^(E' - bias).
   with X(M+R-1 downto M) select
   desp <= "000" when "000001",
           "001" when "000011"|"000010",
           "010" when "000111"|"000110"|"000101"|"000100",
           "011" when "001111"|"001110"|"001101"|"001100"|"001011"|"001010"|"001001"|"001000",
           "100" when "011111"|"011110"|"011101"|"011100"|"011011"|"011010"|"011001"|"011000"
                     |"010111"|"010110"|"010101"|"010100"|"010011"|"010010"|"010001"|"010000",
           "101" when others;

   -- Right shift of k bits.  After it, the leading one sits just above the
   -- vector (it is the IEEE hidden bit and is dropped), the next 23 bits are
   -- the fraction and the remaining R bits are used for rounding.
   fracX <= X(M+R-1 downto 0) & CONV_STD_LOGIC_VECTOR(0,R-1);

   with CONV_INTEGER(desp) select
      fracdesp <= fracX(M+R-2 downto 0)   when 0,
                  fracX(M+R-1 downto 1)   when 1,
                  fracX(M+R   downto 2)   when 2,
                  fracX(M+R+1 downto 3)   when 3,
                  fracX(M+R+2 downto 4)   when 4,
                  fracX(M+R+3 downto 5)   when others;

   -- Round to nearest, ties to even: round bit and (LSB or sticky).
   stk <= '0' when fracdesp(R-2 downto 0) = CONV_STD_LOGIC_VECTOR(0,R-1) else '1';
   rnd <= fracdesp(R-1) and (fracdesp(R) or stk);

   -- [exponent | fraction] + [k | rounding bit].
   expfracrd <= ('0' & exp0 & fracdesp(M+R-2 downto R))
                + (CONV_STD_LOGIC_VECTOR(0,E-D+1) & desp & CONV_STD_LOGIC_VECTOR(0,22) & rnd);

   -- Overflow: the exponent reached 255 or more.
   inf0 <= '1' when expfracrd(30 downto 23) = "11111111" else '0';
   inf  <= inf0 or expfracrd(31) or over;

   -- Output selection, sel = [exc of X | inf | under].
   sel <= X(2+1+E+M+R-1 downto 1+E+M+R) & inf & under;
   with sel select
   result <= CONV_STD_LOGIC_VECTOR(0,32)                                when "0000"|"0001"|"0010"|"0011"   -- zero
                                                                             |"0101",                      -- underflow
             X(E+M+R) & "11111111" & CONV_STD_LOGIC_VECTOR(0,23)        when "1000"|"1001"|"1010"|"1011"   -- infinity
                                                                             |"0110",                      -- overflow
             X(E+M+R) & "11111111" & '1' & expfracrd(21 downto 0)       when "1100"|"1101"|"1110"|"1111",  -- NaN
             X(E+M+R) & expfracrd(30 downto 0)                          when others;                       -- number

end arch;
