-- Schema as deployed before migration 1 (generated from commit 3c92390).
CREATE TABLE setting (
	"key" VARCHAR(64) NOT NULL, 
	value JSON NOT NULL, 
	PRIMARY KEY ("key")
);
CREATE TABLE routine (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	duration_min INTEGER, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE micro_move (
	id INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE learning_path (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	category VARCHAR(32) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	daily_goal_min INTEGER, 
	active BOOLEAN NOT NULL, 
	completed_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE TABLE hobby (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE pause (
	id INTEGER NOT NULL, 
	area VARCHAR(32), 
	until DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE prompt (
	id INTEGER NOT NULL, 
	area VARCHAR(32) NOT NULL, 
	kind VARCHAR(40) NOT NULL, 
	payload JSON, 
	scheduled_for DATETIME NOT NULL, 
	sent_at DATETIME, 
	telegram_message_id INTEGER, 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_prompt_scheduled_for ON prompt (scheduled_for);
CREATE TABLE routine_step (
	id INTEGER NOT NULL, 
	routine_id INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	duration_sec INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(routine_id) REFERENCES routine (id) ON DELETE CASCADE
);
CREATE TABLE path_step (
	id INTEGER NOT NULL, 
	path_id INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	detail TEXT, 
	done_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(path_id) REFERENCES learning_path (id) ON DELETE CASCADE
);
CREATE TABLE flashcard (
	id INTEGER NOT NULL, 
	path_id INTEGER NOT NULL, 
	front TEXT NOT NULL, 
	back TEXT NOT NULL, 
	fsrs_state JSON, 
	due DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(path_id) REFERENCES learning_path (id) ON DELETE CASCADE
);
CREATE INDEX ix_flashcard_due ON flashcard (due);
CREATE TABLE hobby_element (
	id INTEGER NOT NULL, 
	hobby_id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	requires_path_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(hobby_id) REFERENCES hobby (id) ON DELETE CASCADE, 
	FOREIGN KEY(requires_path_id) REFERENCES learning_path (id) ON DELETE SET NULL
);
CREATE TABLE schedule_rule (
	id INTEGER NOT NULL, 
	hobby_id INTEGER, 
	path_id INTEGER, 
	method VARCHAR(32) NOT NULL, 
	sessions_per_week INTEGER, 
	weekdays JSON, 
	start_date DATE, 
	end_date DATE, 
	weight FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT rule_targets_one_item CHECK ((hobby_id IS NULL) != (path_id IS NULL)), 
	FOREIGN KEY(hobby_id) REFERENCES hobby (id) ON DELETE CASCADE, 
	FOREIGN KEY(path_id) REFERENCES learning_path (id) ON DELETE CASCADE
);
CREATE TABLE log_entry (
	id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	area VARCHAR(32) NOT NULL, 
	prompt_id INTEGER, 
	label VARCHAR(200), 
	routine_id INTEGER, 
	path_id INTEGER, 
	path_step_id INTEGER, 
	hobby_id INTEGER, 
	hobby_element_id INTEGER, 
	outcome VARCHAR(32), 
	duration_min INTEGER, 
	rating INTEGER, 
	note TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(prompt_id) REFERENCES prompt (id) ON DELETE SET NULL, 
	FOREIGN KEY(routine_id) REFERENCES routine (id) ON DELETE SET NULL, 
	FOREIGN KEY(path_id) REFERENCES learning_path (id) ON DELETE SET NULL, 
	FOREIGN KEY(path_step_id) REFERENCES path_step (id) ON DELETE SET NULL, 
	FOREIGN KEY(hobby_id) REFERENCES hobby (id) ON DELETE SET NULL, 
	FOREIGN KEY(hobby_element_id) REFERENCES hobby_element (id) ON DELETE SET NULL
);
CREATE INDEX ix_log_entry_created_at ON log_entry (created_at);
