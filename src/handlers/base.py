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
import math
import typing
from datetime import datetime
from decimal import Decimal
from time import time

from aiogram import types
from aiogram.utils import markdown
from aiogram.utils.emoji import emojize
from pymongo.cursor import Cursor

from src.config import Config
from src.escrow import get_escrow_instance

from src.bot import (  # noqa: F401, noreorder
    dp,
    private_handler,
    state_handler,
    state_handlers,
)
from src.bot import tg
from src.database import database
from src.i18n import _
from src.money import normalize


def help_message() -> str:
    """Translate initial greeting message."""
    return _(
        "Hello, I'm TellerBot. "
        "I can help you meet with people that you can swap money with.\n\n"
        "Choose one of the options on your keyboard."
    )


def start_keyboard() -> types.ReplyKeyboardMarkup:
    """Create reply keyboard with main menu."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton(emojize(":heavy_plus_sign: ") + _("Create order")),
        types.KeyboardButton(emojize(":bust_in_silhouette: ") + _("My orders")),
        types.KeyboardButton(emojize(":closed_book: ") + _("Order book")),
        types.KeyboardButton(emojize(":abcd: ") + _("Language")),
        types.KeyboardButton(emojize(":question: ") + _("Support")),
    )
    return keyboard


async def inline_control_buttons(
    back: bool = True, skip: bool = True
) -> typing.List[types.InlineKeyboardButton]:
    """Create inline button row with translated labels to control current state."""
    buttons = []
    if back or skip:
        row = []
        state_name = await dp.current_state().get_state()
        if back:
            row.append(
                types.InlineKeyboardButton(
                    _("Back"), callback_data=f"state {state_name} back"
                )
            )
        if skip:
            row.append(
                types.InlineKeyboardButton(
                    _("Skip"), callback_data=f"state {state_name} skip"
                )
            )
        buttons.append(row)
    return buttons


async def orders_list(
    cursor: Cursor,
    chat_id: int,
    start: int,
    quantity: int,
    buttons_data: str,
    user_id: typing.Optional[int] = None,
    message_id: typing.Optional[int] = None,
    invert: bool = False,
) -> None:
    """Send list of orders.

    :param cursor: Cursor of MongoDB query to orders.
    :param chat_id: Telegram ID of current chat.
    :param start: Start index.
    :param quantity: Quantity of orders in cursor.
    :param buttons_data: Beginning of callback data of left/right buttons.
    :param user_id: If cursor is user-specific, Telegram ID of user
        who created all orders in cursor.
    :param message_id: Telegram ID of message to edit.
    :param invert: Invert all prices.
    """
    keyboard = types.InlineKeyboardMarkup(row_width=min(Config.ORDERS_COUNT // 2, 8))

    inline_orders_buttons = (
        types.InlineKeyboardButton(
            emojize(":arrow_left:"),
            callback_data="{} {} {}".format(
                buttons_data, start - Config.ORDERS_COUNT, int(invert)
            ),
        ),
        types.InlineKeyboardButton(
            emojize(":arrow_right:"),
            callback_data="{} {} {}".format(
                buttons_data, start + Config.ORDERS_COUNT, int(invert)
            ),
        ),
    )

    if quantity == 0:
        keyboard.row(*inline_orders_buttons)
        text = _("There are no orders.")
        if message_id is None:
            await tg.send_message(chat_id, text, reply_markup=keyboard)
        else:
            await tg.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        return

    all_orders = await cursor.to_list(length=start + Config.ORDERS_COUNT)
    orders = all_orders[start:]

    lines = []
    buttons = []
    current_time = time()
    for i, order in enumerate(orders):
        line = ""

        if user_id is None:
            if (
                "expiration_time" not in order
                or order["expiration_time"] > current_time
            ):
                line += emojize(":arrow_forward: ")
            else:
                line += emojize(":pause_button: ")

        exp = Decimal("1e-5")

        if "sum_sell" in order:
            line += "{:,} ".format(normalize(order["sum_sell"].to_decimal(), exp))
        line += "{} → ".format(order["sell"])

        if "sum_buy" in order:
            line += "{:,} ".format(normalize(order["sum_buy"].to_decimal(), exp))
        line += order["buy"]

        if "price_sell" in order:
            if invert:
                line += " ({:,} {}/{})".format(
                    normalize(order["price_buy"].to_decimal(), exp),
                    order["buy"],
                    order["sell"],
                )
            else:
                line += " ({:,} {}/{})".format(
                    normalize(order["price_sell"].to_decimal(), exp),
                    order["sell"],
                    order["buy"],
                )

        if user_id is not None and order["user_id"] == user_id:
            line = f"*{line}*"

        lines.append(f"{i + 1}. {line}")
        buttons.append(
            types.InlineKeyboardButton(
                "{}".format(i + 1), callback_data="get_order {}".format(order["_id"])
            )
        )

    keyboard.row(
        types.InlineKeyboardButton(
            _("Invert"),
            callback_data="{} {} {}".format(buttons_data, start, int(not invert)),
        )
    )
    keyboard.add(*buttons)
    keyboard.row(*inline_orders_buttons)

    text = (
        "\\["
        + _("Page {} of {}").format(
            math.ceil(start / Config.ORDERS_COUNT) + 1,
            math.ceil(quantity / Config.ORDERS_COUNT),
        )
        + "]\n"
        + "\n".join(lines)
    )

    if message_id is None:
        await tg.send_message(
            chat_id,
            text,
            reply_markup=keyboard,
            parse_mode=types.ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    else:
        await tg.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=keyboard,
            parse_mode=types.ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )


def get_order_field_names():
    """Get translated names of order fields."""
    return {
        "sum_buy": _("Amount of buying:"),
        "sum_sell": _("Amount of selling:"),
        "price": _("Price:"),
        "payment_system": _("Payment system:"),
        "duration": _("Duration:"),
        "comments": _("Comments:"),
    }


async def show_order(
    order: typing.Mapping[str, typing.Any],
    chat_id: int,
    user_id: int,
    message_id: typing.Optional[int] = None,
    location_message_id: typing.Optional[int] = None,
    show_id: bool = False,
    invert: bool = False,
    edit: bool = False,
    locale: typing.Optional[str] = None,
):
    """Send detailed order.

    :param order: Order document.
    :param chat_id: Telegram ID of chat to send message to.
    :param user_id: Telegram user ID of message receiver.
    :param message_id: Telegram ID of message to edit.
    :param location_message_id: Telegram ID of message with location object.
        It is deleted when **Hide** inline button is pressed.
    :param show_id: Add ID of order to the top.
    :param invert: Invert price.
    :param edit: Enter edit mode.
    :param locale: Locale of message receiver.
    """
    if location_message_id is None:
        if order.get("lat") is not None and order.get("lon") is not None:
            location_message = await tg.send_location(
                chat_id, order["lat"], order["lon"]
            )
            location_message_id = location_message.message_id
        else:
            location_message_id = -1

    header = ""
    if show_id:
        header += "ID: {}\n".format(markdown.code(order["_id"]))

    creator = await database.users.find_one({"id": order["user_id"]})
    header += "{} ({}) ".format(
        markdown.link(creator["mention"], types.User(id=creator["id"]).url),
        markdown.code(creator["id"]),
    )
    if invert:
        header += _("sells {} for {}", locale=locale).format(
            order["sell"], order["buy"]
        )
    else:
        header += _("buys {} for {}", locale=locale).format(order["buy"], order["sell"])
    header += "\n"

    lines = [header]
    field_names = get_order_field_names()
    lines_format: typing.Dict[str, typing.Optional[str]] = {}
    for name in field_names:
        lines_format[name] = None

    if "sum_buy" in order:
        lines_format["sum_buy"] = "{} {}".format(order["sum_buy"], order["buy"])
    if "sum_sell" in order:
        lines_format["sum_sell"] = "{} {}".format(order["sum_sell"], order["sell"])
    if "price_sell" in order:
        if invert:
            lines_format["price"] = "{} {}/{}".format(
                order["price_buy"], order["buy"], order["sell"]
            )
        else:
            lines_format["price"] = "{} {}/{}".format(
                order["price_sell"], order["sell"], order["buy"]
            )
    if "payment_system" in order:
        lines_format["payment_system"] = order["payment_system"]
    if "duration" in order:
        lines_format["duration"] = "{} - {}".format(
            datetime.utcfromtimestamp(order["start_time"]).strftime("%d.%m.%Y"),
            datetime.utcfromtimestamp(order["expiration_time"]).strftime("%d.%m.%Y"),
        )
    if "comments" in order:
        lines_format["comments"] = "«{}»".format(order["comments"])

    keyboard = types.InlineKeyboardMarkup(row_width=6)

    keyboard.row(
        types.InlineKeyboardButton(
            _("Invert", locale=locale),
            callback_data="{} {} {} {}".format(
                "revert" if invert else "invert",
                order["_id"],
                location_message_id,
                int(edit),
            ),
        )
    )

    if edit:
        buttons = []
        for i, (field, value) in enumerate(lines_format.items()):
            if value is not None:
                lines.append(f"{i + 1}. {field_names[field]} {value}")
            elif edit:
                lines.append(f"{i + 1}. {field_names[field]} -")
            buttons.append(
                types.InlineKeyboardButton(
                    f"{i + 1}",
                    callback_data="edit {} {} {} {}".format(
                        order["_id"], field, location_message_id, int(invert)
                    ),
                )
            )

        keyboard.add(*buttons)
        keyboard.row(
            types.InlineKeyboardButton(
                _("Finish", locale=locale),
                callback_data="{} {} {} 0".format(
                    "invert" if invert else "revert", order["_id"], location_message_id
                ),
            )
        )

    else:
        for field, value in lines_format.items():
            if value is not None:
                lines.append(field_names[field] + " " + value)

        keyboard.row(
            types.InlineKeyboardButton(
                _("Similar", locale=locale),
                callback_data="similar {}".format(order["_id"]),
            ),
            types.InlineKeyboardButton(
                _("Match", locale=locale), callback_data="match {}".format(order["_id"])
            ),
        )

        if creator["id"] == user_id:
            keyboard.row(
                types.InlineKeyboardButton(
                    _("Edit", locale=locale),
                    callback_data="{} {} {} 1".format(
                        "invert" if invert else "revert",
                        order["_id"],
                        location_message_id,
                    ),
                ),
                types.InlineKeyboardButton(
                    _("Delete", locale=locale),
                    callback_data="delete {} {}".format(
                        order["_id"], location_message_id
                    ),
                ),
            )
        elif "price_sell" in order:
            if (
                get_escrow_instance(order["buy"]) is not None
                or get_escrow_instance(order["sell"]) is not None
            ):
                keyboard.row(
                    types.InlineKeyboardButton(
                        _("Escrow", locale=locale),
                        callback_data="escrow {} sum_buy 0".format(order["_id"]),
                    )
                )

        keyboard.row(
            types.InlineKeyboardButton(
                _("Hide", locale=locale),
                callback_data="hide {}".format(location_message_id),
            )
        )

    answer = "\n".join(lines)

    if message_id is not None:
        await tg.edit_message_text(
            answer,
            chat_id,
            message_id,
            reply_markup=keyboard,
            parse_mode=types.ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    else:
        await tg.send_message(
            chat_id,
            answer,
            reply_markup=keyboard,
            parse_mode=types.ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
