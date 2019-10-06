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


from decimal import Decimal
import functools
import json
from time import time

from golos import Api
from asyncio import get_event_loop

from .base import BaseBlockchain


NODES = 'wss://api.golos.blckchnd.com/ws'
EXPLORER = 'https://golos.cf/tx/?={}'


class Golos(BaseBlockchain):
    assets = ['GOLOS', 'GBG']
    address = 'tellerbot'

    def __init__(self):
        self.golos = Api(nodes=NODES)

    def trx_url(trx_id):
        return EXPLORER.format(trx_id)

    async def transfer(self, to: str, amount: Decimal, asset: str, memo: str):
        with open('wif.json') as f:
            func = functools.partial(
                self.golos.transfer,
                to, amount, self.address, json.load(f)['golos'], asset, memo
            )
        transaction = await get_event_loop().run_in_executor(None, func)
        return self.trx_url(transaction['id'])

    async def get_transaction(self, from_account: str, amount: Decimal, memo: str, time_start: float):
        func = functools.partial(
            self.golos.get_account_history,
            self.address, op_limit='transfer', age=int(time() - time_start)
        )
        history = await get_event_loop().run_in_executor(None, func)
        for transaction in history:
            decimal_amount = Decimal(transaction['amount'].split()[0])
            if (transaction['to'] == self.address and
               decimal_amount == amount and
               transaction['memo'] == memo):
                return transaction

        return None


golos = Golos()
