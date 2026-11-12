--------------------------------------------------------------------------------
-- File    : sOR.vhd
-- Project : high-radix-fp-fpga
--
-- Entity:
--   sOR - OR of all the bits of a vector
--
-- Purpose:
--   S = '1' if any bit of A is '1'.  Used for the sticky bits and for the
--   zero detection of digits.  It is written as a chain (S(i) = S(i-1) or
--   A(i)) so that the synthesis tool can map it onto the fast carry logic
--   of the FPGA.
--
-- Generics:
--   N : width of A.
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

entity sOR is
   generic ( N : natural := 24 );
   port ( A : in  std_logic_vector(N-1 downto 0);
          S : out std_logic );
end sOR;

architecture Behavioral of sOR is
   signal stemp : std_logic_vector(N-1 downto 0);   -- stemp(i) = OR of A(i downto 0)
begin

   stemp(0) <= A(0);
   chain : for i in 1 to N-1 generate
   begin
      stemp(i) <= stemp(i-1) or A(i);
   end generate;
   S <= stemp(N-1);

end Behavioral;
