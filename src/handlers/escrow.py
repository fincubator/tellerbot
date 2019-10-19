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
from decimal import Decimal
from time import time
from typing import Optional
import string

from bson.objectid import ObjectId
from bson.decimal128 import Decimal128

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import any_state
from aiogram.utils import markdown

from config import SUPPORT_CHAT_ID
from src.handlers import tg, dp, private_handler, show_order, validate_money, start_keyboard
from src.database import database
from src.escrow import EscrowOffer, get_escrow_class, get_escrow_instance
from src.i18n import _
from src import states
from src.utils import normalize_money, MoneyValidationError


def is_address_valid(address):
    return len(address) <= 64


async def call_later(delay, callback, *args, **kwargs):
    await asyncio.sleep(delay)
    return (await callback(*args, **kwargs))


def escrow_callback_handler(*args, state=any_state, **kwargs):
    def decorator(handler):
        @dp.callback_query_handler(*args, state=state, **kwargs)
        async def wrapper(call: types.CallbackQuery):
            offer_id = call.data.split()[1]
            offer = await database.escrow.find_one({'_id': ObjectId(offer_id)})

            if not offer:
                await call.answer(_('Offer is not active.'))
                return

            return await handler(call, EscrowOffer(**offer))
        return wrapper
    return decorator


def escrow_message_handler(*args, **kwargs):
    def decorator(handler):
        @private_handler(*args, **kwargs)
        async def wrapper(message: types.Message, state: FSMContext):
            offer = await database.escrow.find_one({'pending_input_from': message.from_user.id})
            if not offer:
                await tg.send_message(message.chat.id, _('Offer is not active.'))
                return

            return await handler(message, state, EscrowOffer(**offer))
        return wrapper
    return decorator


@escrow_message_handler(state=states.Escrow.sum)
async def set_escrow_sum(message: types.Message, state: FSMContext, offer: EscrowOffer):
    try:
        escrow_sum = await validate_money(message.text, message.chat.id)
    except MoneyValidationError as exception:
        await tg.send_message(message.chat.id, str(exception))
        return

    order = await database.orders.find_one({'_id': offer.order})
    order_sum = order.get(offer.sum_currency)
    if order_sum and escrow_sum > order_sum.to_decimal():
        await tg.send_message(
            message.chat.id,
            _("Send number not exceeding order's sum.")
        )
        return

    update_dict = {offer.sum_currency: Decimal128(escrow_sum)}
    new_currency = 'sell' if offer.sum_currency == 'sum_buy' else 'buy'
    update_dict[f'sum_{new_currency}'] = Decimal128(normalize_money(
        escrow_sum * order[f'price_{new_currency}'].to_decimal()
    ))
    escrow_sum = update_dict[f'sum_{offer.type}']
    update_dict['sum_fee_up'] = Decimal128(normalize_money(
        escrow_sum.to_decimal() * Decimal('1.05')
    ))
    update_dict['sum_fee_down'] = Decimal128(normalize_money(
        escrow_sum.to_decimal() * Decimal('0.95')
    ))

    await offer.update_document(
        {'$set': update_dict, '$unset': {'sum_currency': True}}
    )
    answer = _('Do you agree to pay a fee of 5%?') + ' '
    if offer.type == 'buy':
        answer += _("(You'll pay {} {})")
        sum_fee_field = 'sum_fee_up'
    elif offer.type == 'sell':
        answer += _("(You'll get {} {})")
        sum_fee_field = 'sum_fee_down'
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Yes'), callback_data='init_accept_fee {} {}'.format(offer._id, sum_fee_field)
        ),
        InlineKeyboardButton(
            _('No'), callback_data='init_decline_fee {} {}'.format(offer._id, sum_fee_field)
        )
    )
    answer = answer.format(update_dict[sum_fee_field], offer[offer.type])
    await tg.send_message(message.chat.id, answer, reply_markup=keyboard)
    await states.Escrow.init_fee.set()


@escrow_callback_handler(lambda call: call.data.startswith('init_accept_fee '), state=states.Escrow.init_fee)
async def init_pay_fee(call: types.CallbackQuery, offer: EscrowOffer):
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _('Send your {} address.').format(offer.sell)
    )
    await states.Escrow.init_receive_address.set()


@escrow_callback_handler(lambda call: call.data.startswith('init_decline_fee '), state=states.Escrow.init_fee)
async def init_decline_fee(call: types.CallbackQuery, offer: EscrowOffer):
    sum_fee_field = call.data.split()[2]
    await offer.update_document(
        {'$set': {sum_fee_field: offer['sum_' + offer.type]}}
    )
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _('Send your {} address.').format(offer.sell)
    )
    await states.Escrow.init_receive_address.set()


