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
"""Whitelists for orders."""
from typing import Mapping
from typing import Tuple

from aiogram.types import KeyboardButton
from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.emoji import emojize

from src.i18n import i18n

FIAT: Tuple[str, ...] = ("CNY", "EUR", "RUB", "UAH", "USD")

CRYPTOCURRENCY: Mapping[str, Tuple[str, ...]] = {
    "BTC": ("GDEX", "RUDEX"),
    "BTS": (),
    "CYBER": (),
    "EOS": ("GDEX", "RUDEX"),
    "ETH": ("GDEX", "RUDEX"),
    "GOLOS": ("CYBER",),
    "HIVE": (),
    "STEEM": ("GDEX", "RUDEX"),
    "TRON": (),
    "USDT": ("BTC", "EOS", "ETH", "FINTEH", "GDEX", "RUDEX", "TRON"),
    "VIZ": (),
    "BIP": (),
    "DEC": ("STEEM", "HIVE", "TRON"),
}


def currency_keyboard(currency_type: str) -> ReplyKeyboardMarkup:
    """Get keyboard with currencies from whitelists."""
    keyboard = ReplyKeyboardMarkup(
        row_width=6, one_time_keyboard=currency_type == "sell"
    )
    keyboard.row(*[KeyboardButton(c) for c in FIAT])
    keyboard.add(*[KeyboardButton(c) for c in CRYPTOCURRENCY])
    cancel_button = KeyboardButton(emojize(":x: ") + i18n("cancel"))
    if currency_type == "sell":
        keyboard.row(
            KeyboardButton(emojize(":fast_reverse_button: ") + i18n("back")),
            cancel_button,
        )
    else:
        keyboard.row(cancel_button)
    return keyboard


def gateway_keyboard(currency: str, currency_type: str) -> ReplyKeyboardMarkup:
    """Get keyboard with gateways of ``currency`` from whitelist."""
    keyboard = ReplyKeyboardMarkup(
        row_width=6, one_time_keyboard=currency_type == "sell"
    )
    keyboard.add(*[KeyboardButton(g) for g in CRYPTOCURRENCY[currency]])
    keyboard.row(
        KeyboardButton(emojize(":fast_reverse_button: ") + i18n("back")),
        KeyboardButton(emojize(":fast_forward: ") + i18n("without_gateway")),
        KeyboardButton(emojize(":x: ") + i18n("cancel")),
    )
    return keyboard
