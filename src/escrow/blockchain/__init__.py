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
from typing import Any, Callable, Mapping

from bson.objectid import ObjectId


class BaseBlockchain(ABC):
    assets = []
    address = None
    explorer = ''
    _queue = []

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
        asset: str, memo: str, callback: Callable[[str], Any]
    ):
        trx = {
            'offer_id': offer_id,
            'from_address': from_address,
            'amount': amount,
            'asset': asset,
            'memo': memo,
        }

        self._queue.append((trx, callback))
        if len(self._queue) == 1:
            await self.start_streaming()

    def remove_from_queue(self, offer_id: ObjectId):
        for queue_member in self._queue:
            if queue_member[0]['offer_id'] == offer_id:
                self._queue.remove(queue_member)
                return True
        return False


class BlockchainConnectionError(Exception):
    pass