@escrow_message_handler(state=states.Escrow.init_receive_address)
async def set_init_receive_address(message: types.Message, state: FSMContext, offer: EscrowOffer):
    if not is_address_valid(message.text):
        await tg.send_message(message.chat.id, _('Address is invalid.'))
        return

    await offer.update_document(
        {'$set': {'init.receive_address': message.text}}
    )
    await tg.send_message(
        message.chat.id,
        _('Send your {} address.').format(offer.buy)
    )
    await states.Escrow.init_send_address.set()


@escrow_message_handler(state=states.Escrow.init_send_address)
async def set_init_send_address(message: types.Message, state: FSMContext, offer: EscrowOffer):
    if not is_address_valid(message.text):
        await tg.send_message(message.chat.id, _('Address is invalid.'))
        return

    await offer.update_document({
        '$set': {'init.send_address': message.text},
        '$unset': {'pending_input_from': True}
    })
    order = await database.orders.find_one({'_id': offer.order})
    await show_order(
        order, offer.counter['id'], offer.counter['id'],
        show_id=True, locale=offer.counter['locale']
    )
    locale = offer.counter['locale']
    buy_keyboard = InlineKeyboardMarkup()
    buy_keyboard.add(
        InlineKeyboardButton(
            _('Accept', locale=locale), callback_data='accept {}'.format(offer._id)
        ),
        InlineKeyboardButton(
            _('Decline', locale=locale), callback_data='decline {}'.format(offer._id)
        )
    )
    await tg.send_message(
        offer.counter['id'],
        _('You got an escrow offer to sell {} {} for {} {}.', locale=locale).format(
            offer.sum_sell, offer.sell,
            offer.sum_buy, offer.buy
        ),
        reply_markup=buy_keyboard
    )
    sell_keyboard = InlineKeyboardMarkup()
    sell_keyboard.add(InlineKeyboardButton(
        _('Cancel'), callback_data='escrow_cancel {}'.format(offer._id)
    ))
    await tg.send_message(
        message.from_user.id,
        _('Offer sent.'),
        reply_markup=sell_keyboard
    )
    await state.finish()


@escrow_callback_handler(lambda call: call.data.startswith('accept '))
async def accept_offer(call: types.CallbackQuery, offer: EscrowOffer):
    await offer.update_document(
        {'$set': {'pending_input_from': call.message.chat.id, 'react_time': time()}}
    )
    answer = _('Do you agree to pay a fee of 5%?') + ' '
    if offer.type == 'buy':
        answer += _("(You'll get {} {})")
        sum_fee_field = 'sum_fee_down'
    elif offer.type == 'sell':
        answer += _("(You'll pay {} {})")
        sum_fee_field = 'sum_fee_up'
    answer = answer.format(offer[sum_fee_field], offer[offer.type])
    buy_keyboard = InlineKeyboardMarkup()
    buy_keyboard.add(
        InlineKeyboardButton(
            _('Yes'), callback_data='counter_accept_fee {} {}'.format(offer._id, sum_fee_field)
        ),
        InlineKeyboardButton(
            _('No'), callback_data='counter_decline_fee {} {}'.format(offer._id, sum_fee_field)
        )
    )
    await call.answer()
    await tg.send_message(call.message.chat.id, answer, reply_markup=buy_keyboard)
    await states.Escrow.counter_fee.set()


@escrow_callback_handler(lambda call: call.data.startswith('decline '))
async def decline_offer(call: types.CallbackQuery, offer: EscrowOffer):
    offer.react_time = time()
    await offer.delete_document()
    await tg.send_message(
        offer.init['id'],
        _('Your escrow offer was declined.', locale=offer.init['locale'])
    )
    await call.answer()
    await tg.send_message(call.message.chat.id, _('Offer was declined.'))


@escrow_callback_handler(
    lambda call: call.data.startswith('counter_accept_fee '),
    state=states.Escrow.counter_fee
)
async def counter_pay_fee(call: types.CallbackQuery, offer: EscrowOffer):
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _('Send your {} address.').format(offer.buy)
    )
    await states.Escrow.counter_receive_address.set()


@escrow_callback_handler(
    lambda call: call.data.startswith('counter_decline_fee '),
    state=states.Escrow.counter_fee
)
async def counter_decline_fee(call: types.CallbackQuery, offer: EscrowOffer):
    sum_fee_field = call.data.split()[2]
    await offer.update_document(
        {'$set': {sum_fee_field: offer['sum_' + offer.type]}}
    )
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _('Send your {} address.').format(offer.buy)
    )
    await states.Escrow.counter_receive_address.set()


@escrow_message_handler(state=states.Escrow.counter_receive_address)
async def set_counter_receive_address(message: types.Message, state: FSMContext, offer: EscrowOffer):
    if not is_address_valid(message.text):
        await tg.send_message(message.chat.id, _('Address is invalid.'))
        return

    await offer.update_document(
        {'$set': {'counter.receive_address': message.text}}
    )
    await tg.send_message(
        message.chat.id,
        _('Send your {} address.').format(offer.sell)
    )
    await states.Escrow.counter_send_address.set()


