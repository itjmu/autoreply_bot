"""SQLite FSM persistence with TTL and atomic update_data."""

import json
from dataclasses import asdict
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.state import State
import database as db


class SQLiteStorage(BaseStorage):
    @staticmethod
    def key(key):
        return json.dumps(asdict(key), sort_keys=True)

    async def set_state(self, key, state=None):
        value = state.state if isinstance(state, State) else state
        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO fsm_state(storage_key,state) VALUES(?,?) ON CONFLICT(storage_key) DO UPDATE SET state=excluded.state,updated_at=CURRENT_TIMESTAMP",
                (self.key(key), value),
            )
            await conn.commit()

    async def get_state(self, key):
        async with db._connect() as conn:
            row = await (
                await conn.execute(
                    "SELECT state FROM fsm_state WHERE storage_key=? AND updated_at>=datetime('now','-1 day')",
                    (self.key(key),),
                )
            ).fetchone()
            return row[0] if row else None

    async def set_data(self, key, data):
        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO fsm_state(storage_key,data) VALUES(?,?) ON CONFLICT(storage_key) DO UPDATE SET data=excluded.data,updated_at=CURRENT_TIMESTAMP",
                (self.key(key), json.dumps(dict(data))),
            )
            await conn.commit()

    async def get_data(self, key):
        async with db._connect() as conn:
            row = await (
                await conn.execute(
                    "SELECT data FROM fsm_state WHERE storage_key=? AND updated_at>=datetime('now','-1 day')",
                    (self.key(key),),
                )
            ).fetchone()
            return json.loads(row[0]) if row else {}

    async def update_data(self, key, data):
        async with db._connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            row = await (
                await conn.execute(
                    "SELECT data FROM fsm_state WHERE storage_key=?", (self.key(key),)
                )
            ).fetchone()
            updated = json.loads(row[0]) if row else {}
            updated.update(data)
            await conn.execute(
                "INSERT INTO fsm_state(storage_key,data) VALUES(?,?) ON CONFLICT(storage_key) DO UPDATE SET data=excluded.data,updated_at=CURRENT_TIMESTAMP",
                (self.key(key), json.dumps(updated)),
            )
            await conn.commit()
            return updated

    async def close(self):
        pass
