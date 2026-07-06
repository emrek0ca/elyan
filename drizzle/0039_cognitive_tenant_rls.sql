CREATE OR REPLACE FUNCTION elyan_current_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'elyan_brain_worker') THEN
    CREATE ROLE elyan_brain_worker
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END $$;

DROP POLICY IF EXISTS cognitive_facts_tenant_policy ON brain_memory_facts;
CREATE POLICY cognitive_facts_tenant_policy ON brain_memory_facts
  USING (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'))
  WITH CHECK (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'));

DROP POLICY IF EXISTS cognitive_episodes_tenant_policy ON brain_memory_episodes;
CREATE POLICY cognitive_episodes_tenant_policy ON brain_memory_episodes
  USING (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'))
  WITH CHECK (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'));

DROP POLICY IF EXISTS cognitive_dialogue_tenant_policy ON dialogue_states;
CREATE POLICY cognitive_dialogue_tenant_policy ON dialogue_states
  USING (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'))
  WITH CHECK (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'));

DROP POLICY IF EXISTS cognitive_revision_tenant_policy ON cognitive_memory_revisions;
CREATE POLICY cognitive_revision_tenant_policy ON cognitive_memory_revisions
  USING (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'))
  WITH CHECK (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'));

DROP POLICY IF EXISTS cognitive_outbox_tenant_policy ON cognitive_mutation_outbox;
CREATE POLICY cognitive_outbox_tenant_policy ON cognitive_mutation_outbox
  USING (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'))
  WITH CHECK (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'));

ALTER TABLE dialogue_states VALIDATE CONSTRAINT dialogue_states_session_user_fk;
ALTER TABLE chat_messages VALIDATE CONSTRAINT chat_messages_session_user_fk;
ALTER TABLE session_goals VALIDATE CONSTRAINT session_goals_session_user_fk;
ALTER TABLE proactive_triggers VALIDATE CONSTRAINT proactive_triggers_session_user_fk;
ALTER TABLE cognitive_mutation_outbox VALIDATE CONSTRAINT cognitive_outbox_session_user_fk;

-- RLS activation is deliberately performed by the bootstrap script after the
-- integrity preflight and restricted-role provisioning. Schema installation
-- alone must not change production request behavior while the flag is off.
