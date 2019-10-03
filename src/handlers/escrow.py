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


import asyncio
import functools
from typing import Any, Mapping
import string

from bson.objectid import ObjectId
from bson.decimal128 import Decimal128

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from aiogram.dispatcher import FSMContext
from aiogram.utils import markdown

from . import tg, dp, private_handler, show_order, validate_money, start_keyboard
from ..database import database
from ..escrow import ESCROW_CRYPTO_ADDRESS
from ..i18n import _
from .. import states
from ..utils import normalize_money, MoneyValidationError


def escrow_callback_handler(handler):
    async def decorator(call: types.CallbackQuery):
        offer_id = call.data.split()[1]
        offer = await database.escrow.find_one({'_id': ObjectId(offer_id)})

        if not offer:
            await call.answer(_('Offer is not found.'))
            return

        return await handler(call, offer)
    return decorator


def escrow_message_handler(handler):
    async def decorator(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        offer = await database.escrow.find_one(
            {'$or': [{'init_id': user_id}, {'counter_id': user_id}]}
        )
        if not offer:
            await tg.send_message(message.chat.id, _('Offer is not found.'))
            return

        return await handler(message, state, offer)
    return decorator


@private_handler(state=states.Escrow.sum)
@escrow_message_handler
async def set_escrow_sum(message: types.Message, state: FSMContext, offer: Mapping[str, Any]):
    try:
        escrow_sum = await validate_money(message.text, message.chat.id)
    except MoneyValidationError as exception:
        await tg.send_message(message.chat.id, str(exception))
        return

    order = await database.orders.find_one({'_id': offer['order']})
    sum_field = 'sum_' + offer['sum_currency']
    order_sum = order.get(sum_field)
    if order_sum and escrow_sum > order_sum.to_decimal():
        await tg.send_message(
            message.chat.id,
            _("Send number not exceeding order's sum.")
        )
        return

    update_dict = {sum_field: Decimal128(escrow_sum)}
    new_sum_currency = 'sell' if offer['sum_currency'] == 'buy' else 'buy'
    update_dict['sum_' + new_sum_currency] = Decimal128(normalize_money(
        escrow_sum * order['price_' + new_sum_currency].to_decimal()
    ))

    await database.escrow.update_one(
        {'_id': offer['_id']},
        {'$set': update_dict}
    )
    await tg.send_message(
        message.chat.id,
        _('Send your {} address.').format(offer['sell'])
    )
    await states.Escrow.init_address.set()


@private_handler(state=states.Escrow.init_address)
@escrow_message_handler
async def set_init_address(message: types.Message, state: FSMContext, offer: Mapping[str, Any]):
    if len(message.text) > 35 or not all(ch in string.ascii_letters + string.digits for ch in message.text):
        await tg.send_message(message.chat.id, _('Address is invalid.'))
        return

    await database.escrow.update_one(
        {'_id': offer['_id']},
        {'$set': {'init_address': message.text}}
    )
    order = await database.orders.find_one({'_id': offer['order']})
    await show_order(
        order, offer['counter_id'], offer['counter_id'],
        show_id=True
    )
    counter_keyboard = InlineKeyboardMarkup()
    counter_keyboard.add(
        InlineKeyboardButton(_('Accept'), callback_data='accept {}'.format(offer['_id'])),
        InlineKeyboardButton(_('Decline'), callback_data='decline {}'.format(offer['_id']))
    )
    await tg.send_message(
        offer['counter_id'],
        _('You got an escrow offer to sell {} {} for {} {}.').format(
            offer['sum_sell'], offer['sell'],
            offer['sum_buy'], offer['buy']
        ),
        reply_markup=counter_keyboard
    )
    answer = _('Offer sent.')
    message = await tg.send_message(message.from_user.id, answer)
    init_keyboard = InlineKeyboardMarkup()
    init_keyboard.add(InlineKeyboardButton(
        _('Cancel'), callback_data='escrow_cancel {}'.format(offer['_id'])
    ))
    partial_edit = functools.partial(
        tg.edit_message_reply_markup, message.chat.id, message.message_id,
        reply_markup=init_keyboard
    )
    asyncio.get_running_loop().call_later(3600, partial_edit)
    await state.finish()


@dp.callback_query_handler(lambda call: call.data.startswith('accept '))
@escrow_callback_handler
async def accept_offer(call: types.CallbackQuery, offer: Mapping[str, Any]):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton(
        _('Cancel'), callback_data='escrow_cancel {}'.format(offer['_id'])
    ))
    await tg.send_message(
        offer['init_id'],
        _('Your escrow offer was accepted.') + ' ' +
        _("I'll notify you when transaction is complete."),
        reply_markup=keyboard
    )
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _('Send your {} address.').format(offer['buy'])
    )
    await states.Escrow.counter_address.set()


