from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# job id -> interval in minutes. Prices/heartbeat every 1 min; indicators every 5 (§10.2).
JOB_INTERVALS = {
    "poll_prices_krx": 1, "poll_prices_us": 1, "poll_indexes": 1,
    "heartbeat": 1, "recompute_indicators": 5,
}
JOB_IDS = list(JOB_INTERVALS)


async def _noop():
    return None


def build_scheduler(*, run: bool = True, jobs: dict | None = None) -> AsyncIOScheduler:
    """Register the M1+M2 jobs. `jobs` maps id -> coroutine fn (prod callables injected by
    main.py's lifespan); defaults to no-ops so unit tests can introspect registration."""
    jobs = jobs or {jid: _noop for jid in JOB_IDS}
    sched = AsyncIOScheduler(timezone="UTC")
    for jid in JOB_IDS:
        sched.add_job(jobs[jid], IntervalTrigger(minutes=JOB_INTERVALS[jid]), id=jid,
                      max_instances=1, coalesce=True)
    if run:
        sched.start()
    return sched
