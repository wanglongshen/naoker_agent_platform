import asyncio, sys
sys.path.insert(0, ".")
from app.db.session import async_session_factory
from sqlalchemy import select
from app.models.file import FileFolder

async def check():
    async with async_session_factory() as s:
        folders = (await s.execute(select(FileFolder).where(FileFolder.is_deleted == False))).scalars().all()
        print(f"Folders: {len(folders)}")
        for f in folders:
            print(f"  {f.name} (id={f.id}, path={f.path}, parent={f.parent_folder_id}, depth={f.depth})")

asyncio.run(check())
