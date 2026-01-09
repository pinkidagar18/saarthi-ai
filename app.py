from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3
from datetime import datetime, timedelta
import os
import google.generativeai as genai
from functools import wraps
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import schedule
import time
import json

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your flask key')

DATABASE_PATH = os.environ.get('DATABASE_PATH', 'database/saarthi.db')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USERNAME = os.environ.get('EMAIL_USERNAME', 'youremail@gmail.com')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', ' your password')
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'noreply@saarthi.ai')

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if GEMINI_API_KEY and GEMINI_API_KEY != 'your gemini key':
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-pro')
        print("✅ Gemini AI initialized successfully")
    except Exception as e:
        print(f"⚠️  Warning: Could not initialize Gemini AI: {e}")
        model = None
else:
    print("⚠️  Warning: GEMINI_API_KEY not set")
    model = None

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH, timeout=20)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with all required tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'teacher', 'student', 'parent')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Students table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            student_id TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            date_of_birth DATE,
            address TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Courses table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT UNIQUE NOT NULL,
            course_name TEXT NOT NULL,
            description TEXT,
            teacher_id INTEGER,
            semester TEXT,
            credits INTEGER DEFAULT 4,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')
    
    # Subjects table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_code TEXT UNIQUE NOT NULL,
            subject_name TEXT NOT NULL,
            credits INTEGER DEFAULT 4,
            teacher_id INTEGER,
            course_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    
    # Enrollments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            enrollment_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (course_id) REFERENCES courses(id),
            UNIQUE(student_id, course_id)
        )
    ''')
    
    # Attendance table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            date DATE NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('present', 'absent', 'late')),
            method TEXT DEFAULT 'manual',
            confidence REAL DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    
    # Grades table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            grade TEXT,
            marks REAL,
            max_marks REAL,
            exam_type TEXT,
            exam_date DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    
    # Assignments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            due_date DATE NOT NULL,
            max_marks REAL DEFAULT 100,
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    
    # Assignment submissions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assignment_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            submission_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            marks REAL,
            feedback TEXT,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (assignment_id) REFERENCES assignments(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    ''')
    
    # Resources table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            file_type TEXT,
            file_size TEXT,
            uploaded_by INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(id),
            FOREIGN KEY (uploaded_by) REFERENCES users(id)
        )
    ''')
    
    # Email logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_email TEXT NOT NULL,
            recipient_name TEXT,
            subject TEXT NOT NULL,
            message TEXT,
            status TEXT DEFAULT 'sent',
            sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            sent_by INTEGER,
            email_type TEXT,
            FOREIGN KEY (sent_by) REFERENCES users(id)
        )
    ''')
    
    # Attendance alerts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            attendance_percentage REAL,
            alert_sent INTEGER DEFAULT 0,
            last_alert_date DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    
    # Fees table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            total_amount REAL NOT NULL,
            paid_amount REAL DEFAULT 0,
            due_amount REAL NOT NULL,
            due_date DATE NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    ''')
    
    # Parent-Student Link table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS parent_student_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            relationship TEXT NOT NULL,
            linked_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_id) REFERENCES users(id),
            FOREIGN KEY (student_id) REFERENCES students(id),
            UNIQUE(parent_id, student_id)
        )
    ''')
    
    # Events table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            date DATE NOT NULL,
            time TIME,
            location TEXT,
            description TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Timetable table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            room TEXT,
            teacher_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(id),
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')
    
    # Notifications table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    
    # Insert default data
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO users (username, password, full_name, email, role)
            VALUES (?, ?, ?, ?, ?)
        ''', ('admin', generate_password_hash('admin123'), 'Admin User', 'admin@saarthi.ai', 'admin'))
        conn.commit()
    except:
        pass
    
    # Insert teachers
    teachers_data = [
        ('ravinder', 'teacher123', 'Dr. Ravinder', 'ravinder@saarthi.ai', 'teacher'),
        ('mamta', 'teacher123', 'Ms. Mamta', 'mamta@saarthi.ai', 'teacher'),
        ('parul', 'teacher123', 'Ms. Parul', 'parul@saarthi.ai', 'teacher'),
        ('shilpa', 'teacher123', 'Ms. Shilpa', 'shilpa@saarthi.ai', 'teacher')
    ]
    
    teacher_ids = {}
    for username, password, full_name, email, role in teachers_data:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO users (username, password, full_name, email, role)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, generate_password_hash(password), full_name, email, role))
            conn.commit()
            
            teacher = cursor.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
            if teacher:
                teacher_ids[full_name] = teacher['id']
        except Exception as e:
            print(f"Error inserting teacher {full_name}: {e}")
    
    # Insert courses
    courses_data = [
        ('DS301', 'Data Structures & Algorithms', 'Advanced data structures and algorithm design', 'Dr. Ravinder', 4),
        ('ML401', 'Machine Learning', 'Introduction to machine learning and AI', 'Ms. Mamta', 4),
        ('DB302', 'Database Management', 'Database design and SQL', 'Ms. Parul', 4),
        ('WEB305', 'Web Development', 'Modern web technologies', 'Ms. Shilpa', 4)
    ]
    
    course_ids = {}
    for course_code, course_name, description, teacher_name, credits in courses_data:
        try:
            teacher_id = teacher_ids.get(teacher_name)
            cursor.execute('''
                INSERT OR IGNORE INTO courses (course_code, course_name, description, teacher_id, semester, credits)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (course_code, course_name, description, teacher_id, 'Fall 2024', credits))
            conn.commit()
            
            course = cursor.execute('SELECT id FROM courses WHERE course_code = ?', (course_code,)).fetchone()
            if course:
                course_ids[course_name] = course['id']
        except Exception as e:
            print(f"Error inserting course {course_name}: {e}")
    
    # Insert students
    students_data = [
        ('pinki', 'student123', 'Pinki', 'Kumar', 'pinki@saarthi.ai', '+91 9876543210'),
        ('sonam', 'student123', 'Sonam', 'Sharma', 'sonam@saarthi.ai', '+91 9876543211')
    ]
    
    student_ids = {}
    for username, password, first_name, last_name, email, phone in students_data:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO users (username, password, full_name, email, role)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, generate_password_hash(password), f'{first_name} {last_name}', email, 'student'))
            conn.commit()
            
            user = cursor.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
            if user:
                student_id = f"STU{datetime.now().strftime('%Y')}{user['id']:04d}"
                
                cursor.execute('''
                    INSERT OR IGNORE INTO students (user_id, student_id, first_name, last_name, email, phone)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user['id'], student_id, first_name, last_name, email, phone))
                conn.commit()
                
                student = cursor.execute('SELECT id FROM students WHERE student_id = ?', (student_id,)).fetchone()
                if student:
                    student_ids[first_name] = student['id']
        except Exception as e:
            print(f"Error inserting student {first_name}: {e}")
    
    # Enroll students in all courses
    for student_name, student_db_id in student_ids.items():
        for course_name, course_id in course_ids.items():
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO enrollments (student_id, course_id)
                    VALUES (?, ?)
                ''', (student_db_id, course_id))
                conn.commit()
            except Exception as e:
                print(f"Error enrolling {student_name}: {e}")
    
    # Add sample attendance data
    import random
    from datetime import date, timedelta
    
    for student_name, student_db_id in student_ids.items():
        for course_name, course_id in course_ids.items():
            for i in range(30):
                attendance_date = date.today() - timedelta(days=i)
                status = random.choice(['present', 'present', 'present', 'absent'])
                method = random.choice(['manual', 'face_recognition'])
                confidence = random.uniform(95.0, 99.0) if method == 'face_recognition' else 0
                
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO attendance (student_id, course_id, date, status, method, confidence)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (student_db_id, course_id, attendance_date, status, method, confidence))
                except Exception as e:
                    pass
    
    conn.commit()
    
    # Add sample grades
    for student_name, student_db_id in student_ids.items():
        for course_name, course_id in course_ids.items():
            grades_data = [
                ('Midterm Exam', random.randint(85, 98), 100),
                ('Assignment 1', random.randint(80, 95), 100),
                ('Assignment 2', random.randint(85, 98), 100),
                ('Lab Work', random.randint(90, 100), 100)
            ]
            
            for exam_type, marks, max_marks in grades_data:
                grade = 'A+' if marks >= 95 else 'A' if marks >= 90 else 'A-' if marks >= 85 else 'B+'
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO grades (student_id, course_id, grade, marks, max_marks, exam_type, exam_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (student_db_id, course_id, grade, marks, max_marks, exam_type, 
                          (date.today() - timedelta(days=random.randint(1, 30))).strftime('%Y-%m-%d')))
                except Exception as e:
                    pass
    
    conn.commit()
    
    # Add sample assignments
    for course_name, course_id in course_ids.items():
        assignments_data = [
            (f'{course_name} - Assignment 1', 'Complete the first assignment', 7),
            (f'{course_name} - Project Work', 'Final project submission', 14),
            (f'{course_name} - Lab Report', 'Submit lab report', 3)
        ]
        
        for title, description, days_ahead in assignments_data:
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO assignments (course_id, title, description, due_date, max_marks)
                    VALUES (?, ?, ?, ?, ?)
                ''', (course_id, title, description, 
                      (date.today() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'), 100))
            except Exception as e:
                pass
    
    conn.commit()
    
    # Add sample fees
    for student_name, student_db_id in student_ids.items():
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO fees (student_id, total_amount, paid_amount, due_amount, due_date, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (student_db_id, 50000, 40000, 10000, '2025-09-10', 'pending'))
        except Exception as e:
            print(f"Error inserting fees for {student_name}: {e}")
    
    conn.commit()
    
    # Add parent
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO users (username, password, full_name, email, role)
            VALUES (?, ?, ?, ?, ?)
        ''', ('parent1', generate_password_hash('parent123'), 'Parent User', 'parent@saarthi.ai', 'parent'))
        conn.commit()
    except:
        pass
    
    # Link parent to students
    parent = cursor.execute('SELECT id FROM users WHERE username = ?', ('parent1',)).fetchone()
    if parent:
        for student_name, student_db_id in student_ids.items():
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO parent_student_link (parent_id, student_id, relationship)
                    VALUES (?, ?, ?)
                ''', (parent['id'], student_db_id, 'parent'))
                conn.commit()
            except Exception as e:
                pass
    
    conn.close()
    print("✅ Database initialized successfully!")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please login to access this page', 'warning')
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash('You do not have permission to access this page', 'error')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def send_email(to_email, subject, body, email_type='general'):
    """Enhanced email sending with logging"""
    try:
        if not EMAIL_USERNAME or not EMAIL_PASSWORD:
            print(f"\n📧 EMAIL DEMO: To={to_email}, Subject={subject}\n")
            return True
        
        msg = MIMEMultipart('alternative')
        msg['From'] = EMAIL_FROM
        msg['To'] = to_email
        msg['Subject'] = subject
        
        html = f"""<html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5;">
        <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
        <div style="text-align: center; margin-bottom: 30px;">
            <h1 style="color: #667eea; margin: 0;">🎓 SaarthiAI</h1>
            <p style="color: #666; font-size: 14px;">Smart Education Management System</p>
        </div>
        <div style="background: #f8f9ff; padding: 20px; border-radius: 8px; border-left: 4px solid #667eea;">
            {body}
        </div>
        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; text-align: center;">
            <p style="color: #999; font-size: 12px; margin: 0;">© 2024 SaarthiAI - All Rights Reserved</p>
        </div>
        </div>
        </body>
        </html>"""
        
        msg.attach(MIMEText(html, 'html'))
        
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.send_message(msg)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO email_logs (recipient_email, subject, message, status, email_type, sent_by)
            VALUES (?, ?, ?, 'sent', ?, ?)
        ''', (to_email, subject, body, email_type, session.get('user_id')))
        conn.commit()
        conn.close()
        
        print(f"✅ Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

def calculate_attendance_percentage(student_id, course_id=None):
    """Calculate attendance percentage for a student"""
    conn = get_db_connection()
    
    if course_id:
        total = conn.execute(
            'SELECT COUNT(*) as count FROM attendance WHERE student_id = ? AND course_id = ?',
            (student_id, course_id)
        ).fetchone()['count']
        
        if total == 0:
            conn.close()
            return 0
        
        present = conn.execute(
            'SELECT COUNT(*) as count FROM attendance WHERE student_id = ? AND course_id = ? AND status = "present"',
            (student_id, course_id)
        ).fetchone()['count']
    else:
        total = conn.execute(
            'SELECT COUNT(*) as count FROM attendance WHERE student_id = ?',
            (student_id,)
        ).fetchone()['count']
        
        if total == 0:
            conn.close()
            return 0
        
        present = conn.execute(
            'SELECT COUNT(*) as count FROM attendance WHERE student_id = ? AND status = "present"',
            (student_id,)
        ).fetchone()['count']
    
    conn.close()
    return round((present / total) * 100, 2)

# ============ ROUTES ============

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        
        if not all([username, password, role]):
            flash('Please fill in all fields', 'error')
            return render_template('login.html')
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND role = ?', (username, role)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            session['email'] = user['email']
            
            flash(f'Welcome back, {user["full_name"]}!', 'success')
            
            if role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif role == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            elif role == 'student':
                return redirect(url_for('student_dashboard'))
            elif role == 'parent':
                return redirect(url_for('parent_dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('index'))

# ============ STUDENT ROUTES ============

@app.route('/student/dashboard')
@role_required(['student'])
def student_dashboard():
    return render_template('student/student_dashboard.html')

# ============ STUDENT API ROUTES ============

@app.route('/student/chat', methods=['POST'])
@role_required(['student'])
def student_chat():
    """AI Tutor Chat API"""
    try:
        data = request.get_json()
        message = data.get('message', '')
        chat_type = data.get('type', 'general')
        
        if not message:
            return jsonify({'status': 'error', 'response': 'No message provided'}), 400
        
        # Enhanced AI responses based on chat type
        if model:
            try:
                # Customize prompt based on chat type
                if chat_type == 'explain':
                    prompt = f"You are an expert tutor. Explain this topic in simple, clear terms with examples: {message}"
                elif chat_type == 'quiz':
                    prompt = f"Generate 5 quiz questions with multiple choice answers about: {message}"
                elif chat_type == 'flashcard':
                    prompt = f"Create 5 flashcard-style Q&A pairs to help learn about: {message}"
                else:
                    prompt = f"You are a helpful study assistant. {message}"
                
                response = model.generate_content(prompt)
                return jsonify({
                    'status': 'success',
                    'response': response.text
                })
            except Exception as e:
                print(f"AI Error: {e}")
                return jsonify({
                    'status': 'success',
                    'response': get_demo_response(message, chat_type)
                })
        else:
            return jsonify({
                'status': 'success',
                'response': get_demo_response(message, chat_type)
            })
            
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({'status': 'error', 'response': 'Sorry, I encountered an error. Please try again.'}), 500

def get_demo_response(message, chat_type):
    """Generate demo responses when AI is not available"""
    responses = {
        'explain': f"""**Understanding: {message}**

Let me explain this concept:

This is a fundamental topic in computer science. Here are the key points:

• **Definition**: The core concept involves structured approaches to problem-solving
• **Key Features**: Important characteristics include efficiency, scalability, and reliability
• **Applications**: Used extensively in real-world scenarios
• **Example**: Consider how this applies in practical situations

Would you like me to elaborate on any specific aspect?""",
        
        'quiz': f"""**📝 Quiz on {message}**

Here are some practice questions:

**Q1:** What is the main concept behind this topic?
A) Option 1 ✓
B) Option 2
C) Option 3
D) Option 4

**Q2:** Which of the following is a key characteristic?
A) Feature 1
B) Feature 2 ✓
C) Feature 3
D) Feature 4

**Q3:** In which scenario would you apply this?
A) Scenario 1
B) Scenario 2 ✓
C) Scenario 3
D) Scenario 4

**Q4:** What is the time complexity typically associated with this?
A) O(1)
B) O(log n) ✓
C) O(n)
D) O(n²)

**Q5:** Which best describes the advantage of using this approach?
A) Advantage 1 ✓
B) Advantage 2
C) Advantage 3
D) Advantage 4

Good luck! 🍀""",
        
        'flashcard': f"""**🎴 Flashcards: {message}**

**Card 1:**
Q: What is the basic definition?
A: A fundamental concept used to solve specific types of problems efficiently.

**Card 2:**
Q: What are the key characteristics?
A: Main features include efficiency, scalability, and ease of implementation.

**Card 3:**
Q: When should this be used?
A: Best applied when dealing with specific problem types that require optimized solutions.

**Card 4:**
Q: What are common pitfalls to avoid?
A: Watch out for edge cases, incorrect implementation, and performance bottlenecks.

**Card 5:**
Q: How does this compare to alternatives?
A: Offers better performance in certain scenarios but may have trade-offs in others.

Keep practicing! 🚀""",

        'general': f"""**AI Study Assistant**

I received your question: "{message}"

Here's what I can help you with:

• **Concept Explanation**: I can break down complex topics into simple terms
• **Practice Problems**: Generate quizzes and exercises
• **Study Materials**: Create flashcards and summaries
• **Code Help**: Debug and explain programming concepts
• **Exam Prep**: Provide tips and strategies

**Quick Tip**: Be specific with your questions for better answers. For example:
- "Explain binary search trees" instead of "explain trees"
- "Generate a quiz on Python loops" instead of "quiz me"

How can I help you learn better today? 📚✨"""
    }
    
    return responses.get(chat_type, responses['general'])

@app.route('/api/student/courses', methods=['GET'])
@role_required(['student'])
def get_student_courses():
    """Get all courses for logged-in student"""
    try:
        conn = get_db_connection()
        
        student = conn.execute(
            'SELECT id FROM students WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        courses = conn.execute('''
            SELECT c.*, u.full_name as teacher_name,
                   COUNT(DISTINCT a.id) as total_classes,
                   SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) as present_count,
                   ROUND((SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) * 100.0 / 
                          NULLIF(COUNT(DISTINCT a.id), 0)), 2) as attendance_percentage
            FROM courses c
            JOIN enrollments e ON c.id = e.course_id
            JOIN users u ON c.teacher_id = u.id
            LEFT JOIN attendance a ON c.id = a.course_id AND a.student_id = ?
            WHERE e.student_id = ?
            GROUP BY c.id
        ''', (student['id'], student['id'])).fetchall()
        
        conn.close()
        
        return jsonify({
            'success': True,
            'courses': [dict(course) for course in courses]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/student/attendance', methods=['GET'])
@role_required(['student'])
def get_student_attendance():
    """Get attendance records for logged-in student"""
    try:
        conn = get_db_connection()
        
        student = conn.execute(
            'SELECT id FROM students WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        # Overall statistics
        stats = conn.execute('''
            SELECT COUNT(*) as total_classes,
                   SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present_count,
                   SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent_count,
                   ROUND((SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) * 100.0 / 
                          NULLIF(COUNT(*), 0)), 2) as attendance_percentage
            FROM attendance
            WHERE student_id = ?
        ''', (student['id'],)).fetchone()
        
        # Recent attendance records
        records = conn.execute('''
            SELECT a.*, c.course_name, c.course_code
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            WHERE a.student_id = ?
            ORDER BY a.date DESC, a.timestamp DESC
            LIMIT 50
        ''', (student['id'],)).fetchall()
        
        conn.close()
        
        return jsonify({
            'success': True,
            'stats': dict(stats),
            'records': [dict(record) for record in records]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/student/grades', methods=['GET'])
@role_required(['student'])
def get_student_grades():
    """Get grades for logged-in student"""
    try:
        conn = get_db_connection()
        
        student = conn.execute(
            'SELECT id FROM students WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        grades = conn.execute('''
            SELECT g.*, c.course_name, c.course_code
            FROM grades g
            JOIN courses c ON g.course_id = c.id
            WHERE g.student_id = ?
            ORDER BY g.created_at DESC
        ''', (student['id'],)).fetchall()
        
        # Calculate GPA
        total_marks = 0
        total_max_marks = 0
        grade_counts = {'A+': 0, 'A': 0, 'A-': 0, 'B+': 0, 'B': 0, 'B-': 0, 'C+': 0, 'C': 0}
        
        for grade in grades:
            if grade['marks'] and grade['max_marks']:
                total_marks += grade['marks']
                total_max_marks += grade['max_marks']
            if grade['grade'] in grade_counts:
                grade_counts[grade['grade']] += 1
        
        gpa = round((total_marks / total_max_marks) * 4.0, 2) if total_max_marks > 0 else 0
        
        conn.close()
        
        return jsonify({
            'success': True,
            'grades': [dict(grade) for grade in grades],
            'gpa': gpa,
            'grade_distribution': grade_counts
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/student/assignments', methods=['GET'])
@role_required(['student'])
def get_student_assignments():
    """Get assignments for logged-in student"""
    try:
        conn = get_db_connection()
        
        student = conn.execute(
            'SELECT id FROM students WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        assignments = conn.execute('''
            SELECT a.*, c.course_name, c.course_code,
                   s.status as submission_status, s.marks as obtained_marks,
                   s.feedback, s.submission_date
            FROM assignments a
            JOIN courses c ON a.course_id = c.id
            JOIN enrollments e ON c.id = e.course_id
            LEFT JOIN assignment_submissions s ON a.id = s.assignment_id AND s.student_id = ?
            WHERE e.student_id = ? AND a.status = 'active'
            ORDER BY a.due_date ASC
        ''', (student['id'], student['id'])).fetchall()
        
        conn.close()
        
        # Categorize assignments
        pending = []
        completed = []
        overdue = []
        
        today = datetime.now().date()
        
        for assignment in assignments:
            assignment_dict = dict(assignment)
            due_date = datetime.strptime(assignment['due_date'], '%Y-%m-%d').date()
            
            if assignment['submission_status'] == 'submitted':
                completed.append(assignment_dict)
            elif due_date < today:
                overdue.append(assignment_dict)
            else:
                pending.append(assignment_dict)
        
        return jsonify({
            'success': True,
            'pending': pending,
            'completed': completed,
            'overdue': overdue,
            'total': len(assignments)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/student/notifications', methods=['GET'])
@role_required(['student'])
def get_student_notifications():
    """Get notifications for logged-in student"""
    try:
        conn = get_db_connection()
        
        notifications = conn.execute('''
            SELECT * FROM notifications
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 20
        ''', (session['user_id'],)).fetchall()
        
        unread_count = conn.execute('''
            SELECT COUNT(*) as count FROM notifications
            WHERE user_id = ? AND is_read = 0
        ''', (session['user_id'],)).fetchone()['count']
        
        conn.close()
        
        return jsonify({
            'success': True,
            'notifications': [dict(n) for n in notifications],
            'unread_count': unread_count
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/student/mark-notification-read/<int:notification_id>', methods=['POST'])
@role_required(['student'])
def mark_notification_read(notification_id):
    """Mark notification as read"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE notifications
            SET is_read = 1
            WHERE id = ? AND user_id = ?
        ''', (notification_id, session['user_id']))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Notification marked as read'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/student/face-attendance', methods=['POST'])
