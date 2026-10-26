
CREATE TABLE client_registry (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	code VARCHAR NOT NULL, 
	full_name VARCHAR NOT NULL, 
	crm_id VARCHAR, 
	sex VARCHAR(6), 
	birth_year INTEGER, 
	email VARCHAR, 
	phone VARCHAR, 
	telegram VARCHAR, 
	telegram_id INTEGER, 
	whatsapp VARCHAR, 
	max_messenger VARCHAR, 
	brokers JSON, 
	primary_channel VARCHAR(8), 
	ips_sent_at DATE, 
	note VARCHAR, 
	created_at DATETIME NOT NULL, 
	CONSTRAINT uq_client_registry_code UNIQUE (code)
)

;

CREATE TABLE client (
	id INTEGER NOT NULL, 
	registry_id INTEGER NOT NULL, 
	version INTEGER NOT NULL, 
	source_digest VARCHAR NOT NULL, 
	note VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_client_registry_version UNIQUE (registry_id, version), 
	FOREIGN KEY(registry_id) REFERENCES client_registry (id)
)

;

CREATE TABLE client_meeting (
	id INTEGER NOT NULL, 
	registry_id INTEGER NOT NULL, 
	goal VARCHAR NOT NULL, 
	date DATE NOT NULL, 
	time TIME, 
	format VARCHAR(9) NOT NULL, 
	notes TEXT DEFAULT '' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_meeting_goal CHECK (length(trim(goal)) > 0), 
	CONSTRAINT ck_meeting_format CHECK (format IN ('in_person', 'online', 'phone')), 
	FOREIGN KEY(registry_id) REFERENCES client_registry (id)
)

;
CREATE INDEX ix_client_meeting_registry_id ON client_meeting (registry_id);

CREATE TABLE tax_residency (
	id INTEGER NOT NULL, 
	registry_id INTEGER NOT NULL, 
	year INTEGER NOT NULL, 
	country VARCHAR NOT NULL, 
	note VARCHAR, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tax_residency_year UNIQUE (registry_id, year), 
	FOREIGN KEY(registry_id) REFERENCES client_registry (id)
)

;

CREATE TABLE asset (
	id INTEGER NOT NULL, 
	client_id INTEGER NOT NULL, 
	label VARCHAR NOT NULL, 
	amount FLOAT NOT NULL, 
	currency VARCHAR NOT NULL, 
	asset_class VARCHAR(11) NOT NULL, 
	growth_rate FLOAT, 
	note VARCHAR, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES client (id)
)

;

CREATE TABLE budget_item (
	id INTEGER NOT NULL, 
	client_id INTEGER NOT NULL, 
	kind VARCHAR(7) NOT NULL, 
	label VARCHAR NOT NULL, 
	monthly_amount FLOAT NOT NULL, 
	indexation_rate FLOAT, 
	start_month VARCHAR, 
	end_rule VARCHAR(16) NOT NULL, 
	end_month VARCHAR, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES client (id)
)

;

CREATE TABLE goal (
	id INTEGER NOT NULL, 
	client_id INTEGER NOT NULL, 
	label VARCHAR NOT NULL, 
	kind VARCHAR(17) NOT NULL, 
	amount_pv FLOAT NOT NULL, 
	amount_basis VARCHAR(13) DEFAULT 'amount' NOT NULL, 
	pv_year INTEGER NOT NULL, 
	target_year INTEGER, 
	target_month INTEGER, 
	priority INTEGER NOT NULL, 
	becomes_asset BOOLEAN NOT NULL, 
	can_defer BOOLEAN NOT NULL, 
	can_resize BOOLEAN NOT NULL, 
	indexation_rate FLOAT, 
	replaces_asset VARCHAR, 
	reserve_label VARCHAR, 
	note VARCHAR, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES client (id)
)

;

CREATE TABLE liability (
	id INTEGER NOT NULL, 
	client_id INTEGER NOT NULL, 
	label VARCHAR NOT NULL, 
	principal FLOAT NOT NULL, 
	annual_rate FLOAT NOT NULL, 
	monthly_payment FLOAT NOT NULL, 
	term_months INTEGER NOT NULL, 
	start_month VARCHAR NOT NULL, 
	note VARCHAR, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES client (id)
)

;

CREATE TABLE person (
	id INTEGER NOT NULL, 
	client_id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	birth_year INTEGER NOT NULL, 
	role VARCHAR(6) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES client (id)
)

;

CREATE TABLE portfolio (
	id INTEGER NOT NULL, 
	client_id INTEGER NOT NULL, 
	label VARCHAR NOT NULL, 
	role VARCHAR(12) NOT NULL, 
	currency VARCHAR NOT NULL, 
	last_date_pin VARCHAR NOT NULL, 
	rebalancing_period VARCHAR DEFAULT 'month' NOT NULL, 
	abs_deviation FLOAT, 
	rel_deviation FLOAT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES client (id)
)

;

CREATE TABLE scenario (
	id INTEGER NOT NULL, 
	client_id INTEGER NOT NULL, 
	label VARCHAR NOT NULL, 
	is_base BOOLEAN NOT NULL, 
	note VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES client (id)
)

;

CREATE TABLE goal_adjustment (
	id INTEGER NOT NULL, 
	scenario_id INTEGER NOT NULL, 
	goal_id INTEGER NOT NULL, 
	action VARCHAR(6) NOT NULL, 
	new_target_year INTEGER, 
	new_amount_pv FLOAT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(scenario_id) REFERENCES scenario (id), 
	FOREIGN KEY(goal_id) REFERENCES goal (id)
)

