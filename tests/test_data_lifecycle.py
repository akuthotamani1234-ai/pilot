"""QX-A05: synthetic records stay with one run and one worker."""
import pytest

from backend.data_lifecycle import Lifecycle, customer_data, plan_for_workers


def test_each_worker_gets_its_own_tagged_records():
    life = Lifecycle("run_20261117_ab", "staging")
    first = life.prepare(1)
    second = life.prepare(2)
    assert [row["kind"] for row in first] == ["account", "cart", "order"]
    assert all(row["run_id"] == "run_20261117_ab" and row["source"] == "synthetic" for row in first)
    assert first[0]["email"].endswith("@example.com")
    assert "w1" in first[0]["tag"] and "w2" in second[0]["tag"]
    assert {row["tag"] for row in life.for_worker(1)}.isdisjoint({row["tag"] for row in life.for_worker(2)})
    again = life.prepare(1)
    assert [row["tag"] for row in again] == [row["tag"] for row in first]


def test_a_case_starts_only_from_a_reset_and_cleanup_removes_that_run():
    life = Lifecycle("run-1", "test")
    life.prepare(1)
    life.begin_case(1, "open-saree")
    with pytest.raises(ValueError, match="known reset"):
        life.begin_case(1, "second")
    life.reset(1)
    life.begin_case(1, "second")
    cleaned = life.cleanup(1)
    assert len(cleaned) == 3
    assert life.for_worker(1) == []
    assert all(row["state"] == "cleaned" and row["run_id"] == "run-1" for row in cleaned)


def test_cleanup_of_one_worker_leaves_the_other():
    life = Lifecycle("run-1", "test")
    life.prepare(1)
    life.prepare(2)
    life.cleanup(1)
    assert life.for_worker(1) == []
    assert len(life.for_worker(2)) == 3


def test_production_and_customer_addresses_are_refused():
    with pytest.raises(ValueError, match="production customer data"):
        Lifecycle("run-1", "production")
    refused, reason = customer_data("shopper@gmail.com")
    assert refused and "production customer data" in reason
    ok, _reason = customer_data("qa-run-1-w1-account@example.com")
    assert not ok
    life = Lifecycle("run-1", "test")
    life.prepare(1)
    with pytest.raises(ValueError, match="production customer data"):
        life.claim(1, "shopper@gmail.com")
    assert life.claim(1, "qa-run-1-w1-account@example.com").endswith("@example.com")


def test_the_swarm_plan_is_one_isolated_pack_per_worker():
    packs = plan_for_workers("run-9", "staging", [2, 1, 2])
    assert [pack["worker"] for pack in packs] == [1, 2]
    assert all(pack["reset"] and pack["isolated"] and len(pack["records"]) == 3 for pack in packs)
    assert packs[0]["cleanup"] == [row["tag"] for row in packs[0]["records"]]
    refused = plan_for_workers("run-9", "prod", [1])
    assert refused[0]["records"] == []
    assert "production customer data" in refused[0]["refused"]
    assert plan_for_workers("run-9", "test", []) == []
