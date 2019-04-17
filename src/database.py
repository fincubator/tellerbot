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

from motor.motor_asyncio import AsyncIOMotorClient
from aiogram.dispatcher.storage import BaseStorage

client = AsyncIOMotorClient()
database = client.tellerbot

STATE_KEY = 'state'


class MongoStorage(BaseStorage):
    async def get_state(self, user, **kwargs):
        document = await database.users.find_one({'id': user})
        return document.get(STATE_KEY) if document else None

    async def set_state(self, user, state=None, **kwargs):
        if state is None:
            update = {'$unset': {STATE_KEY: True}}
        else:
            update = {'$set': {STATE_KEY: state}}
        await database.users.update_one({'id': user}, update)

    async def finish(self, user, **kwargs):
        await self.set_state(user=user, state=None)

    async def wait_closed(self):
        pass

    async def close(self):
        client.close()


storage = MongoStorage()