@escrow_message_handler(state=states.Escrow.counter_send_address)
async def set_counter_send_address(message: types.Message, state: FSMContext, offer: EscrowOffer):
    if not is_address_valid(message.text):
        await tg.send_message(message.chat.id, _('Address is invalid.'))
        return

    template = (
        'to {escrow_receive_address} '
        'for {not_escrow_amount} {not_escrow_currency} '
        'from {not_escrow_send_address} to {not_escrow_receive_address} '
        'via escrow service on https://t.me/TellerBot'
    )
    if offer.type == 'buy':
        memo = template.format(**{
            'escrow_receive_address': offer.counter['receive_address'],
            'not_escrow_amount': offer.sum_sell,
            'not_escrow_currency': offer.sell,
            'not_escrow_send_address': message.text,
            'not_escrow_receive_address': offer.init['receive_address']
        })
        escrow_user = offer.init
        send_reply = True
    elif offer.type == 'sell':
        memo = template.format(**{
            'escrow_receive_address': offer.init['receive_address'],
            'not_escrow_amount': offer.sum_buy,
            'not_escrow_currency': offer.buy,
            'not_escrow_send_address': offer.init['send_address'],
            'not_escrow_receive_address': offer.counter['receive_address']
        })
        escrow_user = offer.counter
        send_reply = False

    await offer.update_document({
        '$set': {
            'counter.send_address': message.text,
            'memo': memo,
            'transaction_time': time(),
        },
        '$unset': {
            'pending_input_from': True
        }
    })
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Sent', locale=escrow_user['locale']),
            callback_data='escrow_sent {}'.format(offer._id)
        ),
        InlineKeyboardButton(
            _('Cancel', locale=escrow_user['locale']),
            callback_data='escrow_cancel {}'.format(offer._id)
        )
    )
    escrow_address = markdown.bold(get_escrow_class(offer[offer.type]).address)
    await state.finish()
    await tg.send_message(
        escrow_user['id'],
        _('Send {} {} to address {}', locale=escrow_user['locale']).format(
            offer.sum_fee_up, offer[offer.type], escrow_address
        ) + ' ' + _('with memo', locale=escrow_user['locale']) + ':\n' + markdown.code(memo),
        reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )
    if send_reply:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(
            _('Cancel'), callback_data='escrow_cancel {}'.format(offer._id)
        ))
        await tg.send_message(
            message.chat.id,
            _('Transfer information sent.') + ' ' +
            _("I'll notify you when transaction is complete."),
            reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )


@escrow_callback_handler(lambda call: call.data.startswith('escrow_cancel '))
async def cancel_offer(call: types.CallbackQuery, offer: EscrowOffer):
    if offer.stage == 'confirmed':
        await call.answer(_("You can't cancel escrow on this stage."))
        return

    sell_answer = _('Escrow was cancelled.', locale=offer.init['locale'])
    buy_answer = _('Escrow was cancelled.', locale=offer.counter['locale'])
    offer.cancel_time = time()
    await offer.delete_document()
    await call.answer()
    await tg.send_message(offer.init['id'], sell_answer, reply_markup=start_keyboard())
    await tg.send_message(offer.counter['id'], buy_answer, reply_markup=start_keyboard())
    sell_state = FSMContext(dp.storage, offer.init['id'], offer.init['id'])
    buy_state = FSMContext(dp.storage, offer.counter['id'], offer.counter['id'])
    await sell_state.finish()
    await buy_state.finish()


