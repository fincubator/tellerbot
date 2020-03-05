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
import re
from decimal import Decimal

from src.i18n import i18n

HIGH_EXP = Decimal("1e15")
LOW_EXP = Decimal("1e-8")


def gateway_currency_regexp(currency):
    """Return regexp that ignores gateway if it isn't specified."""
    return currency if "." in currency else re.compile(fr"^(\w+\.)?{currency}$")


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
        raise MoneyValueError(i18n("send_decimal_number"))
    if money <= 0:
        raise MoneyValueError(i18n("send_positive_number"))
    if money >= HIGH_EXP:
        raise MoneyValueError(
            i18n("exceeded_money_limit {limit}").format(limit=f"{HIGH_EXP:,f}")
        )

    normalized = normalize(money)
    if normalized.is_zero():
        raise MoneyValueError(
            i18n("shortage_money_limit {limit}").format(limit=f"{LOW_EXP:.8f}")
        )
    return normalized


class MoneyValueError(Exception):
    """Inappropriate money argument value."""
