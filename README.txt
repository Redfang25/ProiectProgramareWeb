MedTrack – Aplicație web pentru monitorizarea tratamentului
============================================================

CERINȚE
-------
- Python 3.8+
- pip

INSTALARE ȘI PORNIRE
---------------------
1. Dezarhivează folderul medtrack/

2. (Opțional) Creează un virtual environment:
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # Mac/Linux

3. Instalează dependențele:
   pip install -r requirements.txt

4. Pornește aplicația:
   python app.py

5. Deschide browserul la:
   http://127.0.0.1:5000

UTILIZARE
----------
- Creează un cont de tip Pacient și unul de tip Medic
- Ca Pacient: adaugă medicamente cu program (zile + ore)
- Ca Pacient: confirmă dozele din pagina "Today"
- Ca Pacient: trimite invitație medicului (după email-ul lui)
- Ca Medic: acceptă invitația din dashboard
- Ca Medic: vizualizează istoricul pacientului conectat

STRUCTURĂ PROIECT
------------------
medtrack/
├── app.py              ← aplicația Flask principală (rute + DB)
├── requirements.txt    ← dependențe Python
├── medtrack.db         ← baza de date SQLite (generată automat la pornire)
├── static/
│   └── style.css       ← stiluri CSS custom
└── templates/
    ├── base.html        ← template de bază cu navbar
    ├── login.html
    ├── register.html
    ├── patient/
    │   ├── today.html       ← dozele zilei curente
    │   ├── medications.html ← CRUD medicamente + programe
    │   ├── history.html     ← istoricul dozelor + statistici
    │   └── doctors.html     ← gestionare acces medici
    └── doctor/
        ├── dashboard.html      ← invitații în așteptare
        ├── patients.html       ← lista pacienților acceptați
        └── patient_detail.html ← detalii pacient + istoric

BAZA DE DATE (SQLite – medtrack.db)
-------------------------------------
users          → id, name, email, password_hash, role
medications    → id, patient_id, name, dosage, instructions
schedules      → id, medication_id, patient_id, days_of_week, times, start_date, end_date
doses          → id, schedule_id, patient_id, medication_id, dose_date, dose_time, status, confirmed_at
doctor_patient → id, doctor_id, patient_id, status

NOTĂ: Parola este stocată hashed (werkzeug). Baza de date se creează
automat la prima pornire a aplicației.
