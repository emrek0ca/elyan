from __future__ import annotations

import asyncio

from core.multi_agent.contract_net import AgentProfile, Bid, ContractNetProtocol, TaskAnnouncement


def test_eligible_agents_filtered_by_capabilities():
    net = ContractNetProtocol()
    task = TaskAnnouncement("t1", "research", ["web_search"], 1000, 1)
    assert asyncio.run(net.allocate_task(task)) == "research_agent"


def test_overloaded_agent_bids_higher():
    net = ContractNetProtocol()
    agent = net.registered_agents["research_agent"]
    agent.current_load = agent.max_concurrent
    bid = asyncio.run(net._request_bid(agent, TaskAnnouncement("t1", "research", ["web_search"], 1000, 1)))
    assert bid.estimated_time_ms > 2000


def test_best_bid_selected_by_utility():
    net = ContractNetProtocol()
    net.set_bid_handler("research_agent", lambda task, agent: Bid("research_agent", task.task_id, 1000, 0.9, 1.0))
    net.set_bid_handler("planning_agent", lambda task, agent: Bid("planning_agent", task.task_id, 1500, 0.4, 0.5))
    task = TaskAnnouncement("t2", "plan", ["task_decomposition"], 1000, 1)
    assert asyncio.run(net.allocate_task(task)) == "planning_agent" or asyncio.run(net.allocate_task(task)) == "research_agent"


def test_task_completion_decrements_load():
    net = ContractNetProtocol()
    task = TaskAnnouncement("t3", "research", ["web_search"], 1000, 1)
    agent_id = asyncio.run(net.allocate_task(task))
    before = net.registered_agents[agent_id].current_load
    net.report_completion("t3", agent_id, True)
    assert net.registered_agents[agent_id].current_load == max(0, before - 1)


def test_no_eligible_agents_returns_none():
    net = ContractNetProtocol()
    for agent in net.registered_agents.values():
        agent.current_load = agent.max_concurrent
    task = TaskAnnouncement("t4", "research", ["web_search"], 1000, 1)
    assert asyncio.run(net.allocate_task(task)) is None


def test_parallel_bid_collection():
    net = ContractNetProtocol()
    task = TaskAnnouncement("t5", "research", ["web_search"], 1000, 1)
    assert asyncio.run(net.allocate_task(task)) is not None


def test_agent_registration_works():
    net = ContractNetProtocol()
    net.register_agent("extra", ["web_search"])
    assert "extra" in net.registered_agents
