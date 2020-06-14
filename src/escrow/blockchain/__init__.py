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
import json
import typing
from abc import ABC
from abc import abstractmethod
from asyncio import create_task
from asyncio import get_running_loop
from decimal import Decimal
from time import time

from aiogram.types import InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup
from aiogram.types import ParseMode
from aiogram.utils import markdown
from bson.objectid import ObjectId

from src.bot import tg
from src.config import config
from src.database import database
from src.i18n import i18n


class InsuranceLimits(typing.NamedTuple):
    """Maximum amount of insured asset."""

    #: Limit on sum of a single offer.
    single: Decimal
    #: Limit on overall sum of offers.
    total: Decimal


class BaseBlockchain(ABC):
    """Abstract class to represent blockchain node client for escrow exchange."""

    #: Internal name of blockchain referenced in ``config.ESCROW_FILENAME``.
    name: str
    #: Frozen set of assets supported by blockchain.
    assets: typing.FrozenSet[str] = frozenset()
    #: Address used by bot.
    address: str
    #: Template of URL to transaction in blockchain explorer. Should
    #: contain ``{}`` which gets replaced with transaction id.
    explorer: str = "{}"

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection with blockchain node."""

    @abstractmethod
    async def get_limits(self, asset: str) -> InsuranceLimits:
        """Get maximum amounts of ``asset`` which will be insured during escrow exchange.

        Escrow offer starts only if sum of it doesn't exceed these limits.
        """

    async def check_transaction(
        self,
        *,
        offer_id: ObjectId,
        from_address: str,
        amount_with_fee: Decimal,
        amount_without_fee: Decimal,
        asset: str,
        memo: str,
        transaction_time: float,
    ) -> bool:
        """Check transaction in history of escrow address.

        :param offer_id: ``_id`` of escrow offer.
        :param from_address: Address which sent assets.
        :param amount_with_fee: Amount of transferred asset with fee added.
        :param amount_without_fee: Amount of transferred asset with fee substracted.
        :param asset: Transferred asset.
        :param memo: Memo in blockchain transaction.
        :param transaction_time: Start of transaction check.
        :return: Queue member with timeout handler or None if queue member is timeouted.
        """

    @abstractmethod
    async def transfer(
        self, to: str, amount: Decimal, asset: str, memo: str = ""
    ) -> str:
        """Transfer ``asset`` from ``self.address``.

        :param to: Address assets are transferred to.
        :param amount: Amount of transferred asset.
        :param asset: Transferred asset.
        :return: URL to transaction in blockchain explorer.
        """

    @abstractmethod
    async def is_block_confirmed(
        self, block_num: int, op: typing.Mapping[str, typing.Any]
    ) -> bool:
        """Check if block # ``block_num`` has ``op`` after confirmation.

        Check block on blockchain-specific conditions to consider it confirmed.

        :param block_num: Number of block to check.
        :param op: Operation to check.
        """

    async def close(self):
        """Close connection with blockchain node."""

    @property
    def nodes(self) -> typing.List[str]:
        """Get list of node URLs."""
        with open(config.ESCROW_FILENAME) as escrow_file:
            return json.load(escrow_file)[self.name]["nodes"]

    @property
    def wif(self) -> str:
        """Get private key encoded to WIF."""
        with open(config.ESCROW_FILENAME) as escrow_file:
            return json.load(escrow_file)[self.name]["wif"]

    def trx_url(self, trx_id: str) -> str:
        """Get URL on transaction with ID ``trx_id`` on explorer."""
        return self.explorer.format(trx_id)

    async def create_queue(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """Create queue from unconfirmed transactions in database."""
        queue: typing.List[typing.Dict[str, typing.Any]] = []
        cursor = database.escrow.find(
            {
                "escrow": {"$in": list(self.assets)},
                "memo": {"$exists": True},
                "trx_id": {"$exists": False},
            }
        )
        async for offer in cursor:
            if offer["type"] == "buy":
                address = offer["init"]["send_address"]
                amount = offer["sum_buy"].to_decimal()
            else:
                address = offer["counter"]["send_address"]
                amount = offer["sum_sell"].to_decimal()
            queue_member = {
                "offer_id": offer["_id"],
                "from_address": address,
                "amount_with_fee": offer["sum_fee_up"].to_decimal(),
                "amount_without_fee": amount,
                "asset": offer[offer["type"]],
                "memo": offer["memo"],
                "transaction_time": offer["transaction_time"],
            }
            scheduled_queue_member = await self.schedule_timeout(queue_member)
            if scheduled_queue_member:
                queue.append(scheduled_queue_member)
        return queue

    def get_min_time(self, queue: typing.List[typing.Dict[str, typing.Any]]) -> float:
        """Get timestamp of earliest transaction from ``queue``."""
        return min(queue, key=lambda q: q["transaction_time"])["transaction_time"]

    async def schedule_timeout(
        self, queue_member: typing.Dict[str, typing.Any]
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """Schedule timeout of transaction check."""
        timedelta = queue_member["transaction_time"] - time()
        delay = timedelta + config.CHECK_TIMEOUT_HOURS * 60 * 60
        if delay <= 0:
            await self._check_timeout(queue_member["offer_id"])
            return None
        loop = get_running_loop()
        queue_member["timeout_handler"] = loop.call_later(
            delay, self.check_timeout, queue_member["offer_id"]
        )
        return queue_member

    def check_timeout(self, offer_id: ObjectId) -> None:
        """Start transaction check timeout asynchronously.

        :param offer_id: ``_id`` of escrow offer.
        """
        create_task(self._check_timeout(offer_id))

    async def _check_timeout(self, offer_id: ObjectId) -> None:
        """Timeout transaction check."""
        offer = await database.escrow.find_one_and_delete({"_id": offer_id})
        await database.escrow_archive.insert_one(offer)
        await tg.send_message(
            offer["init"]["id"],
            i18n("check_timeout {hours}", locale=offer["init"]["locale"]).format(
                hours=config.CHECK_TIMEOUT_HOURS
            ),
        )
        await tg.send_message(
            offer["counter"]["id"],
            i18n("check_timeout {hours}", locale=offer["counter"]["locale"]).format(
                hours=config.CHECK_TIMEOUT_HOURS
            ),
        )

    async def _confirmation_callback(
        self,
        offer_id: ObjectId,
        op: typing.Mapping[str, typing.Any],
        trx_id: str,
        block_num: int,
    ) -> bool:
        """Confirm found block with transaction.

        Notify escrow asset sender and check if block is confirmed.
        If it is, continue exchange. If it is not, send warning and
        update ``transaction_time`` of escrow offer.

        :param offer_id: ``_id`` of escrow offer.
        :param op: Operation object to confirm.
        :param trx_id: ID of transaction with desired operation.
        :param block_num: Number of block to confirm.
        :return: True if transaction was confirmed and False otherwise.
        """
        offer = await database.escrow.find_one({"_id": offer_id})
        if not offer:
            return False

        if offer["type"] == "buy":
            new_currency = "sell"
            escrow_user = offer["init"]
            other_user = offer["counter"]
        elif offer["type"] == "sell":
            new_currency = "buy"
            escrow_user = offer["counter"]
            other_user = offer["init"]

        answer = i18n(
            "transaction_passed {currency}", locale=escrow_user["locale"]
        ).format(currency=offer[new_currency])
        await tg.send_message(escrow_user["id"], answer)
        is_confirmed = await create_task(self.is_block_confirmed(block_num, op))
        if is_confirmed:
            await database.escrow.update_one(
                {"_id": offer["_id"]}, {"$set": {"trx_id": trx_id, "unsent": True}}
            )
            keyboard = InlineKeyboardMarkup()
            keyboard.add(
                InlineKeyboardButton(
                    i18n("sent", locale=other_user["locale"]),
                    callback_data="tokens_sent {}".format(offer["_id"]),
                )
            )
            answer = markdown.link(
                i18n("transaction_confirmed", locale=other_user["locale"]),
                self.trx_url(trx_id),
            )
            answer += "\n" + i18n(
                "send {amount} {currency} {address}", locale=other_user["locale"]
            ).format(
                amount=offer[f"sum_{new_currency}"],
                currency=offer[new_currency],
                address=markdown.escape_md(escrow_user["receive_address"]),
            )
            answer += "."
            await tg.send_message(
                other_user["id"],
                answer,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )
            return True

        await database.escrow.update_one(
            {"_id": offer["_id"]}, {"$set": {"transaction_time": time()}}
        )
        answer = i18n("transaction_not_confirmed", locale=escrow_user["locale"])
        answer += " " + i18n("try_again", locale=escrow_user["locale"])
        await tg.send_message(escrow_user["id"], answer)
        return False

    async def _refund_callback(
        self,
        reasons: typing.FrozenSet[str],
        offer_id: ObjectId,
        op: typing.Mapping[str, typing.Any],
        from_address: str,
        amount: Decimal,
        asset: str,
        block_num: int,
    ) -> None:
        """Refund transaction after confirmation because of mistakes in it.

        :param reasons: Frozen set of mistakes in transaction.
            The only allowed elements are ``asset``, ``amount`` and ``memo``.
        :param offer_id: ``_id`` of escrow offer.
        :param op: Operation object to confirm.
        :param from_address: Address which sent assets.
        :param amount: Amount of transferred asset.
        :param asset: Transferred asset.
        """
        offer = await database.escrow.find_one({"_id": offer_id})
        if not offer:
            return

        user = offer["init"] if offer["type"] == "buy" else offer["counter"]
        answer = i18n("transfer_mistakes", locale=user["locale"])
        points = []
        for reason in reasons:
            if reason == "asset":
                memo_point = i18n("wrong_asset", locale="en")
                message_point = i18n("wrong_asset", locale=user["locale"])
            elif reason == "amount":
                memo_point = i18n("wrong_amount", locale="en")
                message_point = i18n("wrong_amount", locale=user["locale"])
            elif reason == "memo":
                memo_point = i18n("wrong_memo", locale="en")
                message_point = i18n("wrong_memo", locale=user["locale"])
            else:
                continue
            points.append(memo_point)
            answer += f"\n• {message_point}"

        answer += "\n\n" + i18n("refund_promise", locale=user["locale"])
        await tg.send_message(user["id"], answer, parse_mode=ParseMode.MARKDOWN)
        is_confirmed = await create_task(self.is_block_confirmed(block_num, op))
        await database.escrow.update_one(
            {"_id": offer["_id"]}, {"$set": {"transaction_time": time()}}
        )
        if is_confirmed:
            trx_url = await self.transfer(
                from_address,
                amount,
                asset,
                memo="reason of refund: " + ", ".join(points),
            )
            answer = markdown.link(
                i18n("transaction_refunded", locale=user["locale"]), trx_url
            )
        else:
            answer = i18n("transaction_not_confirmed", locale=user["locale"])
        answer += " " + i18n("try_again", locale=user["locale"])
        await tg.send_message(user["id"], answer, parse_mode=ParseMode.MARKDOWN)


class StreamBlockchain(BaseBlockchain):
    """Blockchain node client supporting continuous stream to check transaction."""

    _queue: typing.List[typing.Dict[str, typing.Any]] = []

    def remove_from_queue(
        self, offer_id: ObjectId
    ) -> typing.Optional[typing.Mapping[str, typing.Any]]:
        """Remove transaction with specified ``offer_id`` value from ``self._queue``.

        :param offer_id: ``_id`` of escrow offer.
        :return: True if transaction was found and False otherwise.
        """
        for queue_member in self._queue:
            if queue_member["offer_id"] == offer_id:
                if "timeout_handler" in queue_member:
                    queue_member["timeout_handler"].cancel()
                self._queue.remove(queue_member)
                return queue_member
        return None

    def check_timeout(self, offer_id: ObjectId) -> None:
        self.remove_from_queue(offer_id)
        super().check_timeout(offer_id)

    @abstractmethod
    async def stream(self) -> None:
        """Stream new blocks and check if they contain transactions from ``self._queue``.

        Use built-in method to subscribe to new blocks if node has it,
        otherwise get new blocks in blockchain-specific time interval between blocks.

        If block contains desired transaction, call ``self._confirmation_callback``.
        If it returns True, remove transaction from ``self._queue`` and stop
        streaming if ``self._queue`` is empty.
        """

    def start_streaming(self) -> None:
        """Start streaming in background asynchronous task."""
        create_task(self.stream())

    async def add_to_queue(self, **kwargs):
        """Add transaction to self._queue to be checked.

        Same parameters as in ``self.check_transaction``.
        """
        queue_member = await self.schedule_timeout(kwargs)
        if not queue_member:
            return
        self._queue.append(queue_member)
        # Start streaming if not already streaming
        if len(self._queue) == 1:
            self.start_streaming()


class BlockchainConnectionError(Exception):
    """Unsuccessful attempt at connection to blockchain node."""