;

CREATE TABLE plan_run (
	id INTEGER NOT NULL, 
	scenario_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	status VARCHAR(7) NOT NULL, 
	t0 VARCHAR NOT NULL, 
	horizon_years INTEGER NOT NULL, 
	withdrawal_years INTEGER, 
	retirement_year INTEGER NOT NULL, 
	seed INTEGER NOT NULL, 
	mc_number INTEGER NOT NULL, 
	distribution VARCHAR(7) NOT NULL, 
	match_moments BOOLEAN DEFAULT 1 NOT NULL, 
	buffer_lookahead_months INTEGER NOT NULL, 
	savings_horizon_years INTEGER, 
	inflation_rate FLOAT NOT NULL, 
	expense_indexation_rate FLOAT NOT NULL, 
	income_indexation_rate FLOAT NOT NULL, 
	goal_indexation_rate FLOAT NOT NULL, 
	discount_rate FLOAT NOT NULL, 
	buffer_rate FLOAT NOT NULL, 
	accumulation_portfolio_id INTEGER, 
	withdrawal_portfolio_id INTEGER, 
	okama_version VARCHAR, 
	inputs_snapshot JSON NOT NULL, 
	retirement_projection_run_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(scenario_id) REFERENCES scenario (id), 
	FOREIGN KEY(accumulation_portfolio_id) REFERENCES portfolio (id), 
	FOREIGN KEY(withdrawal_portfolio_id) REFERENCES portfolio (id), 
	FOREIGN KEY(retirement_projection_run_id) REFERENCES plan_run (id)
)

;
CREATE INDEX ix_plan_run_retirement_projection_run_id ON plan_run (retirement_projection_run_id);

CREATE TABLE portfolio_holding (
	id INTEGER NOT NULL, 
	portfolio_id INTEGER NOT NULL, 
	symbol VARCHAR NOT NULL, 
	weight FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(portfolio_id) REFERENCES portfolio (id)
)

;

CREATE TABLE ledger_row (
	id INTEGER NOT NULL, 
	plan_run_id INTEGER NOT NULL, 
	month VARCHAR NOT NULL, 
	line_kind VARCHAR(16) NOT NULL, 
	label VARCHAR NOT NULL, 
	amount FLOAT NOT NULL, 
	resolved_rate FLOAT, 
	goal_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(plan_run_id) REFERENCES plan_run (id), 
	FOREIGN KEY(goal_id) REFERENCES goal (id)
)

;
CREATE INDEX ix_ledger_row_plan_run_id ON ledger_row (plan_run_id);
CREATE INDEX ix_ledger_row_month ON ledger_row (month);

CREATE TABLE run_balance_percentile (
	id INTEGER NOT NULL, 
	plan_run_id INTEGER NOT NULL, 
	month VARCHAR NOT NULL, 
	percentile INTEGER NOT NULL, 
	value FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(plan_run_id) REFERENCES plan_run (id)
)

;
CREATE INDEX ix_run_balance_percentile_plan_run_id ON run_balance_percentile (plan_run_id);
CREATE INDEX ix_run_balance_percentile_month ON run_balance_percentile (month);

CREATE TABLE run_goal_result (
	id INTEGER NOT NULL, 
	plan_run_id INTEGER NOT NULL, 
	goal_id INTEGER, 
	month VARCHAR NOT NULL, 
	amount_nominal FLOAT NOT NULL, 
	p_affordable FLOAT NOT NULL, 
	p_alive FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(plan_run_id) REFERENCES plan_run (id), 
	FOREIGN KEY(goal_id) REFERENCES goal (id)
)

;
CREATE INDEX ix_run_goal_result_plan_run_id ON run_goal_result (plan_run_id);

CREATE TABLE run_ledger_state (
	plan_run_id INTEGER NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (plan_run_id), 
	FOREIGN KEY(plan_run_id) REFERENCES plan_run (id)
)

;

CREATE TABLE run_metric (
	id INTEGER NOT NULL, 
	plan_run_id INTEGER NOT NULL, 
	"key" VARCHAR NOT NULL, 
	value FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(plan_run_id) REFERENCES plan_run (id)
)

;
CREATE INDEX ix_run_metric_plan_run_id ON run_metric (plan_run_id);

CREATE TABLE sweep_result (
	id INTEGER NOT NULL, 
	plan_run_id INTEGER NOT NULL, 
	goal_id INTEGER, 
	kind VARCHAR(21) NOT NULL, 
	threshold FLOAT NOT NULL, 
	value FLOAT NOT NULL, 
	note VARCHAR, 
	PRIMARY KEY (id), 
	FOREIGN KEY(plan_run_id) REFERENCES plan_run (id), 
	FOREIGN KEY(goal_id) REFERENCES goal (id)
)

;
CREATE INDEX ix_sweep_result_plan_run_id ON sweep_result (plan_run_id);

CREATE TABLE client_intake_note (
	id INTEGER NOT NULL, 
	registry_id INTEGER, 
	source_key VARCHAR NOT NULL, 
	content_digest VARCHAR NOT NULL, 
	content TEXT NOT NULL, 
	imported_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_intake_source_content UNIQUE (source_key, content_digest)
)

;