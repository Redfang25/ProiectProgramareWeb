from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = 'medtrack-secret-2026-change-in-prod'
DATABASE = 'medtrack.db'

# ──────────────────────────── DB HELPERS ────────────────────────────

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            dosage TEXT,
            instructions TEXT
        );
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medication_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            days_of_week TEXT NOT NULL,
            times TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT
        );
        CREATE TABLE IF NOT EXISTS doses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            medication_id INTEGER NOT NULL,
            dose_date TEXT NOT NULL,
            dose_time TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            confirmed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS doctor_patient (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            UNIQUE(doctor_id, patient_id)
        );
    ''')
    db.commit()
    db.close()

def generate_doses(db, schedule_id, medication_id, patient_id, days_str, times_str, start_str, end_str):
    """Generate dose records for a schedule. Only deletes pending doses."""
    db.execute("DELETE FROM doses WHERE schedule_id=? AND status='pending'", (schedule_id,))
    start = datetime.strptime(start_str, '%Y-%m-%d').date()
    end = datetime.strptime(end_str, '%Y-%m-%d').date() if end_str else start + timedelta(days=90)
    days = [int(d) for d in days_str.split(',') if d.strip()]
    times = [t.strip() for t in times_str.split(',') if t.strip()]
    current = start
    while current <= end:
        if current.weekday() in days:
            for t in times:
                db.execute(
                    'INSERT INTO doses (schedule_id, patient_id, medication_id, dose_date, dose_time, status) VALUES (?,?,?,?,?,?)',
                    (schedule_id, patient_id, medication_id, current.isoformat(), t, 'pending')
                )
        current += timedelta(days=1)

# ──────────────────────────── AUTH DECORATOR ────────────────────────────

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('Acces neautorizat.', 'danger')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ──────────────────────────── GENERAL ROUTES ────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('patient_today') if session['role'] == 'patient' else url_for('doctor_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        role = request.form['role']
        if not name or not email or not password or role not in ('patient', 'doctor'):
            flash('Completați toate câmpurile.', 'danger')
            return render_template('register.html')
        db = get_db()
        if db.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone():
            flash('Email-ul este deja folosit.', 'danger')
            db.close()
            return render_template('register.html')
        db.execute('INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)',
                   (name, email, generate_password_hash(password), role))
        db.commit()
        db.close()
        flash('Cont creat cu succes! Te poți autentifica.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        db.close()
        if not user or not check_password_hash(user['password_hash'], password):
            flash('Email sau parolă incorectă.', 'danger')
            return render_template('login.html')
        session['user_id'] = user['id']
        session['name'] = user['name']
        session['role'] = user['role']
        return redirect(url_for('patient_today') if user['role'] == 'patient' else url_for('doctor_dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ──────────────────────────── PATIENT ROUTES ────────────────────────────

@app.route('/patient/today')
@login_required(role='patient')
def patient_today():
    db = get_db()
    today_str = date.today().isoformat()
    doses = db.execute('''
        SELECT d.id, d.dose_time, d.status, m.name as med_name, m.dosage, m.instructions
        FROM doses d JOIN medications m ON d.medication_id=m.id
        WHERE d.patient_id=? AND d.dose_date=?
        ORDER BY d.dose_time
    ''', (session['user_id'], today_str)).fetchall()
    db.close()
    return render_template('patient/today.html', doses=doses,
                           today=datetime.today().strftime('%d %B %Y'))

@app.route('/patient/doses/<int:dose_id>/confirm', methods=['POST'])
@login_required(role='patient')
def confirm_dose(dose_id):
    status = request.form.get('status')
    if status not in ('taken', 'missed'):
        return redirect(url_for('patient_today'))
    db = get_db()
    db.execute("UPDATE doses SET status=?, confirmed_at=? WHERE id=? AND patient_id=?",
               (status, datetime.now().isoformat(), dose_id, session['user_id']))
    db.commit()
    db.close()
    return redirect(url_for('patient_today'))

@app.route('/patient/medications')
@login_required(role='patient')
def patient_medications():
    db = get_db()
    meds = db.execute('''
        SELECT m.id, m.name, m.dosage, m.instructions,
               s.id as schedule_id, s.days_of_week, s.times, s.start_date, s.end_date
        FROM medications m
        LEFT JOIN schedules s ON s.medication_id=m.id
        WHERE m.patient_id=?
        GROUP BY m.id
    ''', (session['user_id'],)).fetchall()
    db.close()
    return render_template('patient/medications.html', medications=meds,
                           today=date.today().isoformat())

@app.route('/patient/medications/add', methods=['POST'])
@login_required(role='patient')
def add_medication():
    name = request.form['name'].strip()
    dosage = request.form.get('dosage', '').strip()
    instructions = request.form.get('instructions', '').strip()
    days = request.form.getlist('days')
    times = request.form.get('times', '').strip()
    start_date = request.form.get('start_date') or date.today().isoformat()
    end_date = request.form.get('end_date', '').strip() or None
    if not name or not days or not times:
        flash('Completați câmpurile obligatorii (Nume, Zile, Ore).', 'danger')
        return redirect(url_for('patient_medications'))
    days_str = ','.join(days)
    db = get_db()
    cur = db.execute('INSERT INTO medications (patient_id,name,dosage,instructions) VALUES (?,?,?,?)',
                     (session['user_id'], name, dosage, instructions))
    med_id = cur.lastrowid
    cur2 = db.execute('INSERT INTO schedules (medication_id,patient_id,days_of_week,times,start_date,end_date) VALUES (?,?,?,?,?,?)',
                      (med_id, session['user_id'], days_str, times, start_date, end_date))
    db.commit()
    generate_doses(db, cur2.lastrowid, med_id, session['user_id'], days_str, times, start_date, end_date)
    db.commit()
    db.close()
    flash(f'Medicamentul "{name}" a fost adăugat.', 'success')
    return redirect(url_for('patient_medications'))

@app.route('/patient/medications/<int:med_id>/edit', methods=['POST'])
@login_required(role='patient')
def edit_medication(med_id):
    name = request.form['name'].strip()
    dosage = request.form.get('dosage', '').strip()
    instructions = request.form.get('instructions', '').strip()
    days = request.form.getlist('days')
    times = request.form.get('times', '').strip()
    start_date = request.form.get('start_date') or date.today().isoformat()
    end_date = request.form.get('end_date', '').strip() or None
    if not name or not days or not times:
        flash('Completați câmpurile obligatorii.', 'danger')
        return redirect(url_for('patient_medications'))
    days_str = ','.join(days)
    db = get_db()
    db.execute('UPDATE medications SET name=?,dosage=?,instructions=? WHERE id=? AND patient_id=?',
               (name, dosage, instructions, med_id, session['user_id']))
    sched = db.execute('SELECT id FROM schedules WHERE medication_id=? AND patient_id=?',
                       (med_id, session['user_id'])).fetchone()
    if sched:
        db.execute('UPDATE schedules SET days_of_week=?,times=?,start_date=?,end_date=? WHERE id=?',
                   (days_str, times, start_date, end_date, sched['id']))
        db.commit()
        generate_doses(db, sched['id'], med_id, session['user_id'], days_str, times, start_date, end_date)
    else:
        cur = db.execute('INSERT INTO schedules (medication_id,patient_id,days_of_week,times,start_date,end_date) VALUES (?,?,?,?,?,?)',
                         (med_id, session['user_id'], days_str, times, start_date, end_date))
        db.commit()
        generate_doses(db, cur.lastrowid, med_id, session['user_id'], days_str, times, start_date, end_date)
    db.commit()
    db.close()
    flash('Medicament actualizat cu succes.', 'success')
    return redirect(url_for('patient_medications'))

@app.route('/patient/medications/<int:med_id>/delete', methods=['POST'])
@login_required(role='patient')
def delete_medication(med_id):
    db = get_db()
    db.execute('DELETE FROM doses WHERE medication_id=? AND patient_id=?', (med_id, session['user_id']))
    db.execute('DELETE FROM schedules WHERE medication_id=? AND patient_id=?', (med_id, session['user_id']))
    db.execute('DELETE FROM medications WHERE id=? AND patient_id=?', (med_id, session['user_id']))
    db.commit()
    db.close()
    flash('Medicament șters.', 'success')
    return redirect(url_for('patient_medications'))

@app.route('/patient/history')
@login_required(role='patient')
def patient_history():
    db = get_db()
    doses = db.execute('''
        SELECT d.dose_date, d.dose_time, d.status, m.name as med_name, m.dosage
        FROM doses d JOIN medications m ON d.medication_id=m.id
        WHERE d.patient_id=? AND d.status!='pending'
        ORDER BY d.dose_date DESC, d.dose_time DESC
    ''', (session['user_id'],)).fetchall()
    stats = db.execute('''
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status='taken' THEN 1 ELSE 0 END) as taken,
               SUM(CASE WHEN status='missed' THEN 1 ELSE 0 END) as missed
        FROM doses WHERE patient_id=? AND status!='pending'
    ''', (session['user_id'],)).fetchone()
    db.close()
    return render_template('patient/history.html', doses=doses, stats=stats)

@app.route('/patient/doctors')
@login_required(role='patient')
def patient_doctors():
    db = get_db()
    doctors = db.execute('''
        SELECT u.id, u.name, u.email, dp.status, dp.id as dp_id
        FROM doctor_patient dp JOIN users u ON dp.doctor_id=u.id
        WHERE dp.patient_id=?
    ''', (session['user_id'],)).fetchall()
    db.close()
    return render_template('patient/doctors.html', doctors=doctors)

@app.route('/patient/doctors/add', methods=['POST'])
@login_required(role='patient')
def add_doctor():
    email = request.form['email'].strip().lower()
    db = get_db()
    doctor = db.execute("SELECT id FROM users WHERE email=? AND role='doctor'", (email,)).fetchone()
    if not doctor:
        flash('Nu există niciun medic înregistrat cu acest email.', 'danger')
        db.close()
        return redirect(url_for('patient_doctors'))
    existing = db.execute('SELECT id FROM doctor_patient WHERE doctor_id=? AND patient_id=?',
                          (doctor['id'], session['user_id'])).fetchone()
    if existing:
        flash('Medicul este deja în lista ta.', 'warning')
        db.close()
        return redirect(url_for('patient_doctors'))
    db.execute("INSERT INTO doctor_patient (doctor_id,patient_id,status) VALUES (?,?,'pending')",
               (doctor['id'], session['user_id']))
    db.commit()
    db.close()
    flash('Invitație trimisă medicului.', 'success')
    return redirect(url_for('patient_doctors'))

@app.route('/patient/doctors/<int:dp_id>/remove', methods=['POST'])
@login_required(role='patient')
def remove_doctor(dp_id):
    db = get_db()
    db.execute('DELETE FROM doctor_patient WHERE id=? AND patient_id=?', (dp_id, session['user_id']))
    db.commit()
    db.close()
    flash('Accesul medicului a fost revocat.', 'success')
    return redirect(url_for('patient_doctors'))

# ──────────────────────────── DOCTOR ROUTES ────────────────────────────

@app.route('/doctor/dashboard')
@login_required(role='doctor')
def doctor_dashboard():
    db = get_db()
    pending = db.execute('''
        SELECT dp.id, u.name, u.email
        FROM doctor_patient dp JOIN users u ON dp.patient_id=u.id
        WHERE dp.doctor_id=? AND dp.status='pending'
    ''', (session['user_id'],)).fetchall()
    db.close()
    return render_template('doctor/dashboard.html', pending=pending)

@app.route('/doctor/invitations/<int:dp_id>/accept', methods=['POST'])
@login_required(role='doctor')
def accept_invitation(dp_id):
    db = get_db()
    db.execute("UPDATE doctor_patient SET status='accepted' WHERE id=? AND doctor_id=?",
               (dp_id, session['user_id']))
    db.commit()
    db.close()
    flash('Invitație acceptată.', 'success')
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/invitations/<int:dp_id>/reject', methods=['POST'])
@login_required(role='doctor')
def reject_invitation(dp_id):
    db = get_db()
    db.execute('DELETE FROM doctor_patient WHERE id=? AND doctor_id=?', (dp_id, session['user_id']))
    db.commit()
    db.close()
    flash('Invitație respinsă.', 'info')
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/patients')
@login_required(role='doctor')
def doctor_patients():
    db = get_db()
    patients = db.execute('''
        SELECT u.id, u.name, u.email, dp.id as dp_id
        FROM doctor_patient dp JOIN users u ON dp.patient_id=u.id
        WHERE dp.doctor_id=? AND dp.status='accepted'
    ''', (session['user_id'],)).fetchall()
    db.close()
    return render_template('doctor/patients.html', patients=patients)

@app.route('/doctor/patients/<int:patient_id>')
@login_required(role='doctor')
def doctor_patient_detail(patient_id):
    db = get_db()
    if not db.execute("SELECT id FROM doctor_patient WHERE doctor_id=? AND patient_id=? AND status='accepted'",
                      (session['user_id'], patient_id)).fetchone():
        flash('Nu aveți acces la acest pacient.', 'danger')
        return redirect(url_for('doctor_patients'))
    patient = db.execute('SELECT id, name, email FROM users WHERE id=?', (patient_id,)).fetchone()
    medications = db.execute('''
        SELECT m.name, m.dosage, m.instructions, s.days_of_week, s.times, s.start_date, s.end_date
        FROM medications m LEFT JOIN schedules s ON s.medication_id=m.id
        WHERE m.patient_id=? GROUP BY m.id
    ''', (patient_id,)).fetchall()
    history = db.execute('''
        SELECT d.dose_date, d.dose_time, d.status, m.name as med_name, m.dosage
        FROM doses d JOIN medications m ON d.medication_id=m.id
        WHERE d.patient_id=? AND d.status!='pending'
        ORDER BY d.dose_date DESC, d.dose_time DESC LIMIT 100
    ''', (patient_id,)).fetchall()
    stats = db.execute('''
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status='taken' THEN 1 ELSE 0 END) as taken,
               SUM(CASE WHEN status='missed' THEN 1 ELSE 0 END) as missed
        FROM doses WHERE patient_id=? AND status!='pending'
    ''', (patient_id,)).fetchone()
    db.close()
    return render_template('doctor/patient_detail.html',
                           patient=patient, medications=medications,
                           history=history, stats=stats)

# ──────────────────────────── ENTRY POINT ────────────────────────────

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
