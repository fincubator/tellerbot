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


from dataclasses import dataclass, asdict
from typing import Any, Mapping, Optional

from bson.objectid import ObjectId
from bson.decimal128 import Decimal128

from src.database import database


@dataclass
class EscrowOffer:
    _id: ObjectId
    order: ObjectId
    buy: str
    sell: str
    type: str
    time: float
    init: Mapping[str, Any]
    counter: Mapping[str, Any]
    stage: str
    sum_currency: Optional[str] = None
    sum_buy: Optional[Decimal128] = None
    sum_sell: Optional[Decimal128] = None
    sum_fee_up: Optional[Decimal128] = None
    sum_fee_down: Optional[Decimal128] = None
    buy_address: Optional[str] = None
    sell_address: Optional[str] = None
    memo: Optional[str] = None
    return_address: Optional[str] = None
    trx_id: Optional[str] = None

    def __getitem__(self, key):
        return asdict(self)[key]

    async def insert_document(self):
        await database.escrow.insert_one(asdict(self))

    async def update_document(self, update):
        await database.escrow.update_one({'_id': self._id}, update)

    async def delete_document(self):
        await database.escrow_archive.insert_one(asdict(self))
        await database.escrow.delete_one({'_id': self._id})
