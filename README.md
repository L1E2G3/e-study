# E-Study

Versi ini menambahkan sistem materi dan tugas yang lebih lengkap.

Fitur utama:
- Materi: mata pelajaran, kelas, judul, deskripsi, lampiran PDF/Word/PowerPoint, YouTube, penulis, waktu publikasi.
- Materi dan tugas bisa diedit/dihapus oleh guru pembuatnya sendiri.
- Setiap guru memiliki tugas dan materi sendiri untuk urusan edit, hapus, dan koreksi.
- Guru tidak bisa mengoreksi pengumpulan tugas milik guru lain.
- Dashboard guru berisi jumlah materi, tugas, pengumpulan yang belum dinilai, dan deadline dekat.
- Dashboard siswa berisi ringkasan tugas dan nilai.
- Deadline tugas memakai tanggal dan jam serta ditolak oleh server setelah lewat.
- Ukuran maksimum setiap upload adalah 10 MB.
- Format upload: PDF, DOC, DOCX, PPT, PPTX, JPG, JPEG, PNG.
- Guru dapat memberi nilai dan komentar koreksi.
- Siswa melihat nilai dan komentar pada halaman Rekap Nilai.
- Materi dan tugas memiliki pencarian/filter sederhana.
- Pengumpulan siswa hanya dapat diunduh oleh siswa pemilik atau guru pembuat tugas.
- Database lama dimigrasikan otomatis oleh `app.py` tanpa menghapus data.

## Menjalankan

```bash
python app.py
```

Lalu buka `http://127.0.0.1:5000`.

**Jangan menjalankan `init_db.py` pada database yang sudah berisi data.** Script tersebut hanya untuk membuat database baru dari nol.

## Admin

Versi ini memiliki role `admin` dengan akses penuh ke pengguna, materi, tugas, pengumpulan, dan penilaian.

Pada database lama, saat aplikasi pertama kali dibuka, sistem otomatis membuat akun admin jika belum ada:
- Username: `admin`
- Password awal: `Admin12345!`

Segera ubah password dari menu Pengaturan Akun setelah login.

Guru tetap hanya dapat mengedit/menghapus materi dan tugas yang dibuat oleh dirinya sendiri, serta hanya dapat mengoreksi tugas dari tugas miliknya. Admin dapat mengelola semua guru, siswa, materi, tugas, dan nilai.