@dp.callback_query_handler(lambda call: call.data.startswith('decline '))
@escrow_callback_handler
async def decline_offer(call: types.CallbackQuery, offer: Mapping[str, Any]):
    await database.escrow.delete_one({'_id': offer['_id']})
    await tg.send_message(offer['init_id'], _('Your escrow offer was declined.'))
    await call.answer()
    await tg.send_message(call.message.chat.id, _('Offer was declined.'))


@private_handler(state=states.Escrow.counter_address)
@escrow_message_handler
async def set_counter_address(message: types.Message, state: FSMContext, offer: Mapping[str, Any]):
    if len(message.text) > 35 or not all(ch in string.ascii_letters + string.digits for ch in message.text):
        await tg.send_message(message.chat.id, _('Address is invalid.'))
        return

    await database.escrow.update_one(
        {'_id': offer['_id']},
        {'$set': {'counter_address': message.text}}
    )
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Sent'), callback_data='sent {}'.format(offer['_id'])
        ),
        InlineKeyboardButton(
            _('Cancel'), callback_data='escrow_cancel {}'.format(offer['_id'])
        )
    )
    memo = markdown.code(
        'escrow for', offer['sum_buy'], offer['buy'], 'to', offer['init_address']
    )
    escrow_currency = offer['escrow_currency']
    escrow_address = markdown.bold(ESCROW_CRYPTO_ADDRESS[offer[escrow_currency]])
    if escrow_currency == 'buy':
        escrow_id = offer['init_id']
        send_reply = True
    elif escrow_currency == 'sell':
        escrow_id = offer['counter_id']
        send_reply = False

    await tg.send_message(
        escrow_id,
        _('Send {} {} to address {} with memo:').format(
            offer[f'sum_{escrow_currency}'], offer[escrow_currency], escrow_address
        ) + '\n' + memo,
        reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )
    if send_reply:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(
            _('Cancel'), callback_data='escrow_cancel {}'.format(offer['_id'])
        ))
        await tg.send_message(
            message.chat.id,
            _('Transfer information sent.') + ' ' +
            _("I'll notify you when transaction is complete."),
            reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
    other_state = FSMContext(dp.storage, escrow_id, escrow_id)
    await states.Escrow.transfer.set()
    await other_state.set_state(states.Escrow.transfer)


@dp.callback_query_handler(lambda call: call.data.startswith('escrow_cancel '), state=states.Escrow.transfer)
@escrow_callback_handler
async def cancel_offer(call: types.CallbackQuery, offer: Mapping[str, Any]):
    answer = _('Escrow was cancelled.')
    await database.escrow.delete_one({'_id': offer['_id']})
    await call.answer()
    await tg.send_message(offer['init_id'], answer, reply_markup=start_keyboard())
    await tg.send_message(offer['counter_id'], answer, reply_markup=start_keyboard())
    init_state = FSMContext(dp.storage, offer['init_id'], offer['init_id'])
    counter_state = FSMContext(dp.storage, offer['counter_id'], offer['counter_id'])
    await init_state.finish()
    await counter_state.finish()


@dp.callback_query_handler(lambda call: call.data.startswith('sent '), state=states.Escrow.transfer)
@escrow_callback_handler
async def sent_confirmation(call: types.CallbackQuery, offer: Mapping[str, Any]):
    await call.answer('Not implemented yet.')