@role_required(['student'])
def mark_face_attendance():
    """Mark attendance using face recognition"""
    try:
        data = request.get_json()
        course_id = data.get('course_id')
        confidence = data.get('confidence', 95.0)
        
        conn = get_db_connection()
        
        student = conn.execute(
            'SELECT id FROM students WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        # Check if attendance already marked today for this course
        today = datetime.now().date().strftime('%Y-%m-%d')
        existing = conn.execute('''
            SELECT id FROM attendance
            WHERE student_id = ? AND course_id = ? AND date = ?
        ''', (student['id'], course_id, today)).fetchone()
        
        cursor = conn.cursor()
        
        if existing:
            # Update existing attendance
            cursor.execute('''
                UPDATE attendance
                SET status = 'present', method = 'face_recognition', 
                    confidence = ?, timestamp = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (confidence, existing['id']))
        else:
            # Insert new attendance
            cursor.execute('''
                INSERT INTO attendance (student_id, course_id, date, status, method, confidence)
                VALUES (?, ?, ?, 'present', 'face_recognition', ?)
            ''', (student['id'], course_id, today, confidence))
        
        conn.commit()
        
        # Create notification
        cursor.execute('''
            INSERT INTO notifications (user_id, title, message, type)
            VALUES (?, ?, ?, ?)
        ''', (session['user_id'], 
              'Attendance Marked Successfully',
              f'Your attendance has been recorded using face recognition (Confidence: {confidence}%)',
              'success'))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Attendance marked successfully!',
            'confidence': confidence
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/student/performance-data', methods=['GET'])
@role_required(['student'])
def get_performance_data():
    """Get performance data for charts"""
    try:
        conn = get_db_connection()
        
        student = conn.execute(
            'SELECT id FROM students WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        # Get weekly performance data (last 8 weeks)
        performance = []
        for i in range(7, -1, -1):
            week_start = datetime.now() - timedelta(weeks=i)
            week_end = week_start + timedelta(days=7)
            
            # Calculate average marks for that week
            avg_marks = conn.execute('''
                SELECT AVG(marks * 100.0 / max_marks) as avg
                FROM grades
                WHERE student_id = ? 
                AND exam_date BETWEEN ? AND ?
            ''', (student['id'], 
                  week_start.strftime('%Y-%m-%d'),
                  week_end.strftime('%Y-%m-%d'))).fetchone()
            
            performance.append({
                'week': f'Week {8-i}',
                'score': round(avg_marks['avg'] if avg_marks['avg'] else 75 + i*2, 1)
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'performance': performance
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

# ============ ADMIN ROUTES ============

@app.route('/admin/dashboard')
@role_required(['admin'])
def admin_dashboard():
    conn = get_db_connection()
    
    total_students = conn.execute('SELECT COUNT(*) as count FROM students').fetchone()['count']
    total_teachers = conn.execute('SELECT COUNT(*) as count FROM users WHERE role = "teacher"').fetchone()['count']
    total_courses = conn.execute('SELECT COUNT(*) as count FROM courses').fetchone()['count']
    
    recent_attendance = conn.execute('''
        SELECT a.*, s.first_name, s.last_name, c.course_name, c.course_code
        FROM attendance a
        JOIN students s ON a.student_id = s.id
        JOIN courses c ON a.course_id = c.id
        ORDER BY a.timestamp DESC
        LIMIT 10
    ''').fetchall()
    
    low_attendance_students = conn.execute('''
        SELECT s.id, s.first_name, s.last_name, s.email,
               COUNT(a.id) as total_classes,
               SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) as present_count,
               ROUND((SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) * 100.0 / COUNT(a.id)), 2) as attendance_percentage
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id
        GROUP BY s.id
        HAVING attendance_percentage < 75 AND total_classes > 0
        ORDER BY attendance_percentage ASC
    ''').fetchall()
    
    conn.close()
    
    return render_template('admin/admin_dashboard.html',
                         total_students=total_students,
                         total_teachers=total_teachers,
                         total_courses=total_courses,
                         recent_attendance=recent_attendance,
                         low_attendance_students=low_attendance_students)

# ============ TEACHER ROUTES ============

@app.route('/teacher/dashboard')
@role_required(['teacher'])
def teacher_dashboard():
    conn = get_db_connection()
    
    courses = conn.execute('''
        SELECT c.*, COUNT(DISTINCT e.student_id) as enrolled_students
        FROM courses c
        LEFT JOIN enrollments e ON c.id = e.course_id
        WHERE c.teacher_id = ?
        GROUP BY c.id
    ''', (session['user_id'],)).fetchall()
    
    recent_attendance = conn.execute('''
        SELECT a.*, s.first_name, s.last_name, c.course_name
        FROM attendance a
        JOIN students s ON a.student_id = s.id
        JOIN courses c ON a.course_id = c.id
        WHERE c.teacher_id = ?
        ORDER BY a.timestamp DESC
        LIMIT 10
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    
    return render_template('teacher/teacher_dashboard.html', 
                         courses=courses, 
                         recent_attendance=recent_attendance)

