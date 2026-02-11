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
        cursor.execute("SELECT id FROM users WHERE referral_code = %s", (code,))
        if not cursor.fetchone():
            cursor.close()
            db.close()
            return code

# Calculate reward based on referral count
def calculate_reward(referrer_id):
    db = get_db()
    cursor = db.cursor()
    
    # Count how many referrals this user already has
    cursor.execute("SELECT COUNT(*) as count FROM referrals WHERE referrer_id = %s", (referrer_id,))
    result = cursor.fetchone()
    referral_count = result[0] if result else 0
    
    # Reward calculation: 500, 400, 300, 200, 100, then 0
    rewards = [500, 400, 300, 200, 100]
    if referral_count < len(rewards):
        reward = rewards[referral_count]
    else:
        reward = 0
    
    cursor.close()
    db.close()
    return reward

# Home route
@app.route('/')
def index():
    return render_template('index.html')

# Signup route
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        city = request.form['city']
        email = request.form['email']
        password = request.form['password']
        referral_code = request.form.get('referral_code', '').strip()
        
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Generate unique referral code for new user
            user_referral_code = generate_referral_code()
            
            # Insert new user
            cursor.execute("""
                INSERT INTO users (name, city, email, password, referral_code)
                VALUES (%s, %s, %s, %s, %s)
            """, (name, city, email, password, user_referral_code))
            
            user_id = cursor.lastrowid
            
            # Create rewards entry
            cursor.execute("""
                INSERT INTO rewards (user_id) VALUES (%s)
            """, (user_id,))
            
            # If referral code was provided
            if referral_code:
                # Find who referred this user
                cursor.execute("""
                    SELECT id FROM users WHERE referral_code = %s
                """, (referral_code,))
                referrer = cursor.fetchone()
                
                if referrer:
                    referrer_id = referrer[0]
                    
                    # Calculate reward for referrer
                    reward_amount = calculate_reward(referrer_id)
                    
                    # Update referred_by for new user
                    cursor.execute("""
                        UPDATE users SET referred_by = %s WHERE id = %s
                    """, (referral_code, user_id))
                    
                    # Record the referral
                    cursor.execute("""
                        INSERT INTO referrals (referrer_id, referred_id, referral_code_used, reward_amount)
                        VALUES (%s, %s, %s, %s)
                    """, (referrer_id, user_id, referral_code, reward_amount))
                    
                    # Update referrer's rewards if reward > 0
                    if reward_amount > 0:
                        cursor.execute("""
                            UPDATE rewards 
                            SET total_earned = total_earned + %s,
                                available_balance = available_balance + %s
                            WHERE user_id = %s
                        """, (reward_amount, reward_amount, referrer_id))
                    
                    db.commit()
                    
                    # Store reward info for dashboard display
                    session['referral_reward'] = reward_amount
                    session['referrer_id'] = referrer_id
            
            db.commit()
            session['user_id'] = user_id
            session['user_name'] = name
            session['referral_code'] = user_referral_code
            
            cursor.close()
            db.close()
            
            return redirect(url_for('success'))
            
        except mysql.connector.IntegrityError:
            flash('Email already exists!', 'error')
            cursor.close()
            db.close()
            return redirect(url_for('signup'))
    
    return render_template('signup.html')

# Success page after signup
@app.route('/success')
def success():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    return render_template('success.html', 
                         name=session['user_name'],
                         referral_code=session['referral_code'])

# Dashboard route
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get user rewards
    cursor.execute("""
        SELECT total_earned, available_balance 
        FROM rewards 
        WHERE user_id = %s
    """, (user_id,))
    rewards = cursor.fetchone()
    
    # Get referral history
    cursor.execute("""
        SELECT r.referral_date, u.name as referred_name, r.reward_amount
        FROM referrals r
        JOIN users u ON r.referred_id = u.id
        WHERE r.referrer_id = %s
        ORDER BY r.referral_date DESC
    """, (user_id,))
    referrals = cursor.fetchall()
    
    # Get user's referral code
    cursor.execute("""
        SELECT referral_code FROM users WHERE id = %s
    """, (user_id,))
    user = cursor.fetchone()
    
    cursor.close()
    db.close()
    
    # Check if user came from referral signup
    referral_reward = session.pop('referral_reward', None) if 'referral_reward' in session else None
    referrer_id = session.pop('referrer_id', None) if 'referrer_id' in session else None
    
    return render_template('dashboard.html',
                         rewards=rewards,
                         referrals=referrals,
                         referral_code=user['referral_code'],
                         referral_reward=referral_reward)

# Login route (optional but good to have)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, name, referral_code FROM users 
            WHERE email = %s AND password = %s
        """, (email, password))
        
        user = cursor.fetchone()
        cursor.close()
        db.close()
        
        if user:
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['referral_code'] = user['referral_code']
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password!', 'error')
    
    return render_template('login.html')

# Logout route
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# API to check reward status for a referral code
@app.route('/check_reward/<referral_code>')
def check_reward(referral_code):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Find user with this referral code
    cursor.execute("""
        SELECT id FROM users WHERE referral_code = %s
    """, (referral_code,))
    referrer = cursor.fetchone()
    
    if not referrer:
        return jsonify({'valid': False, 'message': 'Invalid referral code'})
    
    # Count referrals and calculate reward
    cursor.execute("""
        SELECT COUNT(*) as count FROM referrals 
        WHERE referrer_id = %s
    """, (referrer['id'],))
    result = cursor.fetchone()
    referral_count = result['count']
    
    rewards = [500, 400, 300, 200, 100]
    if referral_count < len(rewards):
        reward = rewards[referral_count]
        message = f"Use this code to earn ₹{reward} for your friend!"
    else:
        reward = 0
        message = "Reward program for this code has ended"
    
    cursor.close()
    db.close()
    
    return jsonify({
        'valid': True,
        'reward': reward,
        'message': message,
        'referral_count': referral_count
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)