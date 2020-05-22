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
from asyncio import sleep
from calendar import timegm
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urljoin

import aiohttp
from eospy import schema
from eospy import types
from eospy.keys import EOSKey
from eospy.utils import sig_digest

from src.config import config
from src.escrow.blockchain import BaseBlockchain
from src.escrow.blockchain import BlockchainConnectionError
from src.escrow.blockchain import InsuranceLimits


TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


class MaxRamKbytesSchema(schema.IntSchema):
    """RAM as an additional CyberWay resource."""

    default = 0
    missing = 0


class MaxStorageKbytesSchema(schema.IntSchema):
    """Storage as an additional CyberWay resource."""

    default = 0
    missing = 0


class CyberWayTransactionSchema(schema.TransactionSchema):
    """CyberWay transaction schema based on EOS schema with additional resources."""

    max_ram_kbytes = MaxRamKbytesSchema()
    max_storage_kbytes = MaxRamKbytesSchema()


class CyberWayTransaction(types.Transaction):
    """CyberWay transaction class based on EOS transaction."""

    def __init__(self, d, chain_info, lib_info):
        """EOS initialization with Cyberway compatible schema validator."""
        if "expiration" not in d:
            d["expiration"] = str(datetime.utcnow() + timedelta(seconds=30))
        if "ref_block_num" not in d:
            d["ref_block_num"] = chain_info["last_irreversible_block_num"] & 0xFFFF
        if "ref_block_prefix" not in d:
            d["ref_block_prefix"] = lib_info["ref_block_prefix"]
        self._validator = CyberWayTransactionSchema()
        super(types.Transaction, self).__init__(d)
        self.actions = self._create_obj_array(self.actions, types.Action)

    def _encode_hdr(self):
        exp_diff = self.expiration - datetime(1970, 1, 1, tzinfo=self.expiration.tzinfo)
        exp = self._encode_buffer(types.UInt32(exp_diff.total_seconds()))
        ref_blk = self._encode_buffer(types.UInt16(self.ref_block_num & 0xFFFF))
        ref_block_prefix = self._encode_buffer(types.UInt32(self.ref_block_prefix))
        net_usage_words = self._encode_buffer(types.VarUInt(self.net_usage_words))
        max_cpu_usage_ms = self._encode_buffer(types.Byte(self.max_cpu_usage_ms))
        max_ram_kbytes = self._encode_buffer(types.VarUInt(self.max_ram_kbytes))
        max_storage_kbytes = self._encode_buffer(types.VarUInt(self.max_storage_kbytes))
        delay_sec = self._encode_buffer(types.VarUInt(self.delay_sec))
        return (
            f"{exp}"
            f"{ref_blk}"
            f"{ref_block_prefix}"
            f"{net_usage_words}"
            f"{max_cpu_usage_ms}"
            f"{max_ram_kbytes}"
            f"{max_storage_kbytes}"
            f"{delay_sec}"
        )