@escrow_callback_handler(lambda call: call.data.startswith('escrow_sent '))
async def escrow_sent_confirmation(call: types.CallbackQuery, offer: EscrowOffer):
    escrow_instance = get_escrow_instance(offer[offer.type])

    if offer.type == 'buy':
        escrow_user = offer.init
        other_user = offer.counter
        new_currency = 'sell'
    elif offer.type == 'sell':
        escrow_user = offer.counter
        other_user = offer.init
        new_currency = 'buy'

    trx = await escrow_instance.get_transaction(
        escrow_user['send_address'],
        offer.sum_fee_up.to_decimal(),
        offer[offer.type],
        offer.memo,
        offer.transaction_time
    )
    if trx:
        url = markdown.link(
            _('Transaction is confirmed.', locale=other_user['locale']),
            escrow_instance.trx_url(trx['trx_id'])
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton(
                _('Sent', locale=other_user['locale']),
                callback_data='tokens_sent {}'.format(offer._id)
            ),
            InlineKeyboardButton(
                _('Cancel', locale=other_user['locale']),
                callback_data='tokens_cancel {}'.format(offer._id)
            )
        )
        await offer.update_document({
            '$set': {
                'return_address': trx['from'],
                'trx_id': trx['trx_id']
            }
        })
        await tg.send_message(
            other_user['id'],
            url + '\n' + _('Send {} {} to address {}', locale=other_user['locale']).format(
                offer[f'sum_{new_currency}'],
                offer[new_currency],
                escrow_user['receive_address']
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


@escrow_callback_handler(lambda call: call.data.startswith('tokens_cancel '))
async def cancel_confirmed_offer(call: types.CallbackQuery, offer: EscrowOffer):
    if offer.type == 'buy':
        return_user = offer.init
        cancel_user = offer.counter
    elif offer.type == 'sell':
        return_user = offer.counter
        cancel_user = offer.init

    escrow_instance = get_escrow_instance(offer[offer.type])
    trx_url = await escrow_instance.transfer(
        offer.return_address, offer.sum_fee_up.to_decimal(), offer[offer.type]
    )
    cancel_answer = _('Escrow was cancelled.', locale=cancel_user['locale'])
    return_answer = _('Escrow was cancelled.', locale=return_user['locale']) + ' ' + markdown.link(
        _('You got your {} {} back.', locale=return_user['locale']).format(
            offer.sum_fee_up, offer[offer.type]
        ), trx_url
    )
    await offer.delete_document()
    await call.answer()
    await tg.send_message(cancel_user['id'], cancel_answer, reply_markup=start_keyboard())
    await tg.send_message(return_user['id'], return_answer, reply_markup=start_keyboard())


@escrow_callback_handler(lambda call: call.data.startswith('tokens_sent '))
async def final_offer_confirmation(call: types.CallbackQuery, offer: EscrowOffer):
    if offer.type == 'buy':
        confirm_user = offer.init
        other_user = offer.counter
        new_currency = 'sell'
    elif offer.type == 'sell':
        confirm_user = offer.counter
        other_user = offer.init
        new_currency = 'buy'

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Yes', locale=confirm_user['locale']),
            callback_data='escrow_complete {}'.format(offer._id)
        )
    )
    reply = await tg.send_message(
        confirm_user['id'],
        _('Did you get {} from {}?', locale=confirm_user['locale']).format(
            offer[new_currency], other_user['send_address']
        ),
        reply_markup=keyboard
    )
    keyboard.add(
        InlineKeyboardButton(
            _('No', locale=confirm_user['locale']),
            callback_data='escrow_validate {}'.format(offer._id)
        )
    )
    await call_later(
        60 * 10, tg.edit_message_reply_markup,
        call.message.chat.id, reply.message_id,
        reply_markup=keyboard
    )
    await call.answer()
    await tg.send_message(
        other_user['id'],
        _("When your transfer is confirmed, I'll complete escrow.",
          locale=other_user['locale']),
        reply_markup=start_keyboard()
    )


@escrow_callback_handler(lambda call: call.data.startswith('escrow_complete '))
async def complete_offer(call: types.CallbackQuery, offer: EscrowOffer):
    if offer.type == 'buy':
        recipient_user = offer.counter
        other_user = offer.init
    elif offer.type == 'sell':
        recipient_user = offer.init
        other_user = offer.counter

    await call.answer(_('Escrow is being completed, please wait.'))
    escrow_instance = get_escrow_instance(offer[offer.type])
    trx_url = await escrow_instance.transfer(
        recipient_user['receive_address'],
        offer.sum_fee_down.to_decimal(),
        offer[offer.type]
    )
    answer = _('Escrow is completed!', locale=other_user['locale'])
    recipient_answer = _('Escrow is completed!', locale=recipient_user['locale']) + ' ' + markdown.link(
        _('I sent you {} {}.', locale=recipient_user['locale']).format(
            offer.sum_fee_down, offer[offer.type]
        ), trx_url
    )
    await offer.delete_document()
    await tg.send_message(
        recipient_user['id'], recipient_answer,
        reply_markup=start_keyboard(), parse_mode=ParseMode.MARKDOWN
    )
    await tg.send_message(
        other_user['id'], answer,
        reply_markup=start_keyboard()
    )


@escrow_callback_handler(lambda call: call.data.startswith('escrow_validate '))
async def validate_offer(call: types.CallbackQuery, offer: EscrowOffer):
    escrow_instance = get_escrow_instance(offer[offer.type])
    await tg.send_message(
        SUPPORT_CHAT_ID,
        'Unconfirmed escrow.\nTransaction: {}\nMemo: {}'.format(
            escrow_instance.trx_url(offer.trx_id),
            markdown.code(offer.memo),
        )
    )
    await offer.delete_document()
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _("We'll manually validate your request and decide on the return."),
        reply_markup=start_keyboard()
    )
