from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import mysql.connector
from config import Config
import random
import string
from datetime import datetime

app = Flask(__name__)
app.config.from_object(Config)

# Database connection helper
def get_db():
    return mysql.connector.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB']
    )

# Generate unique referral code
def generate_referral_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM users WHERE my_referral_code = %s", (code,))
        exists = cursor.fetchone()
        cursor.close()
        db.close()

        if not exists:
            return code

def calculate_reward(referrer_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (referrer_id,))
    count = cursor.fetchone()[0]
    cursor.close()
    db.close()
    
    rewards = [500, 400, 300, 200, 100]
    return rewards[count] if count < len(rewards) else 0

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        city = request.form['city']
        email = request.form['email']
        password = request.form['password']
        ref_code_used = request.form.get('referral_code', '').strip()
        
        db = get_db()
        cursor = db.cursor()
        try:
            my_code = generate_referral_code()
            cursor.execute("""INSERT INTO users (name, city, email, password, my_referral_code, referred_by_code) 
                           VALUES (%s, %s, %s, %s, %s, %s)""", 
                           (name, city, email, password, my_code, ref_code_used))
            new_user_id = cursor.lastrowid

            if ref_code_used:
                cursor.execute("SELECT id FROM users WHERE my_referral_code = %s", (ref_code_used,))
                referrer = cursor.fetchone()
                if referrer:
                    ref_id = referrer[0]
                    reward = calculate_reward(ref_id)
                    if reward > 0:
                        cursor.execute("INSERT INTO referrals (referrer_id, referred_user_id, reward_earned) VALUES (%s, %s, %s)", 
                                       (ref_id, new_user_id, reward))
                        cursor.execute("UPDATE users SET total_earnings = total_earnings + %s, available_balance = available_balance + %s WHERE id = %s", 
                                       (reward, reward, ref_id))
            
            db.commit()
            session['user_id'] = new_user_id
            session['user_name'] = name
            session['my_code'] = my_code
            return redirect(url_for('success'))
        except Exception as e:
            db.rollback()
            flash('Email already exists or Database Error', 'error')
        finally:
            cursor.close()
            db.close()
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s AND password = %s", (request.form['email'], request.form['password']))
        user = cursor.fetchone()
        cursor.close()
        db.close()
        if user:
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['my_code'] = user['my_referral_code']
            return redirect(url_for('dashboard'))
        flash('Invalid Credentials', 'error')
    return render_template('login.html')

@app.route('/success')
def success():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('success.html', name=session['user_name'], referral_code=session['my_code'])

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # 1. Fetch User Data
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    
    # 2. Fetch Referral History
    cursor.execute("""SELECT r.referral_date, u.name as referred_name, r.reward_earned 
                   FROM referrals r JOIN users u ON r.referred_user_id = u.id 
                   WHERE r.referrer_id = %s ORDER BY r.referral_date DESC""", (session['user_id'],))
    history = cursor.fetchall()
    
    # 3. Fetch Withdrawal History (NEW LOGIC)
    cursor.execute("""SELECT amount, withdrawal_date, status 
                   FROM withdrawals WHERE user_id = %s 
                   ORDER BY withdrawal_date DESC""", (session['user_id'],))
    withdrawals = cursor.fetchall()
    
    cursor.close()
    db.close()
    return render_template('dashboard.html', user=user, referrals=history, withdrawals=withdrawals)

@app.route('/withdraw', methods=['POST'])
def withdraw():
    if 'user_id' not in session: return redirect(url_for('login'))
    try:
        amount = float(request.form.get('amount', 0))
    except ValueError:
        flash('Invalid amount entered', 'error')
        return redirect(url_for('dashboard'))

    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT available_balance FROM users WHERE id = %s", (user_id,))
    user_data = cursor.fetchone()
    
    if amount > 0 and user_data['available_balance'] >= amount:
        cursor.execute("UPDATE users SET available_balance = available_balance - %s WHERE id = %s", (amount, user_id))
        cursor.execute("INSERT INTO withdrawals (user_id, amount) VALUES (%s, %s)", (user_id, amount))
        db.commit()
        flash(f'Successfully withdrawn Rs.{amount}', 'success')
    else:
        flash('Insufficient balance or invalid amount', 'error')
    
    cursor.close()
    db.close()
    return redirect(url_for('dashboard'))

@app.route('/check_reward/<referral_code>')
def check_reward(referral_code):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM users WHERE my_referral_code = %s", (referral_code,))
    referrer = cursor.fetchone()
    if not referrer:
        return jsonify({'valid': False, 'message': 'Invalid referral code'})
    
    reward = calculate_reward(referrer[0])
    message = f"Valid code! Referrer earns Rs.{reward}" if reward > 0 else "Code valid, but reward limit reached."
    return jsonify({'valid': True, 'message': message})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)