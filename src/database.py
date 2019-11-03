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

from aiogram.dispatcher.storage import BaseStorage
from motor.motor_asyncio import AsyncIOMotorClient

from src.config import DATABASE_NAME


client = AsyncIOMotorClient()
database = client[DATABASE_NAME]

STATE_KEY = 'state'


class MongoStorage(BaseStorage):
    """MongoDB asynchronous storage for FSM using motor."""

    async def get_state(self, user: int, **kwargs) -> typing.Optional[str]:
        """Get current state of user with Telegram ID ``user``."""
        document = await database.users.find_one({'id': user})
        return document.get(STATE_KEY) if document else None

    async def set_state(
        self, user: int, state: typing.Optional[str] = None, **kwargs
    ) -> None:
        """Set new state ``state`` of user with Telegram ID ``user``."""
        if state is None:
            await database.users.update_one({'id': user}, {'$unset': {STATE_KEY: True}})
        else:
            await database.users.update_one({'id': user}, {'$set': {STATE_KEY: state}})

    async def finish(self, user, **kwargs):
        """Finish conversation with user."""
        await self.set_state(user=user, state=None)

    async def wait_closed(self) -> None:
        """Do nothing.

        Motor client does not use this method.
        """

    async def close(self):
        """Disconnect from MongoDB."""
        client.close()


storage = MongoStorage()
