import os
import secrets
import uuid
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from flask import Flask, render_template, request, redirect, url_for, session, abort, send_from_directory
import sqlite3
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
MAX_FILE_SIZE = 10 * 1024 * 1024
app.config.update(
    UPLOAD_FOLDER=BASE_DIR / 'uploads',
    MAX_CONTENT_LENGTH=MAX_FILE_SIZE,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'jpg', 'jpeg', 'png'}
app.config['UPLOAD_FOLDER'].mkdir(parents=True, exist_ok=True)


def csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']

app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def protect_forms():
    if request.method == 'POST':
        token = request.form.get('_csrf_token', '')
        if not token or not secrets.compare_digest(token, session.get('_csrf_token', '')):
            abort(400, 'Form tidak valid. Muat ulang halaman lalu coba lagi.')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file, prefix):
    if not file or not file.filename:
        return ''
    if not allowed_file(file.filename):
        abort(400, 'Format file tidak diizinkan. Gunakan PDF, Word, PowerPoint, JPG, JPEG, atau PNG.')
    safe_name = secure_filename(file.filename)
    if not safe_name:
        abort(400, 'Nama file tidak valid.')
    stored_name = f'{prefix}_{uuid.uuid4().hex}_{safe_name}'
    file.save(app.config['UPLOAD_FOLDER'] / stored_name)
    return stored_name


def remove_file(filename):
    if filename:
        path = app.config['UPLOAD_FOLDER'] / filename
        if path.exists() and path.is_file():
            path.unlink()


def is_teacher():
    return session.get('role') == 'guru'

def is_admin():
    return session.get('role') == 'admin'

def can_manage_content():
    return session.get('role') in {'guru', 'admin'}


def require_login():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return None


def deadline_passed(value):
    if not value:
        return False
    try:
        return datetime.fromisoformat(str(value).replace('T', ' ')) < datetime.now()
    except ValueError:
        return False

app.jinja_env.globals['deadline_passed'] = deadline_passed


def youtube_embed_url(url):
    if not url:
        return ''
    try:
        parsed = urlparse(url.strip())
        host = parsed.netloc.lower().split(':')[0]
        video_id = ''
        if host in {'youtube.com', 'www.youtube.com', 'm.youtube.com'}:
            if parsed.path == '/watch':
                video_id = parse_qs(parsed.query).get('v', [''])[0]
            elif parsed.path.startswith('/embed/'):
                video_id = parsed.path.split('/embed/', 1)[1].split('/')[0]
            elif parsed.path.startswith('/shorts/'):
                video_id = parsed.path.split('/shorts/', 1)[1].split('/')[0]
        elif host == 'youtu.be':
            video_id = parsed.path.strip('/').split('/')[0]
        if video_id and len(video_id) <= 20 and all(c.isalnum() or c in '_-' for c in video_id):
            return f'https://www.youtube.com/embed/{video_id}'
    except Exception:
        pass
    return ''


