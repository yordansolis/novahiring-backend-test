"""
Delete all interview session data while preserving seeded reference data.

Deletes:
  - messages          (all)
  - chat_sessions     (all)
  - ai_call_logs      (all)
  - dimension_scores  where evaluation_id is a UUID (interview-generated)
  - evaluations       where id is a UUID (interview-generated)
  - Redis session:*   keys

Preserves:
  - job_openings, candidates, prompt_versions, question_bank
  - evaluations with id LIKE 'eval-%'  (seeded reference data)
  - dimension_scores linked to those evaluations

Usage:
  uv run python clean_sessions.py
"""

import asyncio

from sqlalchemy import delete, text

from database import async_session_factory, get_redis
from models.evaluation import DimensionScoreRecord, Evaluation
from models.ops import AICallLog, ChatSession, Message


async def clean():
    async with async_session_factory() as session:
        async with session.begin():
            r_msg = await session.execute(delete(Message))
            r_ses = await session.execute(delete(ChatSession))
            r_log = await session.execute(delete(AICallLog))
            r_dim = await session.execute(
                delete(DimensionScoreRecord).where(
                    text("evaluation_id NOT LIKE 'eval-%'")
                )
            )
            r_eval = await session.execute(
                delete(Evaluation).where(
                    text("id NOT LIKE 'eval-%'")
                )
            )

    redis = get_redis()
    keys = await redis.keys("session:*")
    if keys:
        await redis.delete(*keys)
    await redis.aclose()

    print(f"messages deleted:         {r_msg.rowcount}")
    print(f"chat_sessions deleted:    {r_ses.rowcount}")
    print(f"ai_call_logs deleted:     {r_log.rowcount}")
    print(f"dimension_scores deleted: {r_dim.rowcount}")
    print(f"evaluations deleted:      {r_eval.rowcount}")
    print(f"redis session keys:       {len(keys)}")
    print("✓ Session data cleared. Seeded reference data preserved.")


if __name__ == "__main__":
    asyncio.run(clean())
