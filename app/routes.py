from functools import wraps
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
from .database import get_db

TARGET_ORDER = [
    ('Rent & Bills', 'rent_bills_target'),
    ('Groceries', 'groceries_target'),
    ('Other Home', 'other_home_target'),
    ('Savings', 'savings_target'),
    ('Mini Savings', 'mini_savings_target'),
]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get('role') != 'admin':
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def get_or_create_targets(db, user_id, month, year):
    row = db.execute(
        'SELECT * FROM monthly_targets WHERE user_id = ? AND month = ? AND year = ?',
        (user_id, month, year)
    ).fetchone()
    if row:
        return row
    db.execute(
        '''INSERT INTO monthly_targets (user_id, month, year, savings_target, rent_bills_target, groceries_target, other_home_target, mini_savings_target, total_target)
           VALUES (?, ?, ?, 100, 75, 25, 40, 60, 300)''',
        (user_id, month, year)
    )
    db.commit()
    return db.execute(
        'SELECT * FROM monthly_targets WHERE user_id = ? AND month = ? AND year = ?',
        (user_id, month, year)
    ).fetchone()


def category_progress(db, user_id, month, year):
    target = get_or_create_targets(db, user_id, month, year)
    allocs = db.execute(
        '''SELECT category, COALESCE(SUM(final_amount),0) as total
           FROM allocations WHERE user_id = ? AND month = ? AND year = ?
           GROUP BY category''',
        (user_id, month, year)
    ).fetchall()
    allocated_map = {row['category']: row['total'] for row in allocs}
    progress = []
    total_allocated = 0
    total_target = target['total_target']
    for label, field in TARGET_ORDER:
        allocated = float(allocated_map.get(label, 0) or 0)
        t = float(target[field])
        remaining = max(0, t - allocated)
        surplus = max(0, allocated - t)
        progress.append({
            'label': label,
            'target': t,
            'allocated': allocated,
            'remaining': remaining,
            'surplus': surplus,
            'percent': (allocated / t * 100) if t else 0,
        })
        total_allocated += allocated
    return progress, total_allocated, total_target


