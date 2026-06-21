from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# job id -> interval in minutes. Prices/heartbeat every 1 min; indicators every 5 (§10.2);
# intel scrape + sentiment aggregation every 10 (market-intel §14 / sentiment §10).
JOB_INTERVALS = {
    "poll_prices_krx": 1, "poll_prices_us": 1, "poll_indexes": 1,
    "heartbeat": 1, "recompute_indicators": 5, "build_dashboard": 1,
    "intel_scrape": 10, "aggregate_sentiment": 10, "intel_anomaly_scan": 5,
    "intel_confirmation_match": 10, "outcome_checker": 1,
}
# job id -> daily cron (UTC). sync_calendar 21:30 UTC = 06:30 KST (§11.1);
# econ_event_study 02:00 UTC after the sync (§11.4); intel author-stats/retention ~03:00/03:30 KST.
JOB_CRONS = {
    "sync_calendar": {"hour": 21, "minute": 30},
    "econ_event_study": {"hour": 2, "minute": 0},
    "intel_author_stats": {"hour": 18, "minute": 0},
    "intel_retention": {"hour": 18, "minute": 30},
    "db_backup": {"hour": 19, "minute": 30},          # 04:30 KST — quietest cross-market window
    "win_rate_monitor": {"hour": 22, "minute": 30},   # 07:30 KST
}
JOB_IDS = list(JOB_INTERVALS) + list(JOB_CRONS)


async def _noop():
    return None


def build_scheduler(*, run: bool = True, jobs: dict | None = None) -> AsyncIOScheduler:
    """Register the M1+M2+M3 jobs. `jobs` maps id -> coroutine fn (prod callables injected by
    main.py's lifespan); defaults to no-ops so unit tests can introspect registration."""
    jobs = jobs or {jid: _noop for jid in JOB_IDS}
    sched = AsyncIOScheduler(timezone="UTC")
    for jid, minutes in JOB_INTERVALS.items():
        sched.add_job(jobs[jid], IntervalTrigger(minutes=minutes), id=jid,
                      max_instances=1, coalesce=True)
    for jid, cron in JOB_CRONS.items():
        sched.add_job(jobs[jid], CronTrigger(timezone="UTC", **cron), id=jid,
                      max_instances=1, coalesce=True)
    if run:
        sched.start()
    return sched