def get_db_connection():
    conn = sqlite3.connect(BASE_DIR / 'database.db')
    conn.row_factory = sqlite3.Row
    users_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if users_sql and "'admin'" not in (users_sql['sql'] or ''):
        conn.execute('ALTER TABLE users RENAME TO users_legacy')
        conn.execute('''CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'siswa' CHECK (role IN ('admin', 'guru', 'siswa')),
            nama_lengkap TEXT DEFAULT 'Pelajar Tanpa Nama'
        )''')
        conn.execute('''INSERT INTO users (id, username, password, role, nama_lengkap)
                        SELECT id, username, password, role, nama_lengkap FROM users_legacy''')
        conn.execute('DROP TABLE users_legacy')
    else:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'siswa' CHECK (role IN ('admin', 'guru', 'siswa')),
            nama_lengkap TEXT DEFAULT 'Pelajar Tanpa Nama'
        )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS materi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        judul TEXT,
        isi TEXT,
        mata_pelajaran TEXT,
        kelas TEXT,
        file_materi TEXT,
        video_url TEXT,
        penulis TEXT,
        tanggal TEXT,
        dibuat_oleh INTEGER
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS tugas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        judul TEXT,
        deskripsi TEXT,
        file_tugas TEXT,
        deadline TEXT,
        dibuat_oleh INTEGER
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pengumpulan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tugas_id INTEGER,
        user_id INTEGER,
        file_siswa TEXT,
        nilai INTEGER,
        komentar TEXT,
        dinilai_oleh INTEGER,
        dinilai_pada TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pengumuman (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        isi TEXT,
        tanggal TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Migrate existing databases without deleting user/material/task data.
    user_columns = {row['name'] for row in conn.execute('PRAGMA table_info(users)')}
    if 'nama_lengkap' not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN nama_lengkap TEXT DEFAULT 'Pelajar Tanpa Nama'")
    for user in conn.execute('SELECT id, password FROM users').fetchall():
        password = user['password'] or ''
        if not password.startswith(('scrypt:', 'pbkdf2:')):
            conn.execute('UPDATE users SET password = ? WHERE id = ?', (generate_password_hash(password), user['id']))

    if not conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone():
        conn.execute("INSERT INTO users (username, password, role, nama_lengkap) VALUES (?, ?, 'admin', ?)",
                     ( 'admin', generate_password_hash('Admin12345!'), 'Administrator'))

    material_columns = {row['name'] for row in conn.execute('PRAGMA table_info(materi)')}
    for column, definition in {
        'mata_pelajaran': "TEXT DEFAULT ''",
        'kelas': "TEXT DEFAULT ''",
        'file_materi': "TEXT",
        'video_url': "TEXT",
        'penulis': "TEXT DEFAULT 'Guru'",
        'tanggal': "TEXT",
        'dibuat_oleh': "INTEGER",
    }.items():
        if column not in material_columns:
            conn.execute(f'ALTER TABLE materi ADD COLUMN {column} {definition}')

    task_columns = {row['name'] for row in conn.execute('PRAGMA table_info(tugas)')}
    if 'dibuat_oleh' not in task_columns:
        conn.execute('ALTER TABLE tugas ADD COLUMN dibuat_oleh INTEGER')

    submission_columns = {row['name'] for row in conn.execute('PRAGMA table_info(pengumpulan)')}
    for column, definition in {
        'komentar': "TEXT",
        'dinilai_oleh': "INTEGER",
        'dinilai_pada': "TEXT",
    }.items():
        if column not in submission_columns:
            conn.execute(f'ALTER TABLE pengumpulan ADD COLUMN {column} {definition}')

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("UPDATE materi SET tanggal = ? WHERE tanggal IS NULL OR tanggal = ''", (now,))
    # Legacy rows are assigned to the matching teacher name where possible;
    # otherwise the first teacher account owns them.
    first_teacher = conn.execute("SELECT id FROM users WHERE role='guru' ORDER BY id LIMIT 1").fetchone()
    if first_teacher:
        conn.execute("UPDATE materi SET dibuat_oleh = ? WHERE dibuat_oleh IS NULL", (first_teacher['id'],))
        conn.execute("UPDATE tugas SET dibuat_oleh = ? WHERE dibuat_oleh IS NULL", (first_teacher['id'],))
    conn.commit()
    return conn


@app.route('/uploads/<filename>')
def download_upload(filename):
    if 'user_id' not in session or filename != secure_filename(filename):
        abort(404)
    conn = get_db_connection()
    material = conn.execute('SELECT id FROM materi WHERE file_materi = ?', (filename,)).fetchone()
    task_file = conn.execute('SELECT dibuat_oleh FROM tugas WHERE file_tugas = ?', (filename,)).fetchone()
    submission = conn.execute('''
        SELECT p.user_id, t.dibuat_oleh
        FROM pengumpulan p JOIN tugas t ON p.tugas_id = t.id
        WHERE p.file_siswa = ?
    ''', (filename,)).fetchone()
    conn.close()
    if material or task_file:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    if submission:
        allowed = is_admin() or submission['user_id'] == session['user_id'] or (is_teacher() and submission['dibuat_oleh'] == session['user_id'])
        if allowed:
            return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    abort(404)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identitas = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (identitas,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['nama_lengkap']
            session['role'] = user['role']
            return redirect(url_for('index'))
        return '''<!DOCTYPE html><html><head><title>Login Gagal</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"></head><body class="bg-light d-flex justify-content-center align-items-center vh-100"><div class="text-center p-5 bg-white shadow rounded border-top border-danger border-5"><h1 class="text-danger mb-3">Login Gagal</h1><p class="fs-5 text-muted">Username atau password salah.</p><a href="/login" class="btn btn-danger mt-3">Kembali ke Login</a></div></body></html>'''
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        identitas = request.form['username'].strip()
        nama_lengkap = request.form['nama_lengkap'].strip()
        password = request.form['password']
        conn = get_db_connection()
        if conn.execute('SELECT id FROM users WHERE username = ?', (identitas,)).fetchone():
            conn.close()
            return '''<!DOCTYPE html><html><head><title>Pendaftaran Gagal</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"></head><body class="bg-light d-flex justify-content-center align-items-center vh-100"><div class="text-center p-5 bg-white shadow rounded border-top border-warning border-5"><h1 class="text-warning mb-3">Username sudah terdaftar</h1><a href="/register" class="btn btn-warning mt-3">Kembali</a></div></body></html>'''
        conn.execute('INSERT INTO users (username, password, role, nama_lengkap) VALUES (?, ?, ?, ?)', (identitas, generate_password_hash(password), 'siswa', nama_lengkap))
        conn.commit(); conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    pengumuman = conn.execute('SELECT * FROM pengumuman ORDER BY id DESC LIMIT 10').fetchall()
    stats = {}
    if is_admin():
        stats['materi'] = conn.execute('SELECT COUNT(*) c FROM materi').fetchone()['c']
        stats['tugas'] = conn.execute('SELECT COUNT(*) c FROM tugas').fetchone()['c']
        stats['belum_dinilai'] = conn.execute('SELECT COUNT(*) c FROM pengumpulan WHERE nilai IS NULL').fetchone()['c']
        stats['pengguna'] = conn.execute('SELECT COUNT(*) c FROM users').fetchone()['c']
        recent = conn.execute('''SELECT t.judul, t.deadline, COUNT(p.id) jumlah FROM tugas t LEFT JOIN pengumpulan p ON p.tugas_id=t.id GROUP BY t.id ORDER BY t.id DESC LIMIT 5''').fetchall()
    elif is_teacher():
        stats['materi'] = conn.execute('SELECT COUNT(*) c FROM materi WHERE dibuat_oleh=?', (session['user_id'],)).fetchone()['c']
        stats['tugas'] = conn.execute('SELECT COUNT(*) c FROM tugas WHERE dibuat_oleh=?', (session['user_id'],)).fetchone()['c']
        stats['belum_dinilai'] = conn.execute('''SELECT COUNT(*) c FROM pengumpulan p JOIN tugas t ON p.tugas_id=t.id WHERE t.dibuat_oleh=? AND p.nilai IS NULL''', (session['user_id'],)).fetchone()['c']
        stats['deadline_dekat'] = conn.execute('''SELECT COUNT(*) c FROM tugas WHERE dibuat_oleh=? AND deadline >= ? AND deadline <= ?''', (session['user_id'], datetime.now().strftime('%Y-%m-%d %H:%M'), (datetime.now().replace(microsecond=0) + __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d %H:%M'))).fetchone()['c']
        recent = conn.execute('''SELECT t.judul, t.deadline, COUNT(p.id) jumlah FROM tugas t LEFT JOIN pengumpulan p ON p.tugas_id=t.id WHERE t.dibuat_oleh=? GROUP BY t.id ORDER BY t.id DESC LIMIT 5''', (session['user_id'],)).fetchall()
    else:
        stats['tugas_belum'] = conn.execute('''SELECT COUNT(*) c FROM tugas t WHERE NOT EXISTS (SELECT 1 FROM pengumpulan p WHERE p.tugas_id=t.id AND p.user_id=?) AND (t.deadline IS NULL OR t.deadline >= ?)''', (session['user_id'], datetime.now().strftime('%Y-%m-%d %H:%M'))).fetchone()['c']
        stats['nilai_baru'] = conn.execute('''SELECT COUNT(*) c FROM pengumpulan WHERE user_id=? AND nilai IS NOT NULL''', (session['user_id'],)).fetchone()['c']
        recent = conn.execute('SELECT judul, deadline FROM tugas ORDER BY id DESC LIMIT 5').fetchall()
    conn.close()
    return render_template('index.html', username=session['username'], role=session['role'], pengumuman=pengumuman, stats=stats, recent=recent)


@app.route('/tambah-pengumuman', methods=['POST'])
def tambah_pengumuman():
    if not can_manage_content(): return 'Akses Ditolak!', 403
    isi = request.form.get('isi', '').strip()
    if not isi: abort(400, 'Pengumuman tidak boleh kosong.')
    conn = get_db_connection(); conn.execute('INSERT INTO pengumuman (isi) VALUES (?)', (isi,)); conn.commit(); conn.close()
    return redirect(url_for('index'))


@app.route('/admin/pengumuman/<int:pengumuman_id>/edit', methods=['GET', 'POST'])
def admin_edit_pengumuman(pengumuman_id):
    if not is_admin(): return 'Akses Ditolak!', 403
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM pengumuman WHERE id=?', (pengumuman_id,)).fetchone()
    if not row:
        conn.close(); abort(404)
    if request.method == 'POST':
        isi = request.form.get('isi', '').strip()
        if not isi:
            conn.close(); abort(400, 'Pengumuman tidak boleh kosong.')
        conn.execute('UPDATE pengumuman SET isi=? WHERE id=?', (isi, pengumuman_id))
        conn.commit(); conn.close()
        return redirect(url_for('admin_dashboard'))
    conn.close()
    return render_template('edit_pengumuman.html', username=session['username'], role=session['role'], pengumuman=row)


@app.route('/admin/pengumuman/<int:pengumuman_id>/delete', methods=['POST'])
def admin_delete_pengumuman(pengumuman_id):
    if not is_admin(): return 'Akses Ditolak!', 403
    conn = get_db_connection()
    row = conn.execute('SELECT id FROM pengumuman WHERE id=?', (pengumuman_id,)).fetchone()
    if not row:
        conn.close(); abort(404)
    conn.execute('DELETE FROM pengumuman WHERE id=?', (pengumuman_id,))
    conn.commit(); conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/materi')
def materi():
    if 'user_id' not in session: return redirect(url_for('login'))
    search = request.args.get('q', '').strip()
    subject = request.args.get('mapel', '').strip()
    conn = get_db_connection()
    query = 'SELECT m.*, u.nama_lengkap AS pembuat_nama FROM materi m LEFT JOIN users u ON m.dibuat_oleh=u.id WHERE 1=1'
    params = []
    if search:
        query += ' AND (m.judul LIKE ? OR m.isi LIKE ? OR m.mata_pelajaran LIKE ?)'; params += [f'%{search}%'] * 3
    if subject:
        query += ' AND m.mata_pelajaran = ?'; params.append(subject)
    query += ' ORDER BY m.id DESC'
    daftar_materi = conn.execute(query, params).fetchall()
    mapel_list = conn.execute('SELECT DISTINCT mata_pelajaran FROM materi WHERE mata_pelajaran IS NOT NULL AND mata_pelajaran != "" ORDER BY mata_pelajaran').fetchall()
    conn.close()
    return render_template('materi.html', username=session['username'], role=session['role'], daftar_materi=daftar_materi, mapel_list=mapel_list, search=search, subject=subject)


def teacher_owns_material(conn, material_id):
    return conn.execute('SELECT * FROM materi WHERE id=?' + ('' if is_admin() else ' AND dibuat_oleh=?'), (material_id,) if is_admin() else (material_id, session['user_id'])).fetchone()


@app.route('/hapus-materi/<int:materi_id>', methods=['POST'])
def hapus_materi(materi_id):
    if not can_manage_content(): return 'Akses Ditolak!', 403
    conn = get_db_connection(); row = teacher_owns_material(conn, materi_id)
    if not row: conn.close(); abort(403, 'Kamu hanya bisa menghapus materi yang kamu buat sendiri.')
    conn.execute('DELETE FROM materi WHERE id=?', (materi_id,)); conn.commit(); conn.close(); remove_file(row['file_materi'])
    return redirect(url_for('materi'))


@app.route('/edit-materi/<int:materi_id>', methods=['GET', 'POST'])
def edit_materi(materi_id):
    if not can_manage_content(): return 'Akses Ditolak!', 403
    conn = get_db_connection(); row = teacher_owns_material(conn, materi_id)
    if not row: conn.close(); abort(403, 'Kamu hanya bisa mengedit materi yang kamu buat sendiri.')
    if request.method == 'POST':
        mata_pelajaran = request.form.get('mata_pelajaran','').strip(); kelas=request.form.get('kelas','').strip(); judul=request.form.get('judul','').strip(); isi=request.form.get('isi','').strip(); video_url=request.form.get('video_url','').strip()
        if not all([mata_pelajaran, kelas, judul, isi]): conn.close(); abort(400, 'Mata pelajaran, kelas, judul, dan deskripsi wajib diisi.')
        video_embed = youtube_embed_url(video_url)
        if video_url and not video_embed: conn.close(); abort(400, 'Link video harus berupa link YouTube yang valid.')
        new_file = save_upload(request.files.get('file_materi'), 'materi')
        filename = row['file_materi']
        if new_file: filename = new_file
        conn.execute('UPDATE materi SET mata_pelajaran=?, kelas=?, judul=?, isi=?, file_materi=?, video_url=? WHERE id=?', (mata_pelajaran,kelas,judul,isi,filename,video_embed,materi_id)); conn.commit(); conn.close()
        if new_file and row['file_materi']: remove_file(row['file_materi'])
        return redirect(url_for('materi'))
    conn.close(); return render_template('edit_materi.html', username=session['username'], role=session['role'], materi=row)


@app.route('/tugas')
def tugas():
    if 'user_id' not in session: return redirect(url_for('login'))
    search = request.args.get('q','').strip()
    conn = get_db_connection()
    query='''SELECT t.*, u.nama_lengkap AS pembuat_nama FROM tugas t LEFT JOIN users u ON t.dibuat_oleh=u.id WHERE 1=1'''; params=[]
    if search: query += ' AND (t.judul LIKE ? OR t.deskripsi LIKE ?)'; params += [f'%{search}%', f'%{search}%']
    query += ' ORDER BY t.id DESC'
    daftar_tugas=conn.execute(query,params).fetchall()
    tugas_terkumpul=[]
    if session['role']=='siswa':
        tugas_terkumpul=[r['tugas_id'] for r in conn.execute('SELECT tugas_id FROM pengumpulan WHERE user_id=?',(session['user_id'],)).fetchall()]
    conn.close()
    return render_template('tugas.html', username=session['username'], role=session['role'], daftar_tugas=daftar_tugas, tugas_terkumpul=tugas_terkumpul, search=search)


def teacher_owns_task(conn, task_id):
    return conn.execute('SELECT * FROM tugas WHERE id=?' + ('' if is_admin() else ' AND dibuat_oleh=?'), (task_id,) if is_admin() else (task_id, session['user_id'])).fetchone()


@app.route('/hapus-tugas/<int:tugas_id>', methods=['POST'])
def hapus_tugas(tugas_id):
    if not can_manage_content(): return 'Akses Ditolak!', 403
    conn=get_db_connection(); row=teacher_owns_task(conn,tugas_id)
    if not row: conn.close(); abort(403,'Kamu hanya bisa menghapus tugas yang kamu buat sendiri.')
    submissions=conn.execute('SELECT file_siswa FROM pengumpulan WHERE tugas_id=?',(tugas_id,)).fetchall()
    conn.execute('DELETE FROM pengumpulan WHERE tugas_id=?',(tugas_id,)); conn.execute('DELETE FROM tugas WHERE id=?',(tugas_id,)); conn.commit(); conn.close()
    remove_file(row['file_tugas'])
    for s in submissions: remove_file(s['file_siswa'])
    return redirect(url_for('tugas'))


@app.route('/edit-tugas/<int:tugas_id>', methods=['GET','POST'])
def edit_tugas(tugas_id):
    if not can_manage_content(): return 'Akses Ditolak!',403
    conn=get_db_connection(); row=teacher_owns_task(conn,tugas_id)
    if not row: conn.close(); abort(403,'Kamu hanya bisa mengedit tugas yang kamu buat sendiri.')
    if request.method=='POST':
        judul=request.form.get('judul','').strip(); deskripsi=request.form.get('deskripsi','').strip(); deadline=request.form.get('deadline','').strip()
        if not judul or not deskripsi or not deadline: conn.close(); abort(400,'Judul, deskripsi, dan deadline wajib diisi.')
        try: deadline_dt=datetime.fromisoformat(deadline)
        except ValueError: conn.close(); abort(400,'Format deadline tidak valid.')
        if deadline_dt <= datetime.now(): conn.close(); abort(400,'Deadline harus berada di masa depan.')
        new_file=save_upload(request.files.get('file_tugas'),'tugas'); filename=row['file_tugas']
        if new_file: filename=new_file
        conn.execute('UPDATE tugas SET judul=?, deskripsi=?, deadline=?, file_tugas=? WHERE id=?',(judul,deskripsi,deadline_dt.strftime('%Y-%m-%d %H:%M'),filename,tugas_id)); conn.commit(); conn.close()
        if new_file and row['file_tugas']: remove_file(row['file_tugas'])
        return redirect(url_for('tugas'))
    conn.close(); return render_template('edit_tugas.html',username=session['username'],role=session['role'],tugas=row)


@app.route('/tambah-materi', methods=['GET','POST'])
def tambah_materi():
    if not can_manage_content(): return 'Akses Ditolak!',403
    if request.method=='POST':
        mata_pelajaran=request.form.get('mata_pelajaran','').strip(); kelas=request.form.get('kelas','').strip(); judul=request.form.get('judul','').strip(); isi=request.form.get('isi','').strip(); video_url=request.form.get('video_url','').strip()
        if not all([mata_pelajaran,kelas,judul,isi]): abort(400,'Mata pelajaran, kelas, judul, dan deskripsi wajib diisi.')
        video_embed=youtube_embed_url(video_url)
        if video_url and not video_embed: abort(400,'Link video harus berupa link YouTube yang valid.')
        filename=save_upload(request.files.get('file_materi'),'materi')
        conn=get_db_connection(); conn.execute('INSERT INTO materi (judul,isi,mata_pelajaran,kelas,file_materi,video_url,penulis,tanggal,dibuat_oleh) VALUES (?,?,?,?,?,?,?,?,?)',(judul,isi,mata_pelajaran,kelas,filename,video_embed,session['username'],datetime.now().strftime('%Y-%m-%d %H:%M:%S'),session['user_id'])); conn.commit(); conn.close()
        return redirect(url_for('materi'))
    return render_template('tambah_materi.html',username=session['username'],role=session['role'])


@app.route('/tambah-tugas', methods=['GET','POST'])
def tambah_tugas():
    if not can_manage_content(): return 'Akses Ditolak!',403
    if request.method=='POST':
        judul=request.form.get('judul','').strip(); deskripsi=request.form.get('deskripsi','').strip(); deadline=request.form.get('deadline','').strip()
        if not judul or not deskripsi or not deadline: abort(400,'Judul, deskripsi, dan deadline wajib diisi.')
        try: deadline_dt=datetime.fromisoformat(deadline)
        except ValueError: abort(400,'Format tanggal dan waktu deadline tidak valid.')
        if deadline_dt<=datetime.now(): abort(400,'Deadline harus berada di masa depan.')
        filename=save_upload(request.files.get('file_tugas'),'tugas')
        conn=get_db_connection(); conn.execute('INSERT INTO tugas (judul,deskripsi,file_tugas,deadline,dibuat_oleh) VALUES (?,?,?,?,?)',(judul,deskripsi,filename,deadline_dt.strftime('%Y-%m-%d %H:%M'),session['user_id'])); conn.commit(); conn.close()
        return redirect(url_for('tugas'))
    return render_template('tambah_tugas.html',username=session['username'],role=session['role'])


@app.route('/kumpul-tugas/<int:tugas_id>', methods=['GET','POST'])
def kumpul_tugas(tugas_id):
    if session.get('role')!='siswa': return 'Akses Ditolak!',403
    conn=get_db_connection(); task=conn.execute('SELECT * FROM tugas WHERE id=?',(tugas_id,)).fetchone()
    if not task: conn.close(); abort(404)
    if request.method=='POST':
        if deadline_passed(task['deadline']): conn.close(); abort(400,'Batas pengumpulan tugas sudah berakhir.')
        existing=conn.execute('SELECT id FROM pengumpulan WHERE tugas_id=? AND user_id=?',(tugas_id,session['user_id'])).fetchone()
        if existing: conn.close(); abort(400,'Kamu sudah mengumpulkan tugas ini.')
        filename=save_upload(request.files.get('file_siswa'),f'siswa_{session["user_id"]}')
        if not filename: conn.close(); abort(400,'File tugas wajib diunggah.')
        conn.execute('INSERT INTO pengumpulan (tugas_id,user_id,file_siswa) VALUES (?,?,?)',(tugas_id,session['user_id'],filename)); conn.commit(); conn.close(); return redirect(url_for('tugas'))
    conn.close(); return render_template('kumpul_tugas.html',username=session['username'],role=session['role'],tugas=task)


@app.route('/koreksi-tugas')
def koreksi_tugas():
    if not can_manage_content(): return 'Akses Ditolak!',403
    conn=get_db_connection(); kumpulan=conn.execute('''SELECT p.id pengumpulan_id,u.nama_lengkap username,t.judul,p.file_siswa,p.nilai,p.komentar,p.dinilai_pada,t.dibuat_oleh,t.deadline FROM pengumpulan p JOIN users u ON p.user_id=u.id JOIN tugas t ON p.tugas_id=t.id WHERE (? = 1 OR t.dibuat_oleh=?) ORDER BY p.id DESC''',(1 if is_admin() else 0, session['user_id'])).fetchall(); conn.close()
    return render_template('koreksi_tugas.html',username=session['username'],role=session['role'],kumpulan=kumpulan)


@app.route('/beri-nilai/<int:pengumpulan_id>', methods=['POST'])
def beri_nilai(pengumpulan_id):
    if not can_manage_content(): return 'Akses Ditolak!',403
    try: nilai=int(request.form['nilai'])
    except (KeyError,ValueError): abort(400,'Nilai harus berupa angka.')
    if not 0<=nilai<=100: abort(400,'Nilai harus berada antara 0 dan 100.')
    komentar=request.form.get('komentar','').strip()
    conn=get_db_connection(); row=conn.execute('''SELECT p.id FROM pengumpulan p JOIN tugas t ON p.tugas_id=t.id WHERE p.id=? AND (? = 1 OR t.dibuat_oleh=?)''',(pengumpulan_id,1 if is_admin() else 0,session['user_id'])).fetchone()
    if not row: conn.close(); abort(403,'Kamu hanya bisa mengoreksi tugas yang kamu buat sendiri.')
    conn.execute('UPDATE pengumpulan SET nilai=?, komentar=?, dinilai_oleh=?, dinilai_pada=? WHERE id=?',(nilai,komentar,session['user_id'],datetime.now().strftime('%Y-%m-%d %H:%M:%S'),pengumpulan_id)); conn.commit(); conn.close(); return redirect(url_for('koreksi_tugas'))


@app.route('/nilai')
def nilai():
    if session.get('role')!='siswa': return 'Halaman nilai hanya untuk siswa.',403
    conn=get_db_connection(); daftar_nilai=conn.execute('''SELECT t.judul,p.nilai,p.komentar,p.dinilai_pada,u.nama_lengkap guru FROM pengumpulan p JOIN tugas t ON p.tugas_id=t.id LEFT JOIN users u ON p.dinilai_oleh=u.id WHERE p.user_id=? ORDER BY p.id DESC''',(session['user_id'],)).fetchall(); conn.close()
    return render_template('nilai.html',username=session['username'],role=session['role'],daftar_nilai=daftar_nilai)


@app.route('/profil')
def profil():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('profil.html',username=session['username'],role=session['role'])


@app.route('/lupa-sandi', methods=['GET','POST'])
def lupa_sandi(): return render_template('lupa_sandi.html')


@app.route('/settings', methods=['GET','POST'])
def settings():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn=get_db_connection(); user=conn.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone()
    if request.method=='POST':
        nama_baru=request.form.get('nama_lengkap','').strip(); password_baru=request.form.get('password','')
        if not nama_baru: conn.close(); abort(400,'Nama tidak boleh kosong.')
        if password_baru: conn.execute('UPDATE users SET nama_lengkap=?,password=? WHERE id=?',(nama_baru,generate_password_hash(password_baru),session['user_id']))
        else: conn.execute('UPDATE users SET nama_lengkap=? WHERE id=?',(nama_baru,session['user_id']))
        conn.commit(); conn.close(); session['username']=nama_baru; return redirect(url_for('index'))
    conn.close(); return render_template('settings.html',username=session['username'],role=session['role'],user=user)


@app.route('/admin')
def admin_dashboard():
    if not is_admin(): return 'Akses Ditolak!', 403
    conn = get_db_connection()
    users = conn.execute('SELECT id, username, role, nama_lengkap FROM users ORDER BY role, username').fetchall()
    materials = conn.execute("SELECT m.id, m.judul, m.mata_pelajaran, u.nama_lengkap pembuat FROM materi m LEFT JOIN users u ON m.dibuat_oleh=u.id ORDER BY m.id DESC").fetchall()
    tasks = conn.execute("SELECT t.id, t.judul, t.deadline, u.nama_lengkap pembuat FROM tugas t LEFT JOIN users u ON t.dibuat_oleh=u.id ORDER BY t.id DESC").fetchall()
    submissions = conn.execute("SELECT p.id, p.nilai, p.komentar, s.nama_lengkap siswa, t.judul tugas, g.nama_lengkap guru FROM pengumpulan p JOIN users s ON p.user_id=s.id JOIN tugas t ON p.tugas_id=t.id LEFT JOIN users g ON t.dibuat_oleh=g.id ORDER BY p.id DESC").fetchall()
    announcements = conn.execute("SELECT * FROM pengumuman ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('admin.html', username=session['username'], role=session['role'], users=users, materials=materials, tasks=tasks, submissions=submissions, announcements=announcements)

@app.route('/admin/users', methods=['POST'])
def admin_create_user():
    if not is_admin(): return 'Akses Ditolak!', 403
    username=request.form.get('username','').strip(); nama=request.form.get('nama_lengkap','').strip(); password=request.form.get('password',''); role=request.form.get('role','siswa')
    if role not in {'admin','guru','siswa'} or not username or not nama or len(password)<8: abort(400,'Data pengguna tidak valid. Password minimal 8 karakter.')
    conn=get_db_connection()
    if conn.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone(): conn.close(); abort(400,'Username sudah digunakan.')
    conn.execute('INSERT INTO users (username,password,role,nama_lengkap) VALUES (?,?,?,?)',(username,generate_password_hash(password),role,nama)); conn.commit(); conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users/<int:user_id>/update', methods=['POST'])
def admin_update_user(user_id):
    if not is_admin(): return 'Akses Ditolak!', 403
    conn=get_db_connection(); user=conn.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
    if not user: conn.close(); abort(404)
    nama=request.form.get('nama_lengkap','').strip(); role=request.form.get('role','siswa'); password=request.form.get('password','')
    if role not in {'admin','guru','siswa'} or not nama: conn.close(); abort(400,'Data pengguna tidak valid.')
    if password:
        if len(password)<8: conn.close(); abort(400,'Password minimal 8 karakter.')
        conn.execute('UPDATE users SET nama_lengkap=?,role=?,password=? WHERE id=?',(nama,role,generate_password_hash(password),user_id))
    else: conn.execute('UPDATE users SET nama_lengkap=?,role=? WHERE id=?',(nama,role,user_id))
    conn.commit(); conn.close(); return redirect(url_for('admin_dashboard'))

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    if not is_admin(): return 'Akses Ditolak!', 403
    if user_id == session.get('user_id'): abort(400,'Admin yang sedang login tidak boleh menghapus dirinya sendiri.')
    conn=get_db_connection(); user=conn.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
    if not user: conn.close(); abort(404)
    files=[r['file_siswa'] for r in conn.execute('SELECT file_siswa FROM pengumpulan WHERE user_id=?',(user_id,)).fetchall()]
    owned_tasks=conn.execute('SELECT id,file_tugas FROM tugas WHERE dibuat_oleh=?',(user_id,)).fetchall()
    for t in owned_tasks: files += [r['file_siswa'] for r in conn.execute('SELECT file_siswa FROM pengumpulan WHERE tugas_id=?',(t['id'],)).fetchall()]
    files += [r['file_materi'] for r in conn.execute('SELECT file_materi FROM materi WHERE dibuat_oleh=?',(user_id,)).fetchall()]
    files += [r['file_tugas'] for r in owned_tasks]
    conn.execute('DELETE FROM pengumpulan WHERE user_id=? OR tugas_id IN (SELECT id FROM tugas WHERE dibuat_oleh=?)',(user_id,user_id))
    conn.execute('DELETE FROM tugas WHERE dibuat_oleh=?',(user_id,)); conn.execute('DELETE FROM materi WHERE dibuat_oleh=?',(user_id,)); conn.execute('DELETE FROM users WHERE id=?',(user_id,)); conn.commit(); conn.close()
    for f in files: remove_file(f)
    return redirect(url_for('admin_dashboard'))


@app.errorhandler(413)
def too_large(_):
    return 'File terlalu besar. Maksimal ukuran file adalah 10 MB.', 413


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')
