import asyncio
import logging
from pathlib import Path

from app.db import SessionLocal
from app.ingest import ingest_dataset, load_dataset

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
logger = logging.getLogger(__name__)


async def main() -> None:
    dataset = load_dataset(DATA_DIR)
    async with SessionLocal() as session:
        counts = await ingest_dataset(session, dataset)
        await session.commit()
    logger.info("Seeded Career Quest dataset: %s", counts)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
