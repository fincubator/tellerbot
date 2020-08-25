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
from contextvars import ContextVar

from aiogram.dispatcher.storage import BaseStorage
from motor.motor_asyncio import AsyncIOMotorClient

from src.config import config


try:
    with open(config.DATABASE_PASSWORD_FILENAME, "r") as password_file:
        client = AsyncIOMotorClient(
            config.DATABASE_HOST,
            config.DATABASE_PORT,
            username=config.DATABASE_USERNAME,
            password=password_file.read(),
        )
except (AttributeError, FileNotFoundError):
    client = AsyncIOMotorClient(config.DATABASE_HOST)
database = client[config.DATABASE_NAME]

database_user: ContextVar[typing.Mapping[str, typing.Any]] = ContextVar("database_user")


class MongoStorage(BaseStorage):
    """MongoDB asynchronous storage for FSM using motor."""

    async def get_state(self, user: int, **kwargs) -> typing.Optional[str]:
        """Get current state of user with Telegram ID ``user``."""
        document = await database.users.find_one({"id": user})
        return document.get("state") if document else None

    async def set_state(
        self, user: int, state: typing.Optional[str] = None, **kwargs
    ) -> None:
        """Set new state ``state`` of user with Telegram ID ``user``."""
        if state is None:
            await database.users.update_one({"id": user}, {"$unset": {"state": True}})
        else:
            await database.users.update_one({"id": user}, {"$set": {"state": state}})

    async def get_data(self, user: int, **kwargs) -> typing.Dict:
        """Get state data of user with Telegram ID ``user``."""
        document = await database.users.find_one({"id": user})
        return document.get("data", {})

    async def set_data(
        self, user: int, data: typing.Optional[typing.Dict] = None, **kwargs
    ) -> None:
        """Set state data ``data`` of user with Telegram ID ``user``."""
        if data is None:
            await database.users.update_one({"id": user}, {"$unset": {"data": True}})
        else:
            await database.users.update_one({"id": user}, {"$set": {"data": data}})

    async def update_data(
        self, user: int, data: typing.Optional[typing.Dict] = None, **kwargs
    ) -> None:
        """Update data of user with Telegram ID ``user``."""
        if data is None:
            data = {}
        data.update(kwargs)
        await database.users.update_one(
            {"id": user},
            {"$set": {f"data.{key}": value for key, value in data.items()}},
        )

    async def reset_state(self, user: int, with_data: bool = True, **kwargs):
        """Reset state for user with Telegram ID ``user``."""
        update = {"$unset": {"state": True}}
        if with_data:
            update["$unset"]["data"] = True
        await database.users.update_one({"id": user}, update)

    async def finish(self, user: int, **kwargs):
        """Finish conversation with user."""
        await self.set_state(user=user, state=None)

    async def wait_closed(self) -> None:
        """Do nothing.

        Motor client does not use this method.
        """

    async def close(self):
        """Disconnect from MongoDB."""
        client.close()
