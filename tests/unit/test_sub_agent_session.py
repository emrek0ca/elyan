from core.sub_agent.session import SessionState, SubAgentSession, SubAgentTask


def test_sub_agent_session_defaults():
    task = SubAgentTask(name="Araştır")
    sess = SubAgentSession(
        session_id="agent:root:subagent:test",
        parent_session_id="root",
        specialist_key="researcher",
        task=task,
    )

    assert sess.state == SessionState.PENDING
    assert sess.task.name == "Araştır"
    assert sess.can_spawn is False
    assert sess.pipeline_state is not None
