from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

JOB_IDS = ["poll_prices_krx", "poll_prices_us", "poll_indexes", "heartbeat"]


async def _noop():
    return None


def build_scheduler(*, run: bool = True, jobs: dict | None = None) -> AsyncIOScheduler:
    """Register the M1a jobs (all every 1 min). `jobs` maps id -> coroutine fn; the prod
    callables are injected by main.py's lifespan. Defaults to no-ops so unit tests can
    introspect registration without real fetching."""
    jobs = jobs or {jid: _noop for jid in JOB_IDS}
    sched = AsyncIOScheduler(timezone="UTC")
    for jid in JOB_IDS:
        sched.add_job(jobs[jid], IntervalTrigger(minutes=1), id=jid,
                      max_instances=1, coalesce=True)
    if run:
        sched.start()
    return sched
