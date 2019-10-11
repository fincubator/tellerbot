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
from config import SUPPORT_CHAT_ID
from decimal import Decimal
import functools
from time import time
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
from ..escrow import get_escrow_instance
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
            {'$or': [{'sell_id': user_id}, {'buy_id': user_id}]}
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
    update_dict[f'sum_{new_sum_currency}'] = Decimal128(normalize_money(
        escrow_sum * order[f'price_{new_sum_currency}'].to_decimal()
    ))
    escrow_currency = offer['escrow_currency']
    escrow_sum = update_dict[f'sum_{escrow_currency}']
    update_dict['sum_fee_up'] = Decimal128(normalize_money(
        escrow_sum.to_decimal() * Decimal('1.05')
    ))
    update_dict['sum_fee_down'] = Decimal128(normalize_money(
        escrow_sum.to_decimal() * Decimal('0.95')
    ))

    await database.escrow.update_one(
        {'_id': offer['_id']},
        {'$set': update_dict}
    )
    answer = _('Do you agree to pay a fee of 5%?') + ' '
    if escrow_currency == 'buy':
        answer += _("(You'll pay {} {})")
        sum_fee_field = 'sum_fee_up'
    elif escrow_currency == 'sell':
        answer += _("(You'll get {} {})")
        sum_fee_field = 'sum_fee_down'
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Yes'), callback_data='sell_accept_fee {} {}'.format(offer['_id'], sum_fee_field)
        ),
        InlineKeyboardButton(
            _('No'), callback_data='sell_decline_fee {} {}'.format(offer['_id'], sum_fee_field)
        )
    )
    answer = answer.format(update_dict[sum_fee_field], offer[escrow_currency])
    await tg.send_message(message.chat.id, answer, reply_markup=keyboard)
    await states.Escrow.sell_fee.set()


@dp.callback_query_handler(lambda call: call.data.startswith('sell_accept_fee '), state=states.Escrow.sell_fee)
@escrow_callback_handler
async def sell_pay_fee(call: types.CallbackQuery, offer: Mapping[str, Any]):
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _('Send your {} address.').format(offer['sell'])
    )
    await states.Escrow.sell_address.set()


@dp.callback_query_handler(lambda call: call.data.startswith('sell_decline_fee '), state=states.Escrow.sell_fee)
@escrow_callback_handler
async def sell_decline_fee(call: types.CallbackQuery, offer: Mapping[str, Any]):
    sum_fee_field = call.data.split()[2]
    await database.escrow.update_one(
        {'_id': offer['_id']},
        {'$set': {sum_fee_field: offer['sum_' + offer['escrow_currency']]}}
    )
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _('Send your {} address.').format(offer['sell'])
    )
    await states.Escrow.sell_address.set()


@private_handler(state=states.Escrow.sell_address)
@escrow_message_handler
async def set_sell_address(message: types.Message, state: FSMContext, offer: Mapping[str, Any]):
    if len(message.text) > 35 or not all(ch in string.ascii_letters + string.digits for ch in message.text):
        await tg.send_message(message.chat.id, _('Address is invalid.'))
        return

    await database.escrow.update_one(
        {'_id': offer['_id']},
        {'$set': {'sell_address': message.text}}
    )
    order = await database.orders.find_one({'_id': offer['order']})
    await show_order(
        order, offer['buy_id'], offer['buy_id'],
        show_id=True
    )
    locale = offer['locale_{}'.format(offer['buy_id'])]
    buy_keyboard = InlineKeyboardMarkup()
    buy_keyboard.add(
        InlineKeyboardButton(
            _('Accept', locale=locale), callback_data='accept {}'.format(offer['_id'])
        ),
        InlineKeyboardButton(
            _('Decline', locale=locale), callback_data='decline {}'.format(offer['_id'])
        )
    )
    await tg.send_message(
        offer['buy_id'],
        _('You got an escrow offer to sell {} {} for {} {}.', locale=locale).format(
            offer['sum_sell'], offer['sell'],
            offer['sum_buy'], offer['buy']
        ),
        reply_markup=buy_keyboard
    )
    answer = _('Offer sent.')
    reply = await tg.send_message(message.from_user.id, answer)
    sell_keyboard = InlineKeyboardMarkup()
    sell_keyboard.add(InlineKeyboardButton(
        _('Cancel'), callback_data='escrow_cancel {}'.format(offer['_id'])
    ))
    partial_edit = functools.partial(
        tg.edit_message_reply_markup, message.chat.id, reply.message_id,
        reply_markup=sell_keyboard
    )
    asyncio.get_running_loop().call_later(60 * 60, partial_edit)
    await state.finish()


