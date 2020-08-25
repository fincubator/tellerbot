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
"""Handlers for cashback."""
import pymongo
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import any_state
from aiogram.types import InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup
from aiogram.types import KeyboardButton
from aiogram.types import ParseMode
from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils import markdown

from src import states
from src.bot import dp
from src.bot import tg
from src.database import database
from src.escrow import get_escrow_instance
from src.escrow.blockchain import TransferError
from src.handlers.base import private_handler
from src.handlers.base import start_keyboard
from src.i18n import i18n


@dp.callback_query_handler(
    lambda call: call.data.startswith("claim_currency "), state=any_state
)
async def claim_currency(call: types.CallbackQuery):
    """Set cashback currency and suggest last escrow address."""
    currency = call.data.split()[1]
    cursor = (
        database.cashback.find(
            {"id": call.from_user.id, "currency": currency, "address": {"$ne": None}}
        )
        .sort("time", pymongo.DESCENDING)
        .limit(1)
    )
    last_cashback = await cursor.to_list(length=1)
    if last_cashback:
        address = last_cashback[0]["address"]
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton(
                i18n("confirm_cashback_address"),
                callback_data=f"claim_transfer {currency} {address}",
            ),
            InlineKeyboardButton(
                i18n("custom_cashback_address"),
                callback_data=f"custom_cashback_address {currency}",
            ),
        )
        await call.answer()
        await tg.edit_message_text(
            i18n("use_cashback_address {address}").format(
                address=markdown.code(address)
            ),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        return await custom_cashback_address(call)


@dp.callback_query_handler(
    lambda call: call.data.startswith("custom_cashback_address "), state=any_state
)
async def custom_cashback_address(call: types.CallbackQuery):
    """Ask for a custom cashback address."""
    currency = call.data.split()[1]
    await states.cashback_address.set()
    await dp.current_state().update_data(currency=currency)
    answer = i18n("send_cashback_address")
    cursor = database.cashback.find(
        {"id": call.from_user.id, "currency": currency, "address": {"$ne": None}}
    ).sort("time", pymongo.DESCENDING)
    addresses = await cursor.distinct("address")
    addresses = addresses[1:]
    await call.answer()
    if addresses:
        keyboard = ReplyKeyboardMarkup(row_width=1)
        keyboard.add(*[KeyboardButton(address) for address in addresses])
        await tg.send_message(call.message.chat.id, answer, reply_markup=keyboard)
    else:
        await tg.send_message(call.message.chat.id, answer)


async def transfer_cashback(user_id: int, currency: str, address: str):
    """Transfer ``currency`` cashback of user ``user_id`` to ``address``."""
    cursor = database.cashback.aggregate(
        [
            {"$match": {"id": user_id, "currency": currency}},
            {"$group": {"_id": None, "amount": {"$sum": "$amount"}}},
        ]
    )
    amount_document = await cursor.to_list(length=1)
    try:
        result = await get_escrow_instance(currency).transfer(
            address,
            amount_document[0]["amount"].to_decimal(),
            currency,
            memo="cashback for using escrow service on https://t.me/TellerBot",
        )
    except Exception as error:
        raise error
    else:
        await database.cashback.delete_many({"id": user_id, "currency": currency})
        return result


@private_handler(state=states.cashback_address)
async def claim_transfer_custom_address(message: types.Message, state: FSMContext):
    """Transfer cashback to custom address."""
    data = await state.get_data()
    await tg.send_message(message.chat.id, i18n("claim_transfer_wait"))
    try:
        trx_url = await transfer_cashback(
            message.from_user.id, data["currency"], message.text
        )
    except TransferError:
        await tg.send_message(message.chat.id, i18n("cashback_transfer_error"))
    else:
        await tg.send_message(
            message.chat.id,
            markdown.link(i18n("cashback_transferred"), trx_url),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=start_keyboard(),
        )


@dp.callback_query_handler(
    lambda call: call.data.startswith("claim_transfer "), state=any_state
)
@dp.async_task
async def claim_transfer(call: types.CallbackQuery):
    """Transfer cashback to suggested address."""
    _, currency, address = call.data.split()
    await call.answer(i18n("claim_transfer_wait"), show_alert=True)
    try:
        trx_url = await transfer_cashback(call.from_user.id, currency, address)
    except TransferError:
        await tg.send_message(
            call.message.chat.id,
            i18n("cashback_transfer_error"),
            reply_markup=start_keyboard(),
        )
    else:
        await tg.send_message(
            call.message.chat.id,
            markdown.link(i18n("cashback_transferred"), trx_url),
            reply_markup=start_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
