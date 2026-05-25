from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, hashlib
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
            prescribed_by INTEGER,
            name TEXT NOT NULL,
            dosage TEXT,
            instructions TEXT,
            dispensed INTEGER DEFAULT 0,
            dispensed_at TEXT
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
            UNIQUE(doctor_id, patient_id)
        );
    ''')
    db.commit()
    db.close()


def pharmacy_token(user_id):
    return hashlib.sha256(f'medtrack-pharmacy-{user_id}-secret2026'.encode()).hexdigest()[:20]

def generate_doses(db, schedule_id, medication_id, patient_id, days_str, times_str, start_str, end_str):
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
                    'INSERT INTO doses (schedule_id,patient_id,medication_id,dose_date,dose_time,status) VALUES (?,?,?,?,?,?)',
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
        return redirect(url_for('patient_today') if session['role'] == 'patient' else url_for('doctor_patients'))
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
        return redirect(url_for('patient_today') if user['role'] == 'patient' else url_for('doctor_patients'))
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
        SELECT d.id, d.dose_time, d.status, m.name as med_name, m.dosage, m.instructions,
               u.name as doctor_name
        FROM doses d
        JOIN medications m ON d.medication_id = m.id
        LEFT JOIN users u ON m.prescribed_by = u.id
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
               u.name as doctor_name,
               s.id as schedule_id, s.days_of_week, s.times, s.start_date, s.end_date
        FROM medications m
        LEFT JOIN users u ON m.prescribed_by = u.id
        LEFT JOIN schedules s ON s.medication_id = m.id
        WHERE m.patient_id=?
        GROUP BY m.id
        ORDER BY m.id DESC
    ''', (session['user_id'],)).fetchall()
    db.close()
    return render_template('patient/medications.html', medications=meds,
                           today=date.today().isoformat())

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
        SELECT u.name, u.email
        FROM doctor_patient dp JOIN users u ON dp.doctor_id=u.id
        WHERE dp.patient_id=?
    ''', (session['user_id'],)).fetchall()
    db.close()
    return render_template('patient/doctors.html', doctors=doctors)

# ──────────────────────────── DOCTOR ROUTES ────────────────────────────

@app.route('/doctor/patients')
@login_required(role='doctor')
def doctor_patients():
    db = get_db()
    patients = db.execute('''
        SELECT u.id, u.name, u.email,
               COUNT(DISTINCT m.id) as med_count,
               SUM(CASE WHEN d.status='pending' AND d.dose_date=? THEN 1 ELSE 0 END) as today_pending
        FROM doctor_patient dp
        JOIN users u ON dp.patient_id = u.id
        LEFT JOIN medications m ON m.patient_id = u.id AND m.prescribed_by = ?
        LEFT JOIN doses d ON d.patient_id = u.id AND d.dose_date = ?
        WHERE dp.doctor_id=?
        GROUP BY u.id
    ''', (date.today().isoformat(), session['user_id'], date.today().isoformat(), session['user_id'])).fetchall()
    db.close()
    return render_template('doctor/patients.html', patients=patients)

@app.route('/doctor/patients/add', methods=['POST'])
@login_required(role='doctor')
def doctor_add_patient():
    email = request.form['email'].strip().lower()
    db = get_db()
    patient = db.execute("SELECT id FROM users WHERE email=? AND role='patient'", (email,)).fetchone()
    if not patient:
        flash('Nu există niciun pacient înregistrat cu acest email.', 'danger')
        db.close()
        return redirect(url_for('doctor_patients'))
    if db.execute('SELECT id FROM doctor_patient WHERE doctor_id=? AND patient_id=?',
                  (session['user_id'], patient['id'])).fetchone():
        flash('Pacientul este deja în lista ta.', 'warning')
        db.close()
        return redirect(url_for('doctor_patients'))
    db.execute('INSERT INTO doctor_patient (doctor_id, patient_id) VALUES (?,?)',
               (session['user_id'], patient['id']))
    db.commit()
    db.close()
    flash(f'Pacientul a fost adăugat cu succes.', 'success')
    return redirect(url_for('doctor_patients'))

@app.route('/doctor/patients/<int:patient_id>/remove', methods=['POST'])
@login_required(role='doctor')
def doctor_remove_patient(patient_id):
    db = get_db()
    db.execute('DELETE FROM doctor_patient WHERE doctor_id=? AND patient_id=?',
               (session['user_id'], patient_id))
    db.commit()
    db.close()
    flash('Pacientul a fost eliminat.', 'info')
    return redirect(url_for('doctor_patients'))

@app.route('/doctor/patients/<int:patient_id>')
@login_required(role='doctor')
def doctor_patient_detail(patient_id):
    db = get_db()
    if not db.execute('SELECT id FROM doctor_patient WHERE doctor_id=? AND patient_id=?',
                      (session['user_id'], patient_id)).fetchone():
        flash('Nu aveți acces la acest pacient.', 'danger')
        return redirect(url_for('doctor_patients'))
    patient = db.execute('SELECT id, name, email FROM users WHERE id=?', (patient_id,)).fetchone()
    medications = db.execute('''
        SELECT m.id, m.name, m.dosage, m.instructions,
               s.id as schedule_id, s.days_of_week, s.times, s.start_date, s.end_date
        FROM medications m
        LEFT JOIN schedules s ON s.medication_id = m.id
        WHERE m.patient_id=? AND m.prescribed_by=?
        GROUP BY m.id
        ORDER BY m.id DESC
    ''', (patient_id, session['user_id'])).fetchall()
    history = db.execute('''
        SELECT d.dose_date, d.dose_time, d.status, m.name as med_name, m.dosage
        FROM doses d JOIN medications m ON d.medication_id=m.id
        WHERE d.patient_id=? AND d.status!='pending' AND m.prescribed_by=?
        ORDER BY d.dose_date DESC, d.dose_time DESC LIMIT 100
    ''', (patient_id, session['user_id'])).fetchall()
    stats = db.execute('''
        SELECT COUNT(*) as total,
               SUM(CASE WHEN d.status='taken' THEN 1 ELSE 0 END) as taken,
               SUM(CASE WHEN d.status='missed' THEN 1 ELSE 0 END) as missed
        FROM doses d JOIN medications m ON d.medication_id=m.id
        WHERE d.patient_id=? AND d.status!='pending' AND m.prescribed_by=?
    ''', (patient_id, session['user_id'])).fetchone()
    db.close()
    return render_template('doctor/patient_detail.html',
                           patient=patient, medications=medications,
                           history=history, stats=stats,
                           today=date.today().isoformat())

@app.route('/doctor/patients/<int:patient_id>/prescribe', methods=['POST'])
@login_required(role='doctor')
def doctor_prescribe(patient_id):
    db = get_db()
    if not db.execute('SELECT id FROM doctor_patient WHERE doctor_id=? AND patient_id=?',
                      (session['user_id'], patient_id)).fetchone():
        flash('Acces neautorizat.', 'danger')
        return redirect(url_for('doctor_patients'))
    name = request.form['name'].strip()
    dosage = request.form.get('dosage', '').strip()
    instructions = request.form.get('instructions', '').strip()
    days = request.form.getlist('days')
    times = request.form.get('times', '').strip()
    start_date = request.form.get('start_date') or date.today().isoformat()
    end_date = request.form.get('end_date', '').strip() or None
    if not name or not days or not times:
        flash('Completați câmpurile obligatorii.', 'danger')
        return redirect(url_for('doctor_patient_detail', patient_id=patient_id))
    days_str = ','.join(days)
    cur = db.execute(
        'INSERT INTO medications (patient_id, prescribed_by, name, dosage, instructions) VALUES (?,?,?,?,?)',
        (patient_id, session['user_id'], name, dosage, instructions)
    )
    med_id = cur.lastrowid
    cur2 = db.execute(
        'INSERT INTO schedules (medication_id, patient_id, days_of_week, times, start_date, end_date) VALUES (?,?,?,?,?,?)',
        (med_id, patient_id, days_str, times, start_date, end_date)
    )
    db.commit()
    generate_doses(db, cur2.lastrowid, med_id, patient_id, days_str, times, start_date, end_date)
    db.commit()
    db.close()
    flash(f'Medicamentul "{name}" a fost prescris cu succes.', 'success')
    return redirect(url_for('doctor_patient_detail', patient_id=patient_id))

@app.route('/doctor/patients/<int:patient_id>/medications/<int:med_id>/delete', methods=['POST'])
@login_required(role='doctor')
def doctor_delete_medication(patient_id, med_id):
    db = get_db()
    if not db.execute('SELECT id FROM doctor_patient WHERE doctor_id=? AND patient_id=?',
                      (session['user_id'], patient_id)).fetchone():
        flash('Acces neautorizat.', 'danger')
        return redirect(url_for('doctor_patients'))
    db.execute("DELETE FROM doses WHERE medication_id=? AND patient_id=?", (med_id, patient_id))
    db.execute("DELETE FROM schedules WHERE medication_id=? AND patient_id=?", (med_id, patient_id))
    db.execute("DELETE FROM medications WHERE id=? AND prescribed_by=?", (med_id, session['user_id']))
    db.commit()
    db.close()
    flash('Medicamentul a fost eliminat din tratament.', 'success')
    return redirect(url_for('doctor_patient_detail', patient_id=patient_id))

# ──────────────────────────── ENTRY POINT ────────────────────────────

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

# ──────────────────────────── PHARMACY ROUTES ────────────────────────────

@app.route('/patient/reteta')
@login_required(role='patient')
def patient_reteta():
    token = pharmacy_token(session['user_id'])
    pharmacy_url = request.host_url.rstrip('/') + url_for('pharmacy_view', token=token)
    db = get_db()
    meds = db.execute('''
        SELECT m.id, m.name, m.dosage, m.instructions, m.dispensed, m.dispensed_at,
               u.name as doctor_name
        FROM medications m
        LEFT JOIN users u ON m.prescribed_by = u.id
        WHERE m.patient_id=?
        ORDER BY m.dispensed ASC, m.id DESC
    ''', (session['user_id'],)).fetchall()
    db.close()
    return render_template('patient/reteta.html',
                           token=token,
                           pharmacy_url=pharmacy_url,
                           medications=meds)

@app.route('/farmacie/<token>')
def pharmacy_view(token):
    db = get_db()
    # Find patient by token
    patients = db.execute("SELECT id, name FROM users WHERE role='patient'").fetchall()
    patient = None
    for p in patients:
        if pharmacy_token(p['id']) == token:
            patient = p
            break
    if not patient:
        db.close()
        return render_template('pharmacy/not_found.html'), 404
    meds = db.execute('''
        SELECT m.id, m.name, m.dosage, m.instructions, m.dispensed, m.dispensed_at,
               u.name as doctor_name, u.email as doctor_email
        FROM medications m
        LEFT JOIN users u ON m.prescribed_by = u.id
        WHERE m.patient_id=?
        ORDER BY m.dispensed ASC, m.id DESC
    ''', (patient['id'],)).fetchall()
    db.close()
    return render_template('pharmacy/view.html',
                           patient=patient, medications=meds, token=token,
                           now=datetime.now().strftime('%d.%m.%Y %H:%M'))

@app.route('/farmacie/<token>/ridica/<int:med_id>', methods=['POST'])
def pharmacy_dispense(token, med_id):
    db = get_db()
    patients = db.execute("SELECT id FROM users WHERE role='patient'").fetchall()
    patient_id = None
    for p in patients:
        if pharmacy_token(p['id']) == token:
            patient_id = p['id']
            break
    if not patient_id:
        db.close()
        return redirect(url_for('pharmacy_view', token=token))
    db.execute("UPDATE medications SET dispensed=1, dispensed_at=? WHERE id=? AND patient_id=?",
               (datetime.now().strftime('%d.%m.%Y %H:%M'), med_id, patient_id))
    db.commit()
    db.close()
    return redirect(url_for('pharmacy_view', token=token))

@app.route('/farmacie/<token>/anuleaza/<int:med_id>', methods=['POST'])
def pharmacy_undispense(token, med_id):
    db = get_db()
    patients = db.execute("SELECT id FROM users WHERE role='patient'").fetchall()
    patient_id = None
    for p in patients:
        if pharmacy_token(p['id']) == token:
            patient_id = p['id']
            break
    if not patient_id:
        db.close()
        return redirect(url_for('pharmacy_view', token=token))
    db.execute("UPDATE medications SET dispensed=0, dispensed_at=NULL WHERE id=? AND patient_id=?",
               (med_id, patient_id))
    db.commit()
    db.close()
    return redirect(url_for('pharmacy_view', token=token))
