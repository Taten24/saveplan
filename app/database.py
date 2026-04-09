import sqlite3
from flask import g

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS monthly_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    savings_target REAL NOT NULL DEFAULT 100,
    rent_bills_target REAL NOT NULL DEFAULT 75,
    groceries_target REAL NOT NULL DEFAULT 25,
    other_home_target REAL NOT NULL DEFAULT 40,
    mini_savings_target REAL NOT NULL DEFAULT 60,
    total_target REAL NOT NULL DEFAULT 300,
    UNIQUE(user_id, month, year),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tx_type TEXT NOT NULL,
    amount REAL NOT NULL,
    description TEXT,
    category TEXT,
    tx_date TEXT NOT NULL,
    payment_method TEXT,
    food_deduction_applied INTEGER NOT NULL DEFAULT 0,
    food_deduction_amount REAL NOT NULL DEFAULT 0,
    allocatable_amount REAL NOT NULL DEFAULT 0,
    other_cash_out REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    auto_amount REAL NOT NULL DEFAULT 0,
    override_amount REAL,
    final_amount REAL NOT NULL DEFAULT 0,
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    FOREIGN KEY(transaction_id) REFERENCES transactions(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    debt_type TEXT NOT NULL,
    amount REAL NOT NULL,
    paid_amount REAL NOT NULL DEFAULT 0,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS cash_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    balance REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
'''


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(g.app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db(app):
    import os
    os.makedirs(app.instance_path, exist_ok=True)

    @app.before_request
    def inject_app_to_g():
        g.app = app

    with app.app_context():
        db = sqlite3.connect(app.config['DATABASE'])
        db.executescript(SCHEMA)
        db.commit()
        db.close()

    app.teardown_appcontext(close_db)
