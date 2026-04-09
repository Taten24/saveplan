# SavePlan Admin Edition

A multi-user Flask personal finance app with owner/admin controls.

## Features
- User registration and login
- Private data per user
- Optional $2 food deduction on income entries
- Automatic allocation toward monthly targets
- Manual override per transaction
- Dashboard, debts, cash accounts, reports
- Admin dashboard
- Freeze unpaid users
- Delete users

## Default monthly targets
- Savings: 100
- Rent & Bills: 75
- Groceries: 25
- Other Home: 40
- Mini Savings: 60

## How the owner works
- The first account that registers becomes `admin` automatically.
- Admin can:
  - view all users
  - freeze users
  - unfreeze users
  - delete users
- Frozen users cannot log in.

## Run locally
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open http://127.0.0.1:5000

## Deploy notes
For Render or other hosting:
- This starter uses SQLite for simplicity.
- For production multi-user hosting, PostgreSQL is recommended later.