def auto_allocate(db, user_id, transaction_id, allocatable_amount, month, year, override_map=None):
    override_map = override_map or {}
    progress, _, _ = category_progress(db, user_id, month, year)
    remaining_pool = float(allocatable_amount)

    for item in progress:
        category = item['label']
        auto_amount = 0.0
        override_amount = override_map.get(category)
        final_amount = 0.0

        if override_amount not in (None, ''):
            try:
                override_amount = max(0.0, float(override_amount))
            except ValueError:
                override_amount = 0.0
            final_amount = min(remaining_pool, override_amount)
        else:
            needed = item['remaining']
            auto_amount = min(remaining_pool, needed)
            final_amount = auto_amount

        if final_amount > 0:
            db.execute(
                '''INSERT INTO allocations (transaction_id, user_id, category, auto_amount, override_amount, final_amount, month, year)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (transaction_id, user_id, category, auto_amount, override_amount if override_amount not in (None, '') else None, final_amount, month, year)
            )
            remaining_pool -= final_amount

    if remaining_pool > 0:
        db.execute(
            '''INSERT INTO allocations (transaction_id, user_id, category, auto_amount, override_amount, final_amount, month, year)
               VALUES (?, ?, 'Excess', ?, NULL, ?, ?, ?)''',
            (transaction_id, user_id, remaining_pool, remaining_pool, month, year)
        )
    db.commit()


def current_user(db):
    if 'user_id' not in session:
        return None
    return db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()


def register_routes(app):
    @app.route('/')
    def index():
        if 'user_id' in session:
            return redirect(url_for('dashboard'))
        return render_template('index.html')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        db = get_db()
        if request.method == 'POST':
            username = request.form['username'].strip()
            password = request.form['password']
            if not username or not password:
                flash('Username and password are required.')
                return redirect(url_for('register'))
            exists = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
            if exists:
                flash('Username already exists.')
                return redirect(url_for('register'))
            count = db.execute('SELECT COUNT(*) as c FROM users').fetchone()['c']
            role = 'admin' if count == 0 else 'user'
            db.execute(
                'INSERT INTO users (username, password_hash, role, status) VALUES (?, ?, ?, ?)',
                (username, generate_password_hash(password), role, 'active')
            )
            db.commit()
            flash('Account created. You can now log in.')
            return redirect(url_for('login'))
        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        db = get_db()
        if request.method == 'POST':
            username = request.form['username'].strip()
            password = request.form['password']
            user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if not user or not check_password_hash(user['password_hash'], password):
                flash('Invalid username or password.')
                return redirect(url_for('login'))
            if user['status'] == 'frozen':
                flash('Your account has been frozen. Please contact the owner.')
                return redirect(url_for('login'))
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('dashboard'))
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        db = get_db()
        user_id = session['user_id']
        now = datetime.now()
        month, year = now.month, now.year
        target = get_or_create_targets(db, user_id, month, year)
        progress, total_allocated, total_target = category_progress(db, user_id, month, year)

        txs = db.execute(
            '''SELECT * FROM transactions WHERE user_id = ? AND strftime('%m', tx_date) = ? AND strftime('%Y', tx_date) = ? ORDER BY tx_date DESC, id DESC''',
            (user_id, f'{month:02d}', str(year))
        ).fetchall()
        total_income = sum(float(t['amount']) for t in txs if t['tx_type'] == 'income')
        total_expenses = sum(float(t['amount']) for t in txs if t['tx_type'] == 'expense') + sum(float(t['other_cash_out']) for t in txs)
        deductions = sum(float(t['food_deduction_amount']) for t in txs)
        net = total_income - total_expenses - deductions
        needed = max(0, total_target - total_allocated)
        excess = max(0, total_allocated - total_target)

        return render_template('dashboard.html', target=target, progress=progress,
                               total_income=round(total_income,2), total_expenses=round(total_expenses,2),
                               deductions=round(deductions,2), net=round(net,2),
                               allocated=round(total_allocated,2), needed=round(needed,2), excess=round(excess,2))

    @app.route('/transactions', methods=['GET', 'POST'])
    @login_required
    def transactions():
        db = get_db()
        user_id = session['user_id']
        now = datetime.now()
        default_date = now.strftime('%Y-%m-%d')

        if request.method == 'POST':
            tx_type = request.form['tx_type']
            amount = float(request.form['amount'])
            description = request.form.get('description', '').strip()
            category = request.form.get('category', '').strip()
            tx_date = request.form.get('tx_date') or default_date
            payment_method = request.form.get('payment_method', '').strip()
            food_toggle = request.form.get('food_deduction') == 'yes'
            other_cash_out = float(request.form.get('other_cash_out') or 0)
            deduction = 2.0 if (tx_type == 'income' and food_toggle) else 0.0
            allocatable = max(0.0, amount - deduction - other_cash_out) if tx_type == 'income' else 0.0

            db.execute(
                '''INSERT INTO transactions (user_id, tx_type, amount, description, category, tx_date, payment_method, food_deduction_applied, food_deduction_amount, allocatable_amount, other_cash_out)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (user_id, tx_type, amount, description, category, tx_date, payment_method, 1 if food_toggle else 0, deduction, allocatable, other_cash_out)
            )
            tx_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.commit()

            if tx_type == 'income' and allocatable > 0:
                month = int(tx_date[5:7])
                year = int(tx_date[:4])
                overrides = {
                    'Rent & Bills': request.form.get('override_rent'),
                    'Groceries': request.form.get('override_groceries'),
                    'Other Home': request.form.get('override_other_home'),
                    'Savings': request.form.get('override_savings'),
                    'Mini Savings': request.form.get('override_mini_savings'),
                }
                auto_allocate(db, user_id, tx_id, allocatable, month, year, overrides)

            flash('Transaction saved.')
            return redirect(url_for('transactions'))

        rows = db.execute(
            'SELECT * FROM transactions WHERE user_id = ? ORDER BY tx_date DESC, id DESC',
            (user_id,)
        ).fetchall()
        return render_template('transactions.html', rows=rows, default_date=default_date)

    @app.route('/budget', methods=['GET', 'POST'])
    @login_required
    def budget():
        db = get_db()
        user_id = session['user_id']
        now = datetime.now()
        month = int(request.args.get('month', now.month))
        year = int(request.args.get('year', now.year))
        target = get_or_create_targets(db, user_id, month, year)
        if request.method == 'POST':
            savings = float(request.form['savings_target'])
            rent = float(request.form['rent_bills_target'])
            groceries = float(request.form['groceries_target'])
            other = float(request.form['other_home_target'])
            mini = float(request.form['mini_savings_target'])
            total = savings + rent + groceries + other + mini
            db.execute(
                '''UPDATE monthly_targets SET savings_target=?, rent_bills_target=?, groceries_target=?, other_home_target=?, mini_savings_target=?, total_target=?
                   WHERE user_id=? AND month=? AND year=?''',
                (savings, rent, groceries, other, mini, total, user_id, month, year)
            )
            db.commit()
            flash('Budget updated.')
            return redirect(url_for('budget', month=month, year=year))
        target = get_or_create_targets(db, user_id, month, year)
        progress, total_allocated, total_target = category_progress(db, user_id, month, year)
        return render_template('budget.html', target=target, month=month, year=year, progress=progress, allocated=total_allocated, total_target=total_target)

    @app.route('/debts', methods=['GET', 'POST'])
    @login_required
    def debts():
        db = get_db()
        user_id = session['user_id']
        if request.method == 'POST':
            db.execute(
                '''INSERT INTO debts (user_id, name, debt_type, amount, paid_amount, due_date, status, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    user_id,
                    request.form['name'].strip(),
                    request.form['debt_type'],
                    float(request.form['amount']),
                    float(request.form.get('paid_amount') or 0),
                    request.form.get('due_date') or None,
                    request.form.get('status') or 'open',
                    request.form.get('note', '').strip(),
                )
            )
            db.commit()
            flash('Debt record saved.')
            return redirect(url_for('debts'))
        rows = db.execute('SELECT * FROM debts WHERE user_id = ? ORDER BY created_at DESC, id DESC', (user_id,)).fetchall()
        return render_template('debts.html', rows=rows)

    @app.route('/accounts', methods=['GET', 'POST'])
    @login_required
    def accounts():
        db = get_db()
        user_id = session['user_id']
        if request.method == 'POST':
            db.execute(
                '''INSERT INTO cash_accounts (user_id, account_name, account_type, balance)
                   VALUES (?, ?, ?, ?)''',
                (user_id, request.form['account_name'].strip(), request.form['account_type'], float(request.form.get('balance') or 0))
            )
            db.commit()
            flash('Account saved.')
            return redirect(url_for('accounts'))
        rows = db.execute('SELECT * FROM cash_accounts WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
        return render_template('accounts.html', rows=rows)

    @app.route('/reports')
    @login_required
    def reports():
        db = get_db()
        user_id = session['user_id']
        monthly = db.execute(
            '''SELECT substr(tx_date,1,7) as ym,
                      SUM(CASE WHEN tx_type='income' THEN amount ELSE 0 END) as income,
                      SUM(CASE WHEN tx_type='expense' THEN amount ELSE 0 END) as expense,
                      SUM(food_deduction_amount) as deductions,
                      SUM(other_cash_out) as other_cash_out
               FROM transactions
               WHERE user_id = ?
               GROUP BY substr(tx_date,1,7)
               ORDER BY ym DESC''',
            (user_id,)
        ).fetchall()
        return render_template('reports.html', monthly=monthly)

    @app.route('/admin')
    @login_required
    @admin_required
    def admin():
        db = get_db()
        users = db.execute(
            '''SELECT u.*,
                      (SELECT COUNT(*) FROM transactions t WHERE t.user_id = u.id) as tx_count,
                      (SELECT COUNT(*) FROM debts d WHERE d.user_id = u.id) as debt_count,
                      (SELECT COUNT(*) FROM cash_accounts c WHERE c.user_id = u.id) as account_count
               FROM users u ORDER BY u.created_at DESC, u.id DESC'''
        ).fetchall()
        return render_template('admin.html', users=users)

    @app.route('/admin/freeze/<int:user_id>', methods=['POST'])
    @login_required
    @admin_required
    def freeze_user(user_id):
        if user_id == session['user_id']:
            flash('You cannot freeze your own admin account.')
            return redirect(url_for('admin'))
        db = get_db()
        db.execute("UPDATE users SET status = 'frozen' WHERE id = ?", (user_id,))
        db.commit()
        flash('User frozen.')
        return redirect(url_for('admin'))

    @app.route('/admin/unfreeze/<int:user_id>', methods=['POST'])
    @login_required
    @admin_required
    def unfreeze_user(user_id):
        db = get_db()
        db.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
        db.commit()
        flash('User unfrozen.')
        return redirect(url_for('admin'))

    @app.route('/admin/delete/<int:user_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_user(user_id):
        if user_id == session['user_id']:
            flash('You cannot delete your own admin account.')
            return redirect(url_for('admin'))
        db = get_db()
        db.execute('DELETE FROM allocations WHERE user_id = ?', (user_id,))
        db.execute('DELETE FROM transactions WHERE user_id = ?', (user_id,))
        db.execute('DELETE FROM debts WHERE user_id = ?', (user_id,))
        db.execute('DELETE FROM cash_accounts WHERE user_id = ?', (user_id,))
        db.execute('DELETE FROM monthly_targets WHERE user_id = ?', (user_id,))
        db.execute('DELETE FROM users WHERE id = ?', (user_id,))
        db.commit()
        flash('User deleted.')
        return redirect(url_for('admin'))
