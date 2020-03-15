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
import functools
import json
import typing
from asyncio import create_task
from asyncio import get_running_loop
from asyncio import sleep
from calendar import timegm
from datetime import datetime
from decimal import Decimal
from time import time

from golos import Api
from golos.exceptions import RetriesExceeded
from golos.exceptions import TransactionNotFound
from golos.ws_client import error_handler

from src.config import config
from src.database import database
from src.escrow.blockchain import BaseBlockchain
from src.escrow.blockchain import BlockchainConnectionError
from src.escrow.blockchain import InsuranceLimits


NODES = (
    "wss://api.golos.blckchnd.com/ws",
    "wss://golosd.privex.io",
    "wss://golos.solox.world/ws",
    "wss://golos.lexa.host/ws",
)


class GolosBlockchain(BaseBlockchain):
    """Golos node client implementation for escrow exchange."""

    assets = frozenset(["GOLOS", "GBG"])
    address = "tellerbot"
    explorer = "https://golos.cf/tx/?={}"

    async def connect(self):
        loop = get_running_loop()
        connect_to_node = functools.partial(Api, nodes=NODES)
        try:
            self._golos = await loop.run_in_executor(None, connect_to_node)
            self._stream = await loop.run_in_executor(None, connect_to_node)
            self._stream.rpc.api_total["set_block_applied_callback"] = "database_api"
        except RetriesExceeded as exception:
            raise BlockchainConnectionError(exception)

        queue = []
        cursor = database.escrow.find(
            {"memo": {"$exists": True}, "trx_id": {"$exists": False}}
        )
        min_time = None
        async for offer in cursor:
            if offer["type"] == "buy":
                address = offer["init"]["send_address"]
                amount = offer["sum_buy"].to_decimal()
            else:
                address = offer["counter"]["send_address"]
                amount = offer["sum_sell"].to_decimal()
            queue_member = self.create_queue_member(
                offer_id=offer["_id"],
                from_address=address,
                amount_with_fee=offer["sum_fee_up"].to_decimal(),
                amount_without_fee=amount,
                asset=offer[offer["type"]],
                memo=offer["memo"],
                transaction_time=offer["transaction_time"],
            )
            if queue_member is not None:
                queue.append()
                if min_time is None or offer["transaction_time"] < min_time:
                    min_time = offer["transaction_time"]
        if not queue:
            return
        func = functools.partial(
            self._golos.get_account_history,
            self.address,
            op_limit="transfer",
            age=int(time() - min_time),
        )
        history = await get_running_loop().run_in_executor(None, func)
        for op in history:
            req = await self._check_operation(op, op["block"], queue)
            if not req:
                continue
            is_confirmed = await self._confirmation_callback(
                req["offer_id"], op, op["trx_id"], op["block"]
            )
            if is_confirmed:
                queue.remove(req)
                if not queue:
                    return
        self._queue.extend(queue)
        await self._start_streaming()

    async def get_limits(self, asset: str):
        limits = {"GOLOS": InsuranceLimits(Decimal("10000"), Decimal("100000"))}
        return limits.get(asset)

    async def transfer(self, to: str, amount: Decimal, asset: str, memo: str = ""):
        with open(config.WIF_FILENAME) as wif_file:
            transaction = await get_running_loop().run_in_executor(
                None,
                self._golos.transfer,
                to,
                amount,
                self.address,
                json.load(wif_file)["golos"],
                asset,
                memo,
            )
        return self.trx_url(transaction["id"])

    async def is_block_confirmed(self, block_num, op):
        loop = get_running_loop()
        while True:
            properties = await loop.run_in_executor(
                None, self._golos.get_dynamic_global_properties
            )
            if properties:
                head_block_num = properties["last_irreversible_block_num"]
                if block_num <= head_block_num:
                    break
            await sleep(3)
        op = {
            "block": block_num,
            "type_op": "transfer",
            "to": op["to"],
            "from": op["from"],
            "amount": op["amount"],
            "memo": op["memo"],
        }
        try:
            await loop.run_in_executor(None, self._golos.find_op_transaction, op)
        except TransactionNotFound:
            return False
        else:
            return True

    async def start_streaming(self):
        create_task(self._start_streaming())

    async def _start_streaming(self):
        loop = get_running_loop()
        block = await loop.run_in_executor(
            None, self._stream.rpc.call, "set_block_applied_callback", [0]
        )
        while True:
            for trx in block["transactions"]:
                for op_type, op in trx["operations"]:
                    if op_type != "transfer":
                        continue
                    block_num = int(block["previous"][:8], 16) + 1
                    req = await self._check_operation(op, block_num)
                    if not req:
                        continue
                    trx_id = await loop.run_in_executor(
                        None, self._golos.get_transaction_id, trx
                    )
                    is_confirmed = await self._confirmation_callback(
                        req["offer_id"], op, trx_id, block_num
                    )
                    if is_confirmed:
                        self._queue.remove(req)
            if not self._queue:
                await loop.run_in_executor(None, self._stream.rpc.close)
                return
            response = await loop.run_in_executor(None, self._stream.rpc.ws.recv)
            response_json = json.loads(response)
            if "error" in response_json:
                return error_handler(response_json)
            block = response_json["result"]

    async def _check_operation(
        self,
        op: typing.Mapping[str, typing.Any],
        block_num: int,
        queue: typing.Optional[typing.List] = None,
    ):
        if queue is None:
            queue = self._queue
        op_amount, asset = op["amount"].split()
        amount = Decimal(op_amount)
        for req in queue:
            if "timestamp" in op:
                date = datetime.strptime(op["timestamp"], "%Y-%m-%dT%H:%M:%S")
                if timegm(date.timetuple()) < req["transaction_time"]:
                    continue
            if op["to"] != self.address or op["from"] != req["from_address"]:
                continue
            req["timeout_handler"].cancel()
            refund_reasons = set()
            if asset != req["asset"]:
                refund_reasons.add("asset")
            if amount not in (req["amount_with_fee"], req["amount_without_fee"]):
                refund_reasons.add("amount")
            if op["memo"] != req["memo"]:
                refund_reasons.add("memo")
            if not refund_reasons:
                return req
            await self._refund_callback(
                frozenset(refund_reasons),
                req["offer_id"],
                op,
                op["from"],
                amount,
                asset,
                block_num,
            )
