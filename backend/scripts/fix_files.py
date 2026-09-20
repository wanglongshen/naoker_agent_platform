import asyncio, sys
sys.path.insert(0, ".")
from app.db.session import async_session_factory
from sqlalchemy import select, update
from app.models.file import FileObject, FileFolder

async def fix():
    async with async_session_factory() as s:
        # Fix: set filename = original_filename where filename looks like a UUID
        files = (await s.execute(
            select(FileObject).where(FileObject.original_filename != FileObject.filename)
        )).scalars().all()

        for f in files:
            old = f.filename
            f.filename = f.original_filename
            s.add(f)
            print(f"  Fixed: {old[:20]}... -> {f.filename}")

        await s.flush()

        # Fix: recalculate child_file_count for all folders
        folders = (await s.execute(
            select(FileFolder).where(FileFolder.is_deleted == False)
        )).scalars().all()

        for folder in folders:
            count = (await s.execute(
                select(FileObject).where(
                    FileObject.folder_id == folder.id,
                    FileObject.is_deleted == False,
                )
            )).scalars().all()
            actual = len(count)
            if folder.child_file_count != actual:
                folder.child_file_count = actual
                s.add(folder)
                print(f"  Fixed count: {folder.name} {folder.child_file_count} -> {actual}")

        await s.commit()
        print("Done!")

asyncio.run(fix())
