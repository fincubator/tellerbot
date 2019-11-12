# Copyright (C) 2019  alfred richardsn
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
import decimal
from decimal import Decimal

from src.i18n import _

HIGH_EXP = Decimal("1e15")
LOW_EXP = Decimal("1e-8")


def normalize(money: Decimal, exp: Decimal = LOW_EXP) -> Decimal:
    """Round ``money`` to ``exp`` and strip trailing zeroes."""
    if money == money.to_integral_value():
        return money.quantize(Decimal(1))
    return money.quantize(exp, rounding=decimal.ROUND_HALF_UP).normalize()


def money(value) -> Decimal:
    """Try to return normalized money object constructed from ``value``."""
    try:
        money = Decimal(value)
    except decimal.InvalidOperation:
        raise MoneyValueError(_("Send decimal number."))
    if money <= 0:
        raise MoneyValueError(_("Send positive number."))
    if money >= HIGH_EXP:
        raise MoneyValueError(_("Send number less than") + f" {HIGH_EXP:,f}")

    normalized = normalize(money)
    if normalized.is_zero():
        raise MoneyValueError(_("Send number greater than") + f" {LOW_EXP:.8f}")
    return normalized


class MoneyValueError(Exception):
    """Inappropriate money argument value."""
