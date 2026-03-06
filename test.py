import asyncio
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.db.models.layer import LayerFeature
import traceback

async def test():
    try:
        async with SessionLocal() as session:
            stmt = select(func.count(LayerFeature.id)).where(LayerFeature.layer_id == '53efcc4f-ed84-4660-9fc3-04e4e6df6d9e')
            result = await session.execute(stmt)
            count = result.scalar()
            print('Count is', count)
    except Exception as e:
        traceback.print_exc()

asyncio.run(test())