@dp.callback_query_handler(lambda call: call.data.startswith('accept '))
@escrow_callback_handler
async def accept_offer(call: types.CallbackQuery, offer: Mapping[str, Any]):
    locale = offer['locale_{}'.format(offer['sell_id'])]
    sell_keyboard = InlineKeyboardMarkup()
    sell_keyboard.add(InlineKeyboardButton(
        _('Cancel', locale=locale), callback_data='escrow_cancel {}'.format(offer['_id'])
    ))
    await tg.send_message(
        offer['sell_id'],
        _('Your escrow offer was accepted.', locale=locale) + ' ' +
        _("I'll notify you when transaction is complete.", locale=locale),
        reply_markup=sell_keyboard
    )
    await call.answer()

    await database.escrow.update_one(
        {'_id': offer['_id']},
        {'$set': {'react_time': time()}},
    )
    answer = _('Do you agree to pay a fee of 5%?') + ' '
    escrow_currency = offer['escrow_currency']
    if escrow_currency == 'buy':
        answer += _("(You'll get {} {})")
        sum_fee_field = 'sum_fee_down'
    elif escrow_currency == 'sell':
        answer += _("(You'll pay {} {})")
        sum_fee_field = 'sum_fee_up'
    answer = answer.format(offer[sum_fee_field], offer[escrow_currency])
    buy_keyboard = InlineKeyboardMarkup()
    buy_keyboard.add(
        InlineKeyboardButton(
            _('Yes'), callback_data='buy_accept_fee {} {}'.format(offer['_id'], sum_fee_field)
        ),
        InlineKeyboardButton(
            _('No'), callback_data='buy_decline_fee {} {}'.format(offer['_id'], sum_fee_field)
        )
    )
    await tg.send_message(call.message.chat.id, answer, reply_markup=buy_keyboard)
    await states.Escrow.buy_fee.set()


@dp.callback_query_handler(lambda call: call.data.startswith('decline '))
@escrow_callback_handler
async def decline_offer(call: types.CallbackQuery, offer: Mapping[str, Any]):
    offer['react_time'] = time()
    await database.escrow_archive.insert_one(offer)
    await database.escrow.delete_one({'_id': offer['_id']})
    await tg.send_message(
        offer['sell_id'],
        _('Your escrow offer was declined.',
          locale=offer['locale_{}'.format(offer['sell_id'])])
    )
    await call.answer()
    await tg.send_message(call.message.chat.id, _('Offer was declined.'))


@dp.callback_query_handler(lambda call: call.data.startswith('buy_accept_fee '), state=states.Escrow.buy_fee)
@escrow_callback_handler
async def buy_pay_fee(call: types.CallbackQuery, offer: Mapping[str, Any]):
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _('Send your {} address.').format(offer['buy'])
    )
    await states.Escrow.buy_address.set()


@dp.callback_query_handler(lambda call: call.data.startswith('buy_decline_fee '), state=states.Escrow.buy_fee)
@escrow_callback_handler
async def buy_decline_fee(call: types.CallbackQuery, offer: Mapping[str, Any]):
    sum_fee_field = call.data.split()[2]
    await database.escrow.update_one(
        {'_id': offer['_id']},
        {'$set': {sum_fee_field: offer['sum_' + offer['escrow_currency']]}}
    )
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _('Send your {} address.').format(offer['buy'])
    )
    await states.Escrow.buy_address.set()


