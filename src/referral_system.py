# Copyright (C) 2019, 2020  alfred richardsn
#
# This file is part of TellerBot.
#
# TellerBot is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with TellerBot.  If not, see <https://www.gnu.org/licenses/>.
from decimal import Decimal
from typing import Mapping

PERSONAL_CATEGORY: Mapping[int, int] = {
    1: 1,
    10: 2,
    100: 5,
    1_000: 10,
    10_000: 20,
    100_000: 40,
}

REFERRED_CATEGORY: Mapping[int, int] = {
    5: 1,
    50: 2,
    500: 4,
    5_000: 8,
    50_000: 16,
    500_000: 30,
}

REFERRED_BY_REFERALS_CATEGORY: Mapping[int, int] = {
    100: 1,
    1_000: 2,
    10_000: 4,
    100_000: 8,
    1_000_000: 20,
}


def bonus_coefficient(category: Mapping[int, int], count: int) -> Decimal:
    """Get multiplication coefficient for cashback."""
    assigned_level = 0
    for level, percent in category.items():
        if level <= count and level > assigned_level:
            assigned_level = level
    return Decimal(category[assigned_level]) / 100 if assigned_level > 0 else Decimal(0)
