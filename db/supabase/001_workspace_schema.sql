-- Elyan workspace schema for Supabase/Postgres
-- Generated from runtime metadata. Apply with a service role or direct postgres access.
create extension if not exists pgcrypto;


CREATE TABLE billing_customers (
	workspace_id VARCHAR(128) NOT NULL, 
	billing_customer VARCHAR(128) NOT NULL, 
	stripe_customer_id VARCHAR(128) NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (workspace_id)
)

;


CREATE TABLE connector_accounts (
	account_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	connector_name VARCHAR(64) NOT NULL, 
	provider VARCHAR(64) NOT NULL, 
	display_name VARCHAR(256) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	scopes_json TEXT NOT NULL, 
	metadata_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (account_id)
)

;

CREATE INDEX ix_connector_accounts_workspace_updated ON connector_accounts (workspace_id, updated_at);


CREATE TABLE connector_action_traces (
	trace_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	connector_account_id VARCHAR(128) NOT NULL, 
	connector_name VARCHAR(64) NOT NULL, 
	event_type VARCHAR(128) NOT NULL, 
	payload_json TEXT NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (trace_id)
)

;

CREATE INDEX ix_connector_action_traces_workspace_created ON connector_action_traces (workspace_id, created_at);


CREATE TABLE connector_definitions (
	connector_name VARCHAR(64) NOT NULL, 
	provider VARCHAR(64) NOT NULL, 
	label VARCHAR(128) NOT NULL, 
	capabilities_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (connector_name)
)

;


CREATE TABLE connector_health (
	health_id VARCHAR(128) NOT NULL, 
	account_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	payload_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (health_id)
)

;

CREATE INDEX ix_connector_health_workspace_updated ON connector_health (workspace_id, updated_at);


CREATE TABLE connector_scopes (
	scope_id VARCHAR(128) NOT NULL, 
	account_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	scope VARCHAR(128) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (scope_id)
)

;

CREATE INDEX ix_connector_scopes_workspace_account ON connector_scopes (workspace_id, account_id);


CREATE TABLE entitlement_snapshots (
	snapshot_id VARCHAR(96) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	scope VARCHAR(64) NOT NULL, 
	payload_json TEXT NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (snapshot_id)
)

;

CREATE INDEX ix_entitlement_snapshots_scope_updated ON entitlement_snapshots (scope, created_at);


CREATE TABLE subscriptions (
	workspace_id VARCHAR(128) NOT NULL, 
	plan_id VARCHAR(64) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	current_period_end FLOAT NOT NULL, 
	payload_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (workspace_id)
)

;


CREATE TABLE sync_receipts (
	event_id VARCHAR(96) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	accepted_at FLOAT NOT NULL, 
	PRIMARY KEY (event_id)
)

;


CREATE TABLE usage_ledger (
	usage_id VARCHAR(96) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	metric VARCHAR(64) NOT NULL, 
	amount INTEGER NOT NULL, 
	payload_json TEXT NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (usage_id)
)

;


CREATE TABLE workspace_approvals (
	request_id VARCHAR(64) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	payload_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (request_id)
)

;


CREATE TABLE workspace_audit_index (
	event_id VARCHAR(96) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	event_type VARCHAR(128) NOT NULL, 
	payload_json TEXT NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (event_id)
)

;

CREATE INDEX ix_workspace_audit_index_type_created ON workspace_audit_index (event_type, created_at);


CREATE TABLE workspace_data_policies (
	workspace_id VARCHAR(128) NOT NULL, 
	allow_product_analytics BOOLEAN NOT NULL, 
	allow_non_personal_learning BOOLEAN NOT NULL, 
	allow_personal_data_learning BOOLEAN NOT NULL, 
	allow_support_access BOOLEAN NOT NULL, 
	metadata_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (workspace_id)
)

;


CREATE TABLE workspace_devices (
	device_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	platform VARCHAR(64) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	metadata_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (device_id)
)

;

CREATE INDEX ix_workspace_devices_workspace_updated ON workspace_devices (workspace_id, updated_at);


CREATE TABLE workspace_memberships (
	membership_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	actor_id VARCHAR(128) NOT NULL, 
	role VARCHAR(64) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (membership_id)
)

;

CREATE INDEX ix_workspace_memberships_workspace_actor ON workspace_memberships (workspace_id, actor_id);


