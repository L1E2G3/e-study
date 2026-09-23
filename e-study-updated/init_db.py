"""Create a fresh E-Study database.

WARNING: this script intentionally recreates the database. Do not use it to
upgrade an existing project database; app.py performs non-destructive migration.
"""
import argparse
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash

parser = argparse.ArgumentParser(description='Initialize a fresh E-Study database.')
parser.add_argument('--teacher-username', required=True)
parser.add_argument('--teacher-name', required=True)
parser.add_argument('--teacher-password', required=True)
args = parser.parse_args()
if len(args.teacher_password) < 12:
    parser.error('--teacher-password must have at least 12 characters.')

db_path = Path(__file__).resolve().parent / 'database.db'
conn = sqlite3.connect(db_path)
conn.executescript('''
DROP TABLE IF EXISTS pengumpulan;
DROP TABLE IF EXISTS tugas;
DROP TABLE IF EXISTS materi;
DROP TABLE IF EXISTS pengumuman;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'guru', 'siswa')),
    nama_lengkap TEXT NOT NULL
);
CREATE TABLE materi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    judul TEXT NOT NULL,
    isi TEXT NOT NULL,
    mata_pelajaran TEXT,
    kelas TEXT,
    file_materi TEXT,
    video_url TEXT,
    penulis TEXT,
    tanggal TEXT,
    dibuat_oleh INTEGER
);
CREATE TABLE tugas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    judul TEXT NOT NULL,
    deskripsi TEXT NOT NULL,
    file_tugas TEXT,
    deadline TEXT,
    dibuat_oleh INTEGER
);
CREATE TABLE pengumpulan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tugas_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    file_siswa TEXT NOT NULL,
    nilai INTEGER,
    komentar TEXT,
    dinilai_oleh INTEGER,
    dinilai_pada TEXT,
    FOREIGN KEY (tugas_id) REFERENCES tugas (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);
CREATE TABLE pengumuman (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isi TEXT NOT NULL,
    tanggal TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
''')
conn.execute('INSERT INTO users (username,password,role,nama_lengkap) VALUES (?,?,?,?)',
             (args.teacher_username, generate_password_hash(args.teacher_password), 'guru', args.teacher_name))
conn.commit()
conn.close()
print('Database baru berhasil dibuat. Buat akun siswa melalui halaman registrasi.')
