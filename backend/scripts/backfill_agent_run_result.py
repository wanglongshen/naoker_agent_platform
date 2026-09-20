"""One-time, idempotent backfill of AgentRun.result for historical succeeded runs.

Usage:
    cd backend
    PYTHONPATH=. python scripts/backfill_agent_run_result.py

Runs can also be invoked with --dry-run to preview without writing.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_agent_run_result")


def _get_test_db_url() -> str:
    from app.core.config import get_settings
    settings = get_settings()
    return settings.test_database_url or settings.database_url


async def _backfill(dry_run: bool = False) -> dict[str, int]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.agent import AgentRun, AgentRunEvent

    db_url = _get_test_db_url()
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    stats = {"total": 0, "filled": 0, "no_answer": 0, "errors": 0}

    try:
        async with session_factory() as s:
            result = await s.execute(
                select(AgentRun).where(
                    AgentRun.status == "succeeded",
                    AgentRun.result.is_(None),
                )
            )
            runs = list(result.scalars().all())
            stats["total"] = len(runs)
            logger.info("Found %d succeeded runs without result", len(runs))

            for run in runs:
                try:
                    events_result = await s.execute(
                        select(AgentRunEvent)
                        .where(AgentRunEvent.run_id == run.id)
                        .order_by(AgentRunEvent.seq.desc())
                    )
                    events = list(events_result.scalars().all())

                    final_answer = None
                    source_event_sequence = None
                    for event in events:
                        if event.event_type == "run_succeeded" and "final_answer" in event.payload:
                            final_answer = event.payload["final_answer"]
                            source_event_sequence = event.seq
                            break
                        if event.event_type == "answer_completed" and "text" in event.payload:
                            final_answer = event.payload["text"]
                            source_event_sequence = event.seq
                            break

                    if final_answer:
                        run.result = {
                            "final_answer": final_answer,
                            "answer_format": "markdown",
                            "completed_at": run.updated_at.isoformat().replace("+00:00", "Z"),
                            "source_event_sequence": source_event_sequence,
                        }
                        if not dry_run:
                            await s.commit()
                        stats["filled"] += 1
                        logger.info(
                            "Backfilled run_id=%s, seq=%s, answer_len=%d",
                            run.id, source_event_sequence, len(final_answer),
                        )
                    else:
                        stats["no_answer"] += 1
                        logger.warning(
                            "No answer found for succeeded run_id=%s", run.id,
                        )
                except Exception:
                    stats["errors"] += 1
                    logger.exception("Error backfilling run_id=%s", run.id)
                    await s.rollback()

    finally:
        await engine.dispose()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill AgentRun.result for historical runs")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    stats = asyncio.run(_backfill(dry_run=args.dry_run))

    logger.info(
        "Backfill complete: total=%d filled=%d no_answer=%d errors=%d",
        stats["total"], stats["filled"], stats["no_answer"], stats["errors"],
    )

    if stats["no_answer"] > 0:
        logger.warning(
            "WARNING: %d succeeded runs have no answer to backfill — "
            "these should be investigated.", stats["no_answer"]
        )

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
