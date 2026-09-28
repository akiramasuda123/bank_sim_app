import os
from datetime import date
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'

db_url = os.environ.get('DATABASE_URL', 'sqlite:///bank_app.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- DBモデル定義 ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    balance = db.Column(db.Integer, default=0)

class SimulationItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    item_type = db.Column(db.String(10), nullable=False, default='pay')  # 'pay' or 'income'
    month = db.Column(db.String(7), nullable=False)  # 例: '2025-07'
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    account = db.relationship('Account', backref=db.backref('simulations', lazy=True))

class ExpenseLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    person_name = db.Column(db.String(50), nullable=False)  # 手打ちの名前
    title = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    month = db.Column(db.String(7), nullable=False)  # 例: '2025-07'
    logged_date = db.Column(db.String(10), nullable=False)  # 例: '2025-07-15'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

# --- ルーティング ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('そのユーザー名は既に使用されています。')
            return redirect(url_for('register'))
        new_user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        flash('アカウントが作成されました！ログインしてください。')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))
        flash('ユーザー名またはパスワードが違います。')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

def get_adjacent_months(month_str):
    """指定月の前月・翌月を返す"""
    y, m = int(month_str[:4]), int(month_str[5:])
    prev_y = y + (m - 2) // 12
    prev_m = (m - 2) % 12 + 1
    next_y = y + m // 12
    next_m = m % 12 + 1
    return f"{prev_y}-{prev_m:02d}", f"{next_y}-{next_m:02d}"

@app.route('/')
@login_required
def index():
    accounts = Account.query.all()
    filter_id = request.args.get('filter_account_id', type=int)
    today = date.today()
    selected_month = request.args.get('month', f"{today.year}-{today.month:02d}")

    query = SimulationItem.query.filter_by(month=selected_month)
    if filter_id:
        query = query.filter_by(account_id=filter_id)
    simulations = query.all()

    total_balance = sum(acc.balance for acc in accounts)

    # 選択月の全シミュレーション（銀行フィルターなし）で全体収支を計算
    all_month_sims = SimulationItem.query.filter_by(month=selected_month).all()
    total_income = sum(s.amount for s in all_month_sims if s.item_type == 'income')
    total_pay = sum(s.amount for s in all_month_sims if s.item_type == 'pay')
    projected_balance = total_balance + total_income - total_pay

    account_summaries = []
    for acc in accounts:
        acc_sims = SimulationItem.query.filter_by(account_id=acc.id, month=selected_month).all()
        acc_income = sum(s.amount for s in acc_sims if s.item_type == 'income')
        acc_pay = sum(s.amount for s in acc_sims if s.item_type == 'pay')
        account_summaries.append({
            'account': acc,
            'current_balance': acc.balance,
            'total_income': acc_income,
            'total_pay': acc_pay,
            'after_balance': acc.balance + acc_income - acc_pay
        })

    return render_template('index.html',
                           summaries=account_summaries,
                           total_balance=total_balance,
                           total_income=total_income,
                           total_pay=total_pay,
                           projected_balance=projected_balance,
                           simulations=simulations,
                           accounts=accounts,
                           filter_id=filter_id,
                           selected_month=selected_month,
                           prev_month=get_adjacent_months(selected_month)[0],
                           next_month=get_adjacent_months(selected_month)[1])

@app.route('/accounts/update', methods=['POST'])
@login_required
def update_accounts():
    accounts = Account.query.all()
    for acc in accounts:
        new_balance = request.form.get(f'balance_{acc.id}')
        if new_balance is not None:
            acc.balance = int(new_balance)
    new_acc_name = request.form.get('new_account_name')
    new_acc_balance = request.form.get('new_account_balance')
    if new_acc_name and new_acc_balance:
        db.session.add(Account(name=new_acc_name, balance=int(new_acc_balance)))
    db.session.commit()
    flash('口座情報を更新しました。')
    month = request.form.get('current_month', '')
    return redirect(url_for('index', month=month))

@app.route('/simulation/add', methods=['POST'])
@login_required
def add_simulation():
    title = request.form.get('title')
    amount = int(request.form.get('amount', 0))
    account_id = request.form.get('account_id')
    item_type = request.form.get('item_type', 'pay')
    month = request.form.get('month')
    if title and amount and account_id and month:
        db.session.add(SimulationItem(title=title, amount=amount, item_type=item_type,
                                      month=month, account_id=account_id))
        db.session.commit()
    return redirect(url_for('index', month=month, filter_account_id=request.form.get('filter_account_id') or ''))

@app.route('/simulation/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_simulation(item_id):
    item = SimulationItem.query.get_or_404(item_id)
    month = item.month
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('index', month=month))

# --- 支出メモ ---
@app.route('/memo')
@login_required
def memo():
    today = date.today()
    selected_month = request.args.get('month', f"{today.year}-{today.month:02d}")
    filter_person = request.args.get('person', '')

    query = ExpenseLog.query.filter_by(month=selected_month)
    if filter_person:
        query = query.filter_by(person_name=filter_person)
    logs = query.order_by(ExpenseLog.logged_date.desc()).all()

    all_logs = ExpenseLog.query.filter_by(month=selected_month).all()
    # 人別集計
    person_totals = {}
    for log in all_logs:
        person_totals[log.person_name] = person_totals.get(log.person_name, 0) + log.amount
    total = sum(person_totals.values())

    # 過去に登録された名前一覧（サジェスト用）
    recent_names = [r[0] for r in db.session.query(ExpenseLog.person_name)
                    .distinct().order_by(ExpenseLog.id.desc()).limit(5).all()]

    return render_template('memo.html',
                           logs=logs,
                           person_totals=person_totals,
                           total=total,
                           selected_month=selected_month,
                           prev_month=get_adjacent_months(selected_month)[0],
                           next_month=get_adjacent_months(selected_month)[1],
                           filter_person=filter_person,
                           recent_names=recent_names,
                           today_str=date.today().isoformat())

@app.route('/memo/add', methods=['POST'])
@login_required
def add_memo():
    person_name = request.form.get('person_name', '').strip()
    title = request.form.get('title', '').strip()
    amount = int(request.form.get('amount', 0))
    month = request.form.get('month')
    logged_date = request.form.get('logged_date') or date.today().isoformat()
    if person_name and title and amount and month:
        db.session.add(ExpenseLog(person_name=person_name, title=title,
                                  amount=amount, month=month, logged_date=logged_date))
        db.session.commit()
    return redirect(url_for('memo', month=month, person=request.form.get('filter_person', '')))

@app.route('/memo/delete/<int:log_id>', methods=['POST'])
@login_required
def delete_memo(log_id):
    log = ExpenseLog.query.get_or_404(log_id)
    month = log.month
    db.session.delete(log)
    db.session.commit()
    return redirect(url_for('memo', month=month))

if __name__ == '__main__':
    app.run(debug=True)
