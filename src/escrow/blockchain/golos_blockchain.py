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


from asyncio import get_running_loop, create_task
from decimal import Decimal
import json

from golos import Api
from golos.ws_client import error_handler
from golos.exceptions import RetriesExceeded

from src.escrow.blockchain import BaseBlockchain, BlockchainConnectionError


class GolosBlockchain(BaseBlockchain):
    assets = ['GOLOS', 'GBG']
    address = 'tellerbot'
    explorer = 'https://golos.cf/tx/?={}'

    _NODES = [
        'wss://api.golos.blckchnd.com/ws',
        'wss://golosd.privex.io',
        'wss://golos.solox.world/ws',
        'wss://golos.lexa.host/ws',
    ]

    def __init__(self):
        try:
            self._golos = Api(nodes=self._NODES)
            self._stream = Api(nodes=self._NODES)
            self._stream.rpc.api_total['set_block_applied_callback'] = 'database_api'
        except RetriesExceeded as exception:
            raise BlockchainConnectionError(exception)

    async def transfer(self, to: str, amount: Decimal, asset: str):
        with open('wif.json') as wif_file:
            transaction = await get_running_loop().run_in_executor(
                None, self._golos.transfer,
                to, amount, self.address, json.load(wif_file)['golos'], asset
            )
        return self.trx_url(transaction['id'])

    async def start_streaming(self):
        create_task(self._start_streaming())

    async def _start_streaming(self):
        loop = get_running_loop()
        block = await loop.run_in_executor(
            None, self._stream.rpc.call, 'set_block_applied_callback', [0]
        )
        while True:
            for trx in block['transactions']:
                for op_type, op in trx['operations']:
                    queue_member = self._check_operation(op_type, op)
                    if not queue_member:
                        continue
                    trx_id = await loop.run_in_executor(
                        None, self._golos.get_transaction_id, trx
                    )
                    req, callback = queue_member
                    await callback(req['offer_id'], trx_id)
                    self._queue.remove(queue_member)
                    if not self._queue:
                        await loop.run_in_executor(None, self._stream.rpc.close)
                        return
            response = await loop.run_in_executor(None, self._stream.rpc.ws.recv)
            response_json = json.loads(response)
            if 'error' in response_json:
                return error_handler(response_json)
            block = response_json['result']

    def _check_operation(self, op_type, op):
        if op_type != 'transfer':
            return None
        tr_amount, tr_asset = op['amount'].split()
        decimal_amount = Decimal(tr_amount)
        for queue_member in self._queue:
            req = queue_member[0]
            if (
                op['to'] == self.address and
                op['from'] == req['from_address'] and
                decimal_amount == req['amount'] and
                tr_asset == req['asset'] and
                op['memo'] == req['memo']
            ):
                return queue_member


golos_blockchain = GolosBlockchain()
