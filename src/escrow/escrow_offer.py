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
import typing
from dataclasses import dataclass

from bson.decimal128 import Decimal128
from bson.objectid import ObjectId

from src.database import database


def asdict(instance):
    """Represent class instance as dictionary excluding None values."""
    return {key: value for key, value in instance.__dict__.items() if value is not None}


@dataclass
class EscrowOffer:
    """Class used to represent escrow offer.

    Attributes correspond to fields in database document.
    """

    #: Primary key value of offer document.
    _id: ObjectId
    #: Primary key value of corresponding order document.
    order: ObjectId
    #: Currency which order creator wants to buy.
    buy: str
    #: Currency which order creator wants to sell.
    sell: str
    #: Type of offer. Field of currency which is held during exchange.
    type: str  # noqa: A003
    #: Currency which is held during exchange.
    escrow: str
    #: Unix time stamp of offer creation.
    time: float
    #: Object representing initiator of escrow.
    init: typing.Mapping[str, typing.Any]
    #: Object representing counteragent of escrow.
    counter: typing.Mapping[str, typing.Any]
    #: Telegram ID of user required to send message to bot.
    pending_input_from: typing.Optional[int] = None
    #: Temporary field of currency in which user is sending amount.
    sum_currency: typing.Optional[str] = None
    #: Amount in ``buy`` currency.
    sum_buy: typing.Optional[Decimal128] = None
    #: Amount in ``sell`` currency.
    sum_sell: typing.Optional[Decimal128] = None
    #: Amount of held currency with agreed fee added.
    sum_fee_up: typing.Optional[Decimal128] = None
    #: Amount of held currency with agreed fee substracted.
    sum_fee_down: typing.Optional[Decimal128] = None
    #: Amount of insured currency.
    insured: typing.Optional[Decimal128] = None
    #: Unix time stamp of counteragent first reaction to sent offer.
    react_time: typing.Optional[float] = None
    #: Unix time stamp since which transaction should be checked.
    transaction_time: typing.Optional[float] = None
    #: Unix time stamp of offer cancellation.
    cancel_time: typing.Optional[float] = None
    #: Bank of fiat currency.
    bank: typing.Optional[str] = None
    #: Required memo in blockchain transaction.
    memo: typing.Optional[str] = None
    #: ID of verified transaction.
    trx_id: typing.Optional[str] = None
    #: True if non-escrow token sender hasn't confirmed their transfer.
    unsent: typing.Optional[bool] = None

    def __getitem__(self, key: str) -> typing.Any:
        """Allow to use class as dictionary."""
        return asdict(self)[key]

    async def insert_document(self) -> None:
        """Convert self to document and insert to database."""
        await database.escrow.insert_one(asdict(self))

    async def update_document(self, update) -> None:
        """Update corresponding document in database.

        :param update: Document with update operators or aggregation
            pipeline sent to MongoDB.
        """
        await database.escrow.update_one({"_id": self._id}, update)

    async def delete_document(self) -> None:
        """Archive and delete corresponding document in database."""
        await database.escrow_archive.insert_one(asdict(self))
        await database.escrow.delete_one({"_id": self._id})
