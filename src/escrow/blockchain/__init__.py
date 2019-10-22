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


from abc import ABC, abstractmethod
from decimal import Decimal

from bson.objectid import ObjectId

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from aiogram.utils import markdown

from src.escrow.escrow_offer import EscrowOffer
from src.handlers import tg
from src.database import database
from src.i18n import _


class BaseBlockchain(ABC):
    assets = []
    address = None
    explorer = ''
    _queue = []

    @abstractmethod
    async def connect(self):
        pass

    @abstractmethod
    async def transfer(self, to: str, amount: Decimal, asset: str):
        pass

    @abstractmethod
    async def start_streaming(self):
        pass

    def trx_url(self, trx_id):
        return self.explorer.format(trx_id)

    async def check_transaction(
        self, offer_id: ObjectId, from_address: str, amount: Decimal,
        asset: str, memo: str
    ):
        trx = {
            'offer_id': offer_id,
            'from_address': from_address,
            'amount': amount,
            'asset': asset,
            'memo': memo,
        }

        self._queue.append(trx)
        if len(self._queue) == 1:
            await self.start_streaming()

    def remove_from_queue(self, offer_id: ObjectId):
        for queue_member in self._queue:
            if queue_member['offer_id'] == offer_id:
                self._queue.remove(queue_member)
                return True
        return False

    async def _confirmation_callback(self, offer_id: ObjectId, trx_id: str):
        offer_document = await database.escrow.find_one({
            '_id': ObjectId(offer_id)
        })
        if not offer_document:
            return
        offer = EscrowOffer(**offer_document)

        if offer.type == 'buy':
            escrow_user = offer.init
            other_user = offer.counter
            new_currency = 'sell'
        elif offer.type == 'sell':
            escrow_user = offer.counter
            other_user = offer.init
            new_currency = 'buy'

        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton(
                _('Sent', locale=other_user['locale']),
                callback_data=f'tokens_sent {offer._id}'
            )
        )
        await offer.update_document({'$set': {'trx_id': trx_id}})
        answer = markdown.link(
            _('Transaction is confirmed.', locale=other_user['locale']),
            self.trx_url(trx_id)
        )
        answer += '\n' + markdown.escape_md(
            _('Send {} {} to address {}', locale=other_user['locale']).format(
                offer[f'sum_{new_currency}'],
                offer[new_currency],
                escrow_user['receive_address']
            )
        )
        answer += '.'
        await tg.send_message(
            other_user['id'], answer,
            reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
        await tg.send_message(
            escrow_user['id'],
            _('Transaction is confirmed.', locale=escrow_user['locale']) + ' ' +
            _("I'll notify should you get {}.", locale=escrow_user['locale']).format(
                offer[new_currency]
            )
        )


class BlockchainConnectionError(Exception):
    pass
