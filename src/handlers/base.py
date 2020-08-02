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

from src.config import config
from src.escrow import get_escrow_instance

from src.bot import (  # noqa: F401, noreorder
    dp,
    private_handler,
    state_handler,
    state_handlers,
)
from src.bot import tg
from src.database import database, database_user, STATE_KEY
from src.i18n import i18n
from src.money import normalize


def start_keyboard() -> types.ReplyKeyboardMarkup:
    """Create reply keyboard with main menu."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton(emojize(":heavy_plus_sign: ") + i18n("create_order")),
        types.KeyboardButton(emojize(":bust_in_silhouette: ") + i18n("my_orders")),
        types.KeyboardButton(emojize(":closed_book: ") + i18n("order_book")),
        types.KeyboardButton(emojize(":loudspeaker: ") + i18n("referral_link")),
        types.KeyboardButton(emojize(":abcd: ") + i18n("language")),
        types.KeyboardButton(emojize(":question: ") + i18n("support")),
    )
    return keyboard


async def inline_control_buttons(
    back: bool = True, skip: bool = True, cancel: bool = True
) -> typing.List[types.InlineKeyboardButton]:
    """Create inline button row with translated labels to control current state."""
    buttons = []
    if back or skip:
        row = []
        state_name = await dp.current_state().get_state()
        if back:
            row.append(
                types.InlineKeyboardButton(
                    i18n("back"), callback_data=f"state {state_name} back"
                )
            )
        if skip:
            row.append(
                types.InlineKeyboardButton(
                    i18n("skip"), callback_data=f"state {state_name} skip"
                )
            )
        buttons.append(row)
    if cancel:
        buttons.append(
            [types.InlineKeyboardButton(i18n("cancel"), callback_data="cancel")]
        )
    return buttons


async def orders_list(
    cursor: Cursor,
    chat_id: int,
    start: int,
    quantity: int,
    buttons_data: str,
    user_id: typing.Optional[int] = None,
    message_id: typing.Optional[int] = None,
    invert: typing.Optional[bool] = None,
) -> None:
    """Send list of orders.

    :param cursor: Cursor of MongoDB query to orders.
    :param chat_id: Telegram ID of current chat.
    :param start: Start index.
    :param quantity: Quantity of orders in cursor.
    :param buttons_data: Beginning of callback data of left/right buttons.
    :param user_id: Telegram ID of current user if cursor is not user-specific.
    :param message_id: Telegram ID of message to edit.
    :param invert: Invert all prices.
    """
    user = database_user.get()
    if invert is None:
        invert = user.get("invert_book", False)
    else:
        await database.users.update_one(
            {"_id": user["_id"]}, {"$set": {"invert_book": invert}}
        )

    keyboard = types.InlineKeyboardMarkup(row_width=min(config.ORDERS_COUNT // 2, 8))

    inline_orders_buttons = (
        types.InlineKeyboardButton(
            emojize(":arrow_left:"),
            callback_data="{} {} {}".format(
                buttons_data, start - config.ORDERS_COUNT, 1 if invert else 0
            ),
        ),
        types.InlineKeyboardButton(
            emojize(":arrow_right:"),
            callback_data="{} {} {}".format(
                buttons_data, start + config.ORDERS_COUNT, 1 if invert else 0
            ),
        ),
    )

    if quantity == 0:
        keyboard.row(*inline_orders_buttons)
        text = i18n("no_orders")
        if message_id is None:
            await tg.send_message(chat_id, text, reply_markup=keyboard)
        else:
            await tg.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        return

    all_orders = await cursor.to_list(length=start + config.ORDERS_COUNT)
    orders = all_orders[start:]

    lines = []
    buttons = []
    current_time = time()
    for i, order in enumerate(orders):
        line = ""

        if user_id is None:
            if not order.get("archived") and order["expiration_time"] > current_time:
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
            i18n("invert"),
            callback_data="{} {} {}".format(buttons_data, start, int(not invert)),
        )
    )
    keyboard.add(*buttons)
    keyboard.row(*inline_orders_buttons)

    text = (
        "\\["
        + i18n("page {number} {total}").format(
            number=math.ceil(start / config.ORDERS_COUNT) + 1,
            total=math.ceil(quantity / config.ORDERS_COUNT),
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


async def show_order(
    order: typing.Mapping[str, typing.Any],
    chat_id: int,
    user_id: int,
    message_id: typing.Optional[int] = None,
    location_message_id: typing.Optional[int] = None,
    show_id: bool = False,
    invert: typing.Optional[bool] = None,
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
    if locale is None:
        locale = i18n.ctx_locale.get()

    new_edit_msg = None
    if invert is None:
        try:
            user = database_user.get()
        except LookupError:
            user = await database.users.find_one({"id": user_id})
        invert = user.get("invert_order", False)
    else:
        user = await database.users.find_one_and_update(
            {"id": user_id}, {"$set": {"invert_order": invert}}
        )
        if "edit" in user:
            if edit:
                if user["edit"]["field"] == "price":
                    new_edit_msg = i18n(
                        "new_price {of_currency} {per_currency}", locale=locale
                    )
                    if invert:
                        new_edit_msg = new_edit_msg.format(
                            of_currency=order["buy"], per_currency=order["sell"]
                        )
                    else:
                        new_edit_msg = new_edit_msg.format(
                            of_currency=order["sell"], per_currency=order["buy"]
                        )
            elif user["edit"]["order_message_id"] == message_id:
                await tg.delete_message(user["chat"], user["edit"]["message_id"])
                await database.users.update_one(
                    {"_id": user["_id"]}, {"$unset": {"edit": True, STATE_KEY: True}}
                )

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

    if order.get("archived"):
        header += markdown.bold(i18n("archived", locale=locale)) + "\n"

    creator = await database.users.find_one({"id": order["user_id"]})
    header += "{} ({}) ".format(
        markdown.link(creator["mention"], types.User(id=creator["id"]).url),
        markdown.code(creator["id"]),
    )
    if invert:
        act = i18n("sells {sell_currency} {buy_currency}", locale=locale)
    else:
        act = i18n("buys {buy_currency} {sell_currency}", locale=locale)
    header += act.format(buy_currency=order["buy"], sell_currency=order["sell"]) + "\n"

    lines = [header]
    field_names = {
        "sum_buy": i18n("buy_amount", locale=locale),
        "sum_sell": i18n("sell_amount", locale=locale),
        "price": i18n("price", locale=locale),
        "payment_system": i18n("payment_system", locale=locale),
        "duration": i18n("duration", locale=locale),
        "comments": i18n("comments", locale=locale),
    }
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
            i18n("invert", locale=locale),
            callback_data="{} {} {} {}".format(
                "revert" if invert else "invert",
                order["_id"],
                location_message_id,
                int(edit),
            ),
        )
    )

    if edit and creator["id"] == user_id:
        buttons = []
        for i, (field, value) in enumerate(lines_format.items()):
            if value is not None:
                lines.append(f"{i + 1}. {field_names[field]} {value}")
            else:
                lines.append(f"{i + 1}. {field_names[field]} -")
            buttons.append(
                types.InlineKeyboardButton(
                    f"{i + 1}",
                    callback_data="edit {} {} {} 0".format(
                        order["_id"], field, location_message_id
                    ),
                )
            )

        keyboard.add(*buttons)
        keyboard.row(
            types.InlineKeyboardButton(
                i18n("finish", locale=locale),
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
                i18n("similar", locale=locale),
                callback_data="similar {}".format(order["_id"]),
            ),
            types.InlineKeyboardButton(
                i18n("match", locale=locale),
                callback_data="match {}".format(order["_id"]),
            ),
        )

        if creator["id"] == user_id:
            keyboard.row(
                types.InlineKeyboardButton(
                    i18n("edit", locale=locale),
                    callback_data="{} {} {} 1".format(
                        "invert" if invert else "revert",
                        order["_id"],
                        location_message_id,
                    ),
                ),
                types.InlineKeyboardButton(
                    i18n("delete", locale=locale),
                    callback_data="delete {} {}".format(
                        order["_id"], location_message_id
                    ),
                ),
            )
            keyboard.row(
                types.InlineKeyboardButton(
                    i18n("unarchive", locale=locale)
                    if order.get("archived")
                    else i18n("archive", locale=locale),
                    callback_data="archive {} {}".format(
                        order["_id"], location_message_id
                    ),
                ),
                types.InlineKeyboardButton(
                    i18n("change_duration", locale=locale),
                    callback_data="edit {} duration {} 1".format(
                        order["_id"], location_message_id
                    ),
                ),
            )
        elif "price_sell" in order and not order.get("archived"):
            if (
                get_escrow_instance(order["buy"]) is not None
                or get_escrow_instance(order["sell"]) is not None
            ):
                keyboard.row(
                    types.InlineKeyboardButton(
                        i18n("escrow", locale=locale),
                        callback_data="escrow {} sum_buy 0".format(order["_id"]),
                    )
                )

        keyboard.row(
            types.InlineKeyboardButton(
                i18n("hide", locale=locale),
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
        if new_edit_msg is not None:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton(
                    i18n("unset", locale=locale), callback_data="unset"
                )
            )
            await tg.edit_message_text(
                new_edit_msg,
                chat_id,
                user["edit"]["message_id"],
                reply_markup=keyboard,
            )
    else:
        await tg.send_message(
            chat_id,
            answer,
            reply_markup=keyboard,
            parse_mode=types.ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