@private_handler(state=states.Escrow.buy_address)
@escrow_message_handler
async def set_buy_address(message: types.Message, state: FSMContext, offer: Mapping[str, Any]):
    if len(message.text) > 35 or not all(ch in string.ascii_letters + string.digits for ch in message.text):
        await tg.send_message(message.chat.id, _('Address is invalid.'))
        return

    escrow_currency = offer['escrow_currency']
    if escrow_currency == 'buy':
        escrow_id = offer['sell_id']
        memo_address = offer['sell_address']
        send_reply = True
    elif escrow_currency == 'sell':
        escrow_id = offer['buy_id']
        memo_address = message.text
        send_reply = False

    memo = 'escrow for {} {} to {}'.format(
        offer['sum_buy'], offer['buy'], memo_address
    )
    await database.escrow.update_one(
        {'_id': offer['_id']},
        {'$set': {
            'buy_address': message.text,
            'memo': memo
        }}
    )
    locale = offer['locale_{}'.format(escrow_id)]
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Sent', locale=locale), callback_data='escrow_sent {}'.format(offer['_id'])
        ),
        InlineKeyboardButton(
            _('Cancel', locale=locale), callback_data='escrow_cancel {}'.format(offer['_id'])
        )
    )
    escrow_address = markdown.bold(get_escrow_instance(offer[escrow_currency]).address)
    await state.finish()
    await tg.send_message(
        escrow_id,
        _('Send {} {} to address {}', locale=locale).format(
            offer['sum_fee_up'], offer[escrow_currency], escrow_address
        ) + ' ' + _('with memo', locale=locale) + ':\n' + markdown.code(memo),
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


@dp.callback_query_handler(lambda call: call.data.startswith('escrow_cancel '))
@escrow_callback_handler
async def cancel_offer(call: types.CallbackQuery, offer: Mapping[str, Any]):
    if offer['stage'] == 'confirmed':
        await call.answer(_("You can't cancel escrow on this stage."))
        return

    sell_answer = _('Escrow was cancelled.',
                    locale=offer['locale_{}'.format(offer['sell_id'])])
    buy_answer = _('Escrow was cancelled.',
                   locale=offer['locale_{}'.format(offer['buy_id'])])
    offer['cancel_time'] = time()
    await database.escrow_archive.insert_one(offer)
    await database.escrow.delete_one({'_id': offer['_id']})
    await call.answer()
    await tg.send_message(offer['sell_id'], sell_answer, reply_markup=start_keyboard())
    await tg.send_message(offer['buy_id'], buy_answer, reply_markup=start_keyboard())
    sell_state = FSMContext(dp.storage, offer['sell_id'], offer['sell_id'])
    buy_state = FSMContext(dp.storage, offer['buy_id'], offer['buy_id'])
    await sell_state.finish()
    await buy_state.finish()


@dp.callback_query_handler(lambda call: call.data.startswith('escrow_sent '))
@escrow_callback_handler
async def escrow_sent_confirmation(call: types.CallbackQuery, offer: Mapping[str, Any]):
    escrow_currency = offer['escrow_currency']

    if escrow_currency == 'buy':
        memo_address = offer['sell_address']
        other_id = offer['buy_id']
        new_currency = 'sell'
    elif escrow_currency == 'sell':
        memo_address = offer['buy_address']
        other_id = offer['sell_id']
        new_currency = 'buy'

    escrow_object = get_escrow_instance(offer[escrow_currency])
    trx = await escrow_object.get_transaction(
        offer['sum_fee_up'].to_decimal(), offer[escrow_currency], offer['memo'], offer['react_time']
    )
    if trx:
        locale = offer['locale_{}'.format(other_id)]
        url = markdown.link(
            _('Transaction is confirmed.', locale=locale),
            escrow_object.trx_url(trx['trx_id'])
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton(
                _('Sent', locale=locale), callback_data='tokens_sent {}'.format(offer['_id'])
            ),
            InlineKeyboardButton(
                _('Cancel', locale=locale), callback_data='tokens_cancel {}'.format(offer['_id'])
            )
        )
        await database.escrow.update_one(
            {'_id': offer['_id']},
            {'$set': {
                'return_address': trx['from'],
                'trx_id': trx['trx_id'],
                'stage': 'confirmed'
            }}
        )
        await tg.send_message(
            other_id,
            url + '\n' + _('Send {} {} to address {}', locale=locale).format(
                offer[f'sum_{new_currency}'], offer[new_currency], memo_address
            ) + '.',
            reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
        await call.answer()
        await tg.send_message(
            call.message.chat.id,
            _('Transaction is confirmed.') + ' ' +
            _("I'll notify should you get {}.").format(offer[new_currency])
        )
    else:
        await call.answer(_("Transaction wasn't found."))


@dp.callback_query_handler(lambda call: call.data.startswith('tokens_cancel '))
@escrow_callback_handler
async def cancel_confirmed_offer(call: types.CallbackQuery, offer: Mapping[str, Any]):
    escrow_currency = offer['escrow_currency']

    if escrow_currency == 'buy':
        return_id = offer['sell_id']
        cancel_id = offer['buy_id']
    elif escrow_currency == 'sell':
        return_id = offer['buy_id']
        cancel_id = offer['sell_id']

    escrow_object = get_escrow_instance(offer[escrow_currency])
    trx_url = await escrow_object.transfer(
        offer['return_address'], offer['sum_fee_up'].to_decimal(), offer[escrow_currency]
    )
    cancel_answer = _('Escrow was cancelled.', locale=offer['locale_{}'.format(cancel_id)])
    locale = offer['locale_{}'.format(return_id)]
    return_answer = _('Escrow was cancelled.', locale=locale) + ' ' + markdown.link(
        _('You got your {} {} back.', locale=locale).format(
            offer['sum_fee_up'], offer[escrow_currency]
        ), trx_url
    )
    await database.escrow_archive.insert_one(offer)
    await database.escrow.delete_one({'_id': offer['_id']})
    await call.answer()
    await tg.send_message(cancel_id, cancel_answer, reply_markup=start_keyboard())
    await tg.send_message(return_id, return_answer, reply_markup=start_keyboard())


@dp.callback_query_handler(lambda call: call.data.startswith('tokens_sent '))
@escrow_callback_handler
async def final_offer_confirmation(call: types.CallbackQuery, offer: Mapping[str, Any]):
    escrow_currency = offer['escrow_currency']

    if escrow_currency == 'buy':
        confirm_id = offer['sell_id']
        other_id = offer['buy_id']
        new_currency = 'sell'
    elif escrow_currency == 'sell':
        confirm_id = offer['buy_id']
        other_id = offer['sell_id']
        new_currency = 'buy'

    locale = offer['locale_{}'.format(confirm_id)]
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Yes', locale=locale), callback_data='escrow_complete {}'.format(offer['_id'])
        )
    )
    reply = await tg.send_message(
        confirm_id,
        _('Did you get {}?', locale=confirm_id).format(offer[new_currency]),
        reply_markup=keyboard
    )
    keyboard.add(
        InlineKeyboardButton(
            _('No', locale=locale), callback_data='escrow_validate {}'.format(offer['_id'])
        )
    )
    partial_edit = functools.partial(
        tg.edit_message_reply_markup, call.message.chat.id, reply.message_id,
        reply_markup=keyboard
    )
    asyncio.get_running_loop().call_later(60 * 10, partial_edit)
    await call.answer()
    await tg.send_message(
        other_id,
        _("When your transfer is confirmed, I'll complete escrow.",
          locale=offer['locale_{}'.format(other_id)]),
        reply_markup=start_keyboard()
    )