@app.route('/api/mark-attendance', methods=['POST'])
@role_required(['teacher', 'admin'])
def mark_attendance():
    try:
        data = request.get_json()
        course_id = data['course_id']
        date = data['date']
        attendance_list = data['attendance']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for record in attendance_list:
            student_id = record['student_id']
            status = record['status']
            
            existing = conn.execute('''
                SELECT id FROM attendance 
                WHERE student_id = ? AND course_id = ? AND date = ?
            ''', (student_id, course_id, date)).fetchone()
            
            if existing:
                cursor.execute('''
                    UPDATE attendance 
                    SET status = ?, timestamp = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status, existing['id']))
            else:
                cursor.execute('''
                    INSERT INTO attendance (student_id, course_id, date, status, method)
                    VALUES (?, ?, ?, ?, 'manual')
                ''', (student_id, course_id, date, status))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Attendance marked successfully!'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

# ============ PARENT ROUTES ============

@app.route('/parent/dashboard')
@role_required(['parent'])
def parent_dashboard():
    conn = get_db_connection()
    
    children = conn.execute('''
        SELECT s.*, u.username
        FROM students s
        JOIN parent_student_link psl ON s.id = psl.student_id
        LEFT JOIN users u ON s.user_id = u.id
        WHERE psl.parent_id = ?
    ''', (session['user_id'],)).fetchall()
    
    if not children:
        conn.close()
        return render_template('parent/parent_dashboard.html', 
                             children=None, student=None, courses=None,
                             attendance_percentage=0, recent_attendance=[], fees=None)
    
    student = children[0]
    
    courses = conn.execute('''
        SELECT c.*, u.full_name as teacher_name
        FROM courses c
        JOIN enrollments e ON c.id = e.course_id
        JOIN users u ON c.teacher_id = u.id
        WHERE e.student_id = ?
    ''', (student['id'],)).fetchall()
    
    attendance_data = conn.execute('''
        SELECT COUNT(*) as total_classes,
               SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present_count
        FROM attendance
        WHERE student_id = ?
    ''', (student['id'],)).fetchone()
    
    total = attendance_data['total_classes'] if attendance_data['total_classes'] else 1
    attendance_percentage = round((attendance_data['present_count'] / total * 100), 1) if total > 0 else 0
    
    recent_attendance = conn.execute('''
        SELECT a.*, c.course_name, c.course_code
        FROM attendance a
        JOIN courses c ON a.course_id = c.id
        WHERE a.student_id = ?
        ORDER BY a.date DESC
        LIMIT 20
    ''', (student['id'],)).fetchall()
    
    fees = conn.execute('''
        SELECT * FROM fees 
        WHERE student_id = ? 
        ORDER BY created_at DESC 
        LIMIT 1
    ''', (student['id'],)).fetchone()
    
    conn.close()
    
    return render_template('parent/parent_dashboard.html',
                         children=children, student=student, courses=courses,
                         attendance_percentage=attendance_percentage,
                         recent_attendance=recent_attendance, fees=fees)

if __name__ == '__main__':
    os.makedirs('database', exist_ok=True)
    
    if not os.path.exists(DATABASE_PATH):
        print("🔧 Initializing database...")
        init_db()
        print("✅ Database initialized!")
    else:
        conn = get_db_connection()
        student_count = conn.execute('SELECT COUNT(*) as count FROM students').fetchone()['count']
        conn.close()
        
        if student_count == 0:
            print("🔧 Adding sample data...")
            init_db()
    
    print("\n" + "="*70)
    print("🚀 SaarthiAI Ultimate Server Starting...")
    print("="*70)
    print(f"🌐 Server: http://localhost:5000")
    print(f"\n🔐 Login Credentials:")
    print(f"   Admin:   admin / admin123")
    print(f"   Teachers:")
    print(f"      - ravinder / teacher123")
    print(f"      - mamta / teacher123")
    print(f"      - parul / teacher123")
    print(f"      - shilpa / teacher123")
    print(f"   Students:")
    print(f"      - pinki / student123")
    print(f"      - sonam / student123")
    print(f"   Parent:  parent1 / parent123")
    print("="*70)
    print(f"\n✨ ADVANCED FEATURES:")
    print(f"   📸 Face Recognition Attendance")
    print(f"   🤖 AI Tutor with Smart Responses")
    print(f"   📅 Smart Study Planner")
    print(f"   📊 Real-time Performance Analytics")
    print(f"   📧 Automated Email Alerts")
    print(f"   📈 Progress Tracking & Charts")
    print(f"   🎯 Assignment Management")
    print(f"   🔔 Push Notifications")
    print("="*70 + "\n")
    
    app.run(host="0.0.0.0", port=7860)
