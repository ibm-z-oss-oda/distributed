from __future__ import annotations

import pytest
from tornado.httpclient import AsyncHTTPClient

from distributed import Semaphore
from distributed.utils_test import gen_cluster


@gen_cluster(client=True, clean_kwargs={"threads": False})
async def test_prometheus_collect_task_states(c, s, a, b):
    pytest.importorskip("prometheus_client")
    from prometheus_client.parser import text_string_to_metric_families

    http_client = AsyncHTTPClient()

    async def fetch_metrics():
        port = s.http_server.port
        response = await http_client.fetch(f"http://localhost:{port}/metrics")
        txt = response.body.decode("utf8")
        families = {
            family.name: family
            for family in text_string_to_metric_families(txt)
            if family.name.startswith("dask_semaphore_")
        }
        return families

    active_metrics = await fetch_metrics()

    expected_metrics = {
        "dask_semaphore_max_leases",
        "dask_semaphore_active_leases",
        "dask_semaphore_pending_leases",
        "dask_semaphore_acquire",
        "dask_semaphore_release",
        "dask_semaphore_average_pending_lease_time_s",
    }

    assert active_metrics.keys() == expected_metrics
    for v in active_metrics.values():  # Not yet any semaphore created
        assert v.samples == []

    sem = await Semaphore(name="test", max_leases=2)

    active_metrics = await fetch_metrics()
    assert active_metrics.keys() == expected_metrics
    # Assert values are set upon intialization
    for name, v in active_metrics.items():
        samples = v.samples
        assert len(samples) == 1
        sample = samples.pop()
        assert sample.labels["name"] == "test"
        if name == "dask_semaphore_max_leases":
            assert sample.value == 2
        else:
            assert sample.value == 0

    assert await sem.acquire()
    active_metrics = await fetch_metrics()
    assert active_metrics["dask_semaphore_max_leases"].samples[0].value == 2
    assert active_metrics["dask_semaphore_active_leases"].samples[0].value == 1
    assert (
        active_metrics["dask_semaphore_average_pending_lease_time_s"].samples[0].value
        > 0
    )
    assert active_metrics["dask_semaphore_acquire"].samples[0].value == 1
    assert active_metrics["dask_semaphore_release"].samples[0].value == 0
    assert active_metrics["dask_semaphore_pending_leases"].samples[0].value == 0

    assert await sem.release() is True
    active_metrics = await fetch_metrics()
    assert active_metrics["dask_semaphore_max_leases"].samples[0].value == 2
    assert active_metrics["dask_semaphore_active_leases"].samples[0].value == 0
    assert (
        active_metrics["dask_semaphore_average_pending_lease_time_s"].samples[0].value
        > 0
    )
    assert active_metrics["dask_semaphore_acquire"].samples[0].value == 1
    assert active_metrics["dask_semaphore_release"].samples[0].value == 1
    assert active_metrics["dask_semaphore_pending_leases"].samples[0].value == 0

    await sem.close()
    active_metrics = await fetch_metrics()
    assert active_metrics.keys() == expected_metrics
    for v in active_metrics.values():
        assert v.samples == []
