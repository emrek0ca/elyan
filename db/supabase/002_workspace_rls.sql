-- Elyan workspace row-level security defaults
-- Server code should set request.jwt.claim.workspace_id or run with service role.

alter table if exists public.workspace_memberships enable row level security;
drop policy if exists workspace_memberships_workspace_isolation on public.workspace_memberships;
create policy workspace_memberships_workspace_isolation on public.workspace_memberships using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_devices enable row level security;
drop policy if exists workspace_devices_workspace_isolation on public.workspace_devices;
create policy workspace_devices_workspace_isolation on public.workspace_devices using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_policies enable row level security;
drop policy if exists workspace_policies_workspace_isolation on public.workspace_policies;
create policy workspace_policies_workspace_isolation on public.workspace_policies using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_threads enable row level security;
drop policy if exists workspace_threads_workspace_isolation on public.workspace_threads;
create policy workspace_threads_workspace_isolation on public.workspace_threads using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_thread_snapshots enable row level security;
drop policy if exists workspace_thread_snapshots_workspace_isolation on public.workspace_thread_snapshots;
create policy workspace_thread_snapshots_workspace_isolation on public.workspace_thread_snapshots using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_approvals enable row level security;
drop policy if exists workspace_approvals_workspace_isolation on public.workspace_approvals;
create policy workspace_approvals_workspace_isolation on public.workspace_approvals using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.connector_accounts enable row level security;
drop policy if exists connector_accounts_workspace_isolation on public.connector_accounts;
create policy connector_accounts_workspace_isolation on public.connector_accounts using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.connector_scopes enable row level security;
drop policy if exists connector_scopes_workspace_isolation on public.connector_scopes;
create policy connector_scopes_workspace_isolation on public.connector_scopes using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.connector_health enable row level security;
drop policy if exists connector_health_workspace_isolation on public.connector_health;
create policy connector_health_workspace_isolation on public.connector_health using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.connector_action_traces enable row level security;
drop policy if exists connector_action_traces_workspace_isolation on public.connector_action_traces;
create policy connector_action_traces_workspace_isolation on public.connector_action_traces using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.billing_customers enable row level security;
drop policy if exists billing_customers_workspace_isolation on public.billing_customers;
create policy billing_customers_workspace_isolation on public.billing_customers using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.subscriptions enable row level security;
drop policy if exists subscriptions_workspace_isolation on public.subscriptions;
create policy subscriptions_workspace_isolation on public.subscriptions using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.entitlement_snapshots enable row level security;
drop policy if exists entitlement_snapshots_workspace_isolation on public.entitlement_snapshots;
create policy entitlement_snapshots_workspace_isolation on public.entitlement_snapshots using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.usage_ledger enable row level security;
drop policy if exists usage_ledger_workspace_isolation on public.usage_ledger;
create policy usage_ledger_workspace_isolation on public.usage_ledger using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_audit_index enable row level security;
drop policy if exists workspace_audit_index_workspace_isolation on public.workspace_audit_index;
create policy workspace_audit_index_workspace_isolation on public.workspace_audit_index using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.sync_receipts enable row level security;
drop policy if exists sync_receipts_workspace_isolation on public.sync_receipts;
create policy sync_receipts_workspace_isolation on public.sync_receipts using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_users enable row level security;
drop policy if exists workspace_users_workspace_isolation on public.workspace_users;
create policy workspace_users_workspace_isolation on public.workspace_users using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_user_sessions enable row level security;
drop policy if exists workspace_user_sessions_workspace_isolation on public.workspace_user_sessions;
create policy workspace_user_sessions_workspace_isolation on public.workspace_user_sessions using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_data_policies enable row level security;
drop policy if exists workspace_data_policies_workspace_isolation on public.workspace_data_policies;
create policy workspace_data_policies_workspace_isolation on public.workspace_data_policies using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_user_preference_profiles enable row level security;
drop policy if exists workspace_user_preference_profiles_workspace_isolation on public.workspace_user_preference_profiles;
create policy workspace_user_preference_profiles_workspace_isolation on public.workspace_user_preference_profiles using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_operational_feedback enable row level security;
drop policy if exists workspace_operational_feedback_workspace_isolation on public.workspace_operational_feedback;
create policy workspace_operational_feedback_workspace_isolation on public.workspace_operational_feedback using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));

alter table if exists public.workspace_tool_reliability enable row level security;
drop policy if exists workspace_tool_reliability_workspace_isolation on public.workspace_tool_reliability;
create policy workspace_tool_reliability_workspace_isolation on public.workspace_tool_reliability using (workspace_id = current_setting('request.jwt.claim.workspace_id', true)) with check (workspace_id = current_setting('request.jwt.claim.workspace_id', true));