class CyberBlockchain(BaseBlockchain):
    """Golos node client implementation for escrow exchange."""

    name = "cyber"
    assets = frozenset(["CYBER", "CYBER.GOLOS"])
    address = "usr11jwlrakn"
    explorer = "https://explorer.cyberway.io/trx/{}"

    async def connect(self):
        self._session = aiohttp.ClientSession(
            raise_for_status=True, timeout=aiohttp.ClientTimeout(total=30)
        )
        with open(config.ESCROW_FILENAME) as escrow_file:
            nodes = json.load(escrow_file)["cyber"]["nodes"]
        for node in nodes:
            try:
                async with self._session.get(urljoin(node, "v1/chain/get_info")):
                    self._node = node
                    break
            except (aiohttp.ClientResponseError, aiohttp.ClientConnectorError):
                continue
        else:
            raise BlockchainConnectionError("Couldn't connect to any node")

        queue = await self.create_queue()
        if not queue:
            return
        await self._check_queue_in_history(queue)

    async def check_transaction(self, **kwargs) -> bool:
        return await self._check_queue_in_history([kwargs])

    async def get_limits(self, asset: str):
        return InsuranceLimits(Decimal("10000"), Decimal("100000"))

    async def transfer(self, to: str, amount: Decimal, asset: str, memo: str = ""):
        if "." in asset:
            asset = asset.split(".")[1]
        if asset == "CYBER":
            formatted_amount = f"{amount:.4f}"
        elif asset == "GOLOS":
            formatted_amount = f"{amount:.3f}"
        arguments = {
            "from": self.address,
            "to": await self._resolve_address(to),
            "quantity": f"{formatted_amount} {asset}",
            "memo": memo,
        }
        payload = {
            "account": "cyber.token",
            "name": "transfer",
            "authorization": [{"actor": self.address, "permission": "active"}],
        }
        payload_data = await self._api(
            "v1/chain/abi_json_to_bin",
            data={
                "code": payload["account"],
                "action": payload["name"],
                "args": arguments,
            },
        )
        payload["data"] = payload_data["binargs"]
        chain_info = await self._api("v1/chain/get_info")
        lib_info = await self._api(
            "v1/chain/get_block",
            data={"block_num_or_id": chain_info["last_irreversible_block_num"]},
        )
        trx = CyberWayTransaction({"actions": [payload]}, chain_info, lib_info)
        digest = sig_digest(trx.encode(), chain_info["chain_id"])
        transaction = trx.__dict__
        transaction["expiration"] = trx.expiration.strftime(TIME_FORMAT)[:-3]
        final_trx = {
            "compression": "none",
            "transaction": transaction,
            "signatures": [EOSKey(self.wif).sign(digest)],
        }
        trx_data = json.dumps(final_trx, cls=types.EOSEncoder)
        result = await self._api("v1/chain/push_transaction", data=trx_data)
        return self.trx_url(result["transaction_id"])

    async def is_block_confirmed(self, block_num, op):
        while True:
            try:
                info = await self._api("v1/chain/get_info")
            except aiohttp.ClientResponseError:
                continue
            if block_num <= info["last_irreversible_block_num"]:
                break
            await sleep(3)
        try:
            await self._api(
                "v1/history/get_transaction",
                data={"id": op["trx_id"], "block_num_hint": block_num},
            )
        except aiohttp.ClientResponseError:
            return False
        else:
            return True

    async def close(self):
        if hasattr(self, "_session"):
            await self._session.close()

    async def _api(
        self,
        method: str,
        *,
        data: typing.Union[None, str, typing.Sequence, typing.Mapping] = None,
        **kwargs,
    ) -> typing.Dict[str, typing.Any]:
        url = urljoin(self._node, method)
        if data is not None and not isinstance(data, str):
            data = json.dumps(data)
        async with self._session.post(url, data=data, **kwargs) as resp:
            return await resp.json()

    async def _resolve_addresses(
        self, addresses: typing.List[str]
    ) -> typing.Dict[str, str]:
        # Change golos address to cyberway address
        result = {}
        data = [f"{address}@golos" for address in addresses]
        while True:
            cyberway_usernames = await self._api(
                "v1/chain/resolve_names", data=data, raise_for_status=False
            )
            if isinstance(cyberway_usernames, dict):
                error_message = cyberway_usernames["error"]["details"][-1]["message"]
                error_element = error_message.split()[-1]
                data = [element for element in data if element != error_element]
                cyberway_username = error_element.split("@")[0]
                result[cyberway_username] = cyberway_username
                if not data:
                    break
            else:
                for element, cyberway_username in zip(data, cyberway_usernames):
                    golos_address = element.split("@")[0]
                    result[golos_address] = cyberway_username["resolved_username"]
                break
        return result

    async def _resolve_address(self, address) -> str:
        address = address.lower()
        addresses = await self._resolve_addresses([address])
        return addresses[address]

    async def _check_queue_in_history(
        self, queue: typing.List[typing.Dict[str, typing.Any]],
    ) -> bool:
        addresses = [queue_member["from_address"].lower() for queue_member in queue]
        resolved = await self._resolve_addresses(addresses)
        for queue_member, address in zip(queue, addresses):
            queue_member["from_address"] = resolved[address]

        pos = -1
        min_time = self.get_min_time(queue)
        while True:
            history = await self._api(
                "v1/history/get_actions",
                data={"account_name": self.address, "pos": pos, "offset": -20},
            )
            if not history["actions"]:
                return False
            for act in reversed(history["actions"]):
                date = datetime.strptime(act["block_time"], TIME_FORMAT)
                if timegm(date.timetuple()) < min_time:
                    return False
                op = act["action_trace"]["act"]["data"]
                op["timestamp"] = act["block_time"]
                op["trx_id"] = act["action_trace"]["trx_id"]
                req = await self._check_operation(op, act["block_num"], queue)
                if not req:
                    continue
                await self._confirmation_callback(
                    req["offer_id"], op, op["trx_id"], act["block_num"]
                )
                if len(queue) == 1:
                    return True
            pos = history["actions"][0]["account_action_seq"] - 1

    async def _check_operation(
        self,
        op: typing.Mapping[str, typing.Any],
        block_num: int,
        queue: typing.List[typing.Dict[str, typing.Any]],
    ):
        op_amount, asset = op["quantity"].split()
        amount = Decimal(op_amount)
        for req in queue:
            if "timestamp" in op:
                date = datetime.strptime(op["timestamp"], TIME_FORMAT)
                if timegm(date.timetuple()) < req["transaction_time"]:
                    continue
            if op["to"] != self.address or op["from"] != req["from_address"]:
                continue
            req_asset = req["asset"]
            if "." in req_asset:
                req_asset = req_asset.split(".")[1]
            refund_reasons = set()
            if asset != req_asset:
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
