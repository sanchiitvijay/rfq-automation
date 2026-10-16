"""One-off copy of the RFQ Agent data from Postgres to the SQLite file.

    .venv/bin/python scripts/migrate_pg_to_sqlite.py postgresql+asyncpg://localhost/rfq [--replace]

Copies jobs, items, events, edits and sends (in that order, so foreign keys hold), then checks that
every table has the same number of rows on both sides. Refuses to run into a non-empty SQLite file
unless --replace is given. Needs asyncpg (pip install asyncpg) for the source only.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from backend.app.db import create_tables, dispose, engine  # noqa: E402
from backend.app.models import Job, JobEdit, JobEvent, JobItem, JobSend  # noqa: E402

ORDER = [Job, JobItem, JobEvent, JobEdit, JobSend]


async def main(source_url: str, replace: bool) -> int:
    await create_tables()
    target = engine()
    async with target.connect() as conn:
        existing = (await conn.execute(select(func.count()).select_from(Job.__table__))).scalar_one()
    if existing and not replace:
        print(f"The SQLite database already has {existing} jobs; run again with --replace to overwrite it.")
        return 1
    source = create_async_engine(source_url)
    try:
        async with source.connect() as src, target.begin() as dst:
            if replace:
                for model in reversed(ORDER):
                    await dst.execute(delete(model.__table__))
            for model in ORDER:
                table = model.__table__
                rows = (await src.execute(text(f"SELECT * FROM {table.name}"))).mappings().all()
                columns = {c.name for c in table.columns}
                batch = [{k: v for k, v in row.items() if k in columns} for row in rows]
                for i in range(0, len(batch), 200):
                    await dst.execute(table.insert(), batch[i:i + 200])
                print(f"{table.name}: copied {len(batch)} rows")
        async with source.connect() as src, target.connect() as dst:
            ok = True
            for model in ORDER:
                name = model.__table__.name
                a = (await src.execute(text(f"SELECT count(*) FROM {name}"))).scalar_one()
                b = (await dst.execute(select(func.count()).select_from(model.__table__))).scalar_one()
                print(f"  check {name}: postgres {a} = sqlite {b}" + ("" if a == b else "  <-- MISMATCH"))
                ok &= a == b
        return 0 if ok else 2
    finally:
        await source.dispose()
        await dispose()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(sys.argv[1], "--replace" in sys.argv)))