@dp.callback_query_handler(lambda call: call.data.startswith('escrow_complete '))
@escrow_callback_handler
async def complete_offer(call: types.CallbackQuery, offer: Mapping[str, Any]):
    escrow_currency = offer['escrow_currency']

    if escrow_currency == 'buy':
        recipient = 'buy'
        other_id = offer['sell_id']
    elif escrow_currency == 'sell':
        recipient = 'sell'
        other_id = offer['buy_id']

    escrow_object = get_escrow_instance(offer[escrow_currency])
    trx_url = await escrow_object.transfer(
        offer[f'{recipient}_address'], offer['sum_fee_down'].to_decimal(), offer[escrow_currency]
    )
    recipient_id = offer[f'{recipient}_id']
    locale = offer['locale_{}'.format(recipient_id)]
    answer = _('Escrow is completed!', locale=offer['locale_{}'.format(other_id)])
    recipient_answer = _('Escrow is completed!', locale=locale) + ' ' + markdown.link(
        _('I sent you {} {}.', locale=locale).format(
            offer['sum_fee_down'], offer[escrow_currency]
        ), trx_url
    )
    await database.escrow_archive.insert_one(offer)
    await database.escrow.delete_one({'_id': offer['_id']})
    await tg.send_message(recipient_id, recipient_answer, reply_markup=start_keyboard())
    await tg.send_message(other_id, answer, reply_markup=start_keyboard())
    await call.answer()


@dp.callback_query_handler(lambda call: call.data.startswith('escrow_validate '))
@escrow_callback_handler
async def validate_offer(call: types.CallbackQuery, offer: Mapping[str, Any]):
    escrow_currency = offer['escrow_currency']
    escrow_object = get_escrow_instance(offer[escrow_currency])
    await tg.send_message(
        SUPPORT_CHAT_ID,
        'Unconfirmed escrow.\nTransaction: {}\nMemo: {}'.format(
            escrow_object.trx_url(offer['trx_id']),
            markdown.code(offer['memo']),
        )
    )
    await database.escrow_archive.insert_one(offer)
    await database.escrow.delete_one({'_id': offer['_id']})
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _("We'll manually validate your request and decide on the return."),
        reply_markup=start_keyboard()
    )