CREATE TABLE workspace_operational_feedback (
	feedback_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	user_id VARCHAR(128) NOT NULL, 
	category VARCHAR(64) NOT NULL, 
	entity_id VARCHAR(128) NOT NULL, 
	outcome VARCHAR(32) NOT NULL, 
	reward FLOAT NOT NULL, 
	latency_ms FLOAT NOT NULL, 
	recovery_count INTEGER NOT NULL, 
	payload_json TEXT NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (feedback_id)
)

;

CREATE INDEX ix_workspace_operational_feedback_workspace_created ON workspace_operational_feedback (workspace_id, created_at);


CREATE TABLE workspace_policies (
	policy_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	policy_type VARCHAR(64) NOT NULL, 
	payload_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (policy_id)
)

;

CREATE INDEX ix_workspace_policies_workspace_type ON workspace_policies (workspace_id, policy_type);


CREATE TABLE workspace_thread_snapshots (
	snapshot_id VARCHAR(96) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	thread_id VARCHAR(64) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	payload_json TEXT NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (snapshot_id)
)

;

CREATE INDEX ix_workspace_thread_snapshots_workspace_created ON workspace_thread_snapshots (workspace_id, created_at);


CREATE TABLE workspace_threads (
	thread_id VARCHAR(64) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	current_mode VARCHAR(32) NOT NULL, 
	summary_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (thread_id)
)

;

CREATE INDEX ix_workspace_threads_workspace_updated ON workspace_threads (workspace_id, updated_at);


CREATE TABLE workspace_tool_reliability (
	stat_id VARCHAR(160) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	scope VARCHAR(64) NOT NULL, 
	tool_name VARCHAR(128) NOT NULL, 
	success_count INTEGER NOT NULL, 
	failure_count INTEGER NOT NULL, 
	sample_count INTEGER NOT NULL, 
	avg_reward FLOAT NOT NULL, 
	avg_latency_ms FLOAT NOT NULL, 
	metadata_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (stat_id)
)

;

CREATE INDEX ix_workspace_tool_reliability_workspace_updated ON workspace_tool_reliability (workspace_id, updated_at);


CREATE TABLE workspace_user_preference_profiles (
	profile_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	user_id VARCHAR(128) NOT NULL, 
	explanation_style VARCHAR(64) NOT NULL, 
	approval_sensitivity_hint VARCHAR(64) NOT NULL, 
	preferred_route VARCHAR(64) NOT NULL, 
	preferred_model VARCHAR(128) NOT NULL, 
	task_templates_json TEXT NOT NULL, 
	metadata_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (profile_id)
)

;

CREATE UNIQUE INDEX ix_workspace_user_preference_profiles_workspace_user ON workspace_user_preference_profiles (workspace_id, user_id);


CREATE TABLE workspace_user_sessions (
	session_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	user_id VARCHAR(128) NOT NULL, 
	session_token_hash VARCHAR(128) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	expires_at FLOAT NOT NULL, 
	last_seen_at FLOAT NOT NULL, 
	metadata_json TEXT NOT NULL, 
	created_at FLOAT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (session_id), 
	UNIQUE (session_token_hash)
)

;

CREATE INDEX ix_workspace_user_sessions_workspace_updated ON workspace_user_sessions (workspace_id, updated_at);
CREATE INDEX ix_workspace_user_sessions_user_updated ON workspace_user_sessions (user_id, updated_at);


CREATE TABLE workspace_users (
	user_id VARCHAR(128) NOT NULL, 
	workspace_id VARCHAR(128) NOT NULL, 
	email VARCHAR(256) NOT NULL, 
	display_name VARCHAR(256) NOT NULL, 
	password_hash VARCHAR(256) NOT NULL, 
	password_salt VARCHAR(128) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	metadata_json TEXT NOT NULL, 
	created_at FLOAT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (user_id)
)

;

CREATE UNIQUE INDEX ix_workspace_users_workspace_email ON workspace_users (workspace_id, email);
CREATE INDEX ix_workspace_users_workspace_updated ON workspace_users (workspace_id, updated_at);


CREATE TABLE workspaces (
	workspace_id VARCHAR(128) NOT NULL, 
	display_name VARCHAR(256) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	metadata_json TEXT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (workspace_id)
)

;
