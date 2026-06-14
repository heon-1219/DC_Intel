from app.scheduler import JOB_IDS, build_scheduler


def test_scheduler_registers_price_jobs():
    sched = build_scheduler(run=False)
    ids = {j.id for j in sched.get_jobs()}
    assert {"poll_prices_krx", "poll_prices_us", "poll_indexes", "heartbeat"} <= ids
    assert set(JOB_IDS) <= ids
