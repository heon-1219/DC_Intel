from apscheduler.triggers.interval import IntervalTrigger

from app.scheduler import JOB_IDS, build_scheduler


def test_scheduler_registers_price_jobs():
    sched = build_scheduler(run=False)
    ids = {j.id for j in sched.get_jobs()}
    assert {"poll_prices_krx", "poll_prices_us", "poll_indexes", "heartbeat"} <= ids
    assert set(JOB_IDS) <= ids


def test_scheduler_registers_all_jobs_including_indicators():
    sched = build_scheduler(run=False)
    ids = {j.id for j in sched.get_jobs()}
    assert ids == {"poll_prices_krx", "poll_prices_us", "poll_indexes",
                   "heartbeat", "recompute_indicators"}


def test_recompute_indicators_runs_every_5_min():
    sched = build_scheduler(run=False)
    job = sched.get_job("recompute_indicators")
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == 300
