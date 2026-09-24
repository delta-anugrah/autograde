"""Baca & tulis media.env — satu-satunya yang tahu bentuk berkas itu."""

from __future__ import annotations

from palmgrade.services.media_env_service import (
    BAWAAN,
    LINE_CODES,
    MediaEnvService,
)


def test_line_codes_tiga():
    assert LINE_CODES == ("line-1", "line-2", "line-3")


def test_berkas_belum_ada_memberi_bawaan(tmp_path):
    svc = MediaEnvService(tmp_path / "media.env")
    hasil = svc.baca()
    assert hasil == {kode: dict(BAWAAN) for kode in LINE_CODES}


def test_bawaan_hikrobot(tmp_path):
    # PC pabrik yang belum punya media.env harus tetap memakai kamera sungguhan.
    svc = MediaEnvService(tmp_path / "media.env")
    assert svc.baca()["line-1"]["sumber"] == "hikrobot"


def test_tulis_lalu_baca_bolak_balik(tmp_path):
    svc = MediaEnvService(tmp_path / "media.env")
    setelan = {
        "line-1": {"sumber": "hikrobot", "berkas": "", "ulang": False},
        "line-2": {"sumber": "video", "berkas": "konveyor.mp4", "ulang": True},
        "line-3": {"sumber": "foto", "berkas": "sawit.jpg", "ulang": False},
    }
    svc.tulis(setelan)
    assert svc.baca() == setelan


def test_isi_berkas_bentuk_env(tmp_path):
    path = tmp_path / "media.env"
    MediaEnvService(path).tulis(
        {
            "line-1": {"sumber": "video", "berkas": "a.mp4", "ulang": True},
            "line-2": {"sumber": "hikrobot", "berkas": "", "ulang": False},
            "line-3": {"sumber": "hikrobot", "berkas": "", "ulang": False},
        }
    )
    isi = path.read_text(encoding="utf-8")
    assert "LINE_1_CAMERA_TYPE=opencv" in isi
    assert "LINE_1_MEDIA_FILE=a.mp4" in isi
    assert "LINE_1_VIDEO_LOOP=true" in isi
    assert "LINE_2_CAMERA_TYPE=hikrobot" in isi
    assert "LINE_2_MEDIA_FILE=" in isi


def test_baris_tak_dikenal_diabaikan(tmp_path):
    # Berkas yang ditulis versi lebih baru tidak boleh mematikan versi lama.
    path = tmp_path / "media.env"
    path.write_text(
        "LINE_1_CAMERA_TYPE=photo\nLINE_1_MEDIA_FILE=sawit.jpg\nLINE_9_WARNA=merah\nBUKAN_BARIS_ENV\n# komentar\n\n",
        encoding="utf-8",
    )
    hasil = MediaEnvService(path).baca()
    assert hasil["line-1"] == {"sumber": "foto", "berkas": "sawit.jpg", "ulang": False}
    assert hasil["line-2"] == dict(BAWAAN)


def test_camera_type_asing_jatuh_ke_bawaan(tmp_path):
    # Berkas disunting tangan dengan nilai ngawur: line tetap boot memakai
    # kamera sungguhan, bukan gagal.
    path = tmp_path / "media.env"
    path.write_text("LINE_1_CAMERA_TYPE=gopro\n", encoding="utf-8")
    assert MediaEnvService(path).baca()["line-1"] == dict(BAWAAN)


def test_opencv_tanpa_berkas_terbaca_webcam(tmp_path):
    path = tmp_path / "media.env"
    path.write_text("LINE_1_CAMERA_TYPE=opencv\nLINE_1_MEDIA_FILE=\n", encoding="utf-8")
    assert MediaEnvService(path).baca()["line-1"]["sumber"] == "webcam"


def test_opencv_dengan_berkas_terbaca_video(tmp_path):
    path = tmp_path / "media.env"
    path.write_text("LINE_1_CAMERA_TYPE=opencv\nLINE_1_MEDIA_FILE=a.mp4\n", encoding="utf-8")
    assert MediaEnvService(path).baca()["line-1"]["sumber"] == "video"


def test_tulis_tidak_meninggalkan_berkas_separo(tmp_path, monkeypatch):
    # Menulis lewat berkas sementara + os.replace: berkas setengah tertulis
    # membuat ketiga line gagal boot.
    import os

    path = tmp_path / "media.env"
    MediaEnvService(path).tulis({kode: dict(BAWAAN) for kode in LINE_CODES})
    asli = path.read_text(encoding="utf-8")

    def replace_gagal(src, dst):
        raise OSError("disk penuh")

    monkeypatch.setattr(os, "replace", replace_gagal)
    try:
        MediaEnvService(path).tulis(
            {
                "line-1": {"sumber": "video", "berkas": "b.mp4", "ulang": False},
                "line-2": dict(BAWAAN),
                "line-3": dict(BAWAAN),
            }
        )
    except OSError:
        pass
    assert path.read_text(encoding="utf-8") == asli


def test_tulis_membuat_folder_induk(tmp_path):
    path = tmp_path / "config" / "media.env"
    MediaEnvService(path).tulis({kode: dict(BAWAAN) for kode in LINE_CODES})
    assert path.exists()


def test_berkas_utf8_cacat_jatuh_ke_bawaan(tmp_path):
    # Berkas yang terkorupsi dengan invalid UTF-8 tidak boleh mematikan line.
    # UnicodeDecodeError subclasses ValueError, bukan OSError — wajib ditangkap
    # eksplisit agar tidak lolos lewat handler lama.
    path = tmp_path / "media.env"
    path.write_bytes(b"LINE_1_CAMERA_TYPE=\xff\xfe\n")
    hasil = MediaEnvService(path).baca()
    assert hasil == {kode: dict(BAWAAN) for kode in LINE_CODES}


def test_tulis_gagal_saat_fsync_tidak_meninggalkan_file_separo(tmp_path, monkeypatch):
    # Kegagalan SAAT menulis (bukan di os.replace) juga harus membersihkan
    # berkas sementara, dan file asli tetap tidak berubah.
    import os

    path = tmp_path / "media.env"
    MediaEnvService(path).tulis({kode: dict(BAWAAN) for kode in LINE_CODES})
    asli = path.read_text(encoding="utf-8")

    def fsync_gagal(fileno):
        raise OSError("disk penuh")

    monkeypatch.setattr(os, "fsync", fsync_gagal)
    try:
        MediaEnvService(path).tulis(
            {
                "line-1": {"sumber": "video", "berkas": "c.mp4", "ulang": False},
                "line-2": dict(BAWAAN),
                "line-3": dict(BAWAAN),
            }
        )
    except OSError:
        pass

    # File asli tidak berubah.
    assert path.read_text(encoding="utf-8") == asli

    # Tidak ada file sementara tersisa di folder.
    tmp_files = list(tmp_path.glob(".media.env.*.tmp"))
    assert len(tmp_files) == 0


def test_tulis_berhasil_walau_berkas_bind_mount(tmp_path, monkeypatch):
    """Berkas yang di-bind-mount Docker tidak bisa di-`os.replace`.

    `docker-compose.yml` memasang `./media.env:/config/media.env` — sebuah
    BERKAS, bukan folder. Di dalam container berkas itu jadi mount point, dan
    `os.replace` ke mount point selalu gagal `EBUSY`, betapapun benar izinnya.

    Terjadi di PC Lampung 2026-09-22: layar Sumber Kamera menjawab HTTP 500
    dengan `OSError: [Errno 16] Device or resource busy` setiap kali disimpan,
    sementara `touch` ke berkas yang sama berhasil — jadi ini bukan soal izin
    dan tidak terlihat dari pemeriksaan izin mana pun.

    Kena SETIAP pemasangan Docker, bukan cuma Lampung: baris mount yang sama
    ada di `docker-compose.yml` dan `docker-compose.prod.yml` di repo ini.
    """
    import errno
    import os

    path = tmp_path / "media.env"
    MediaEnvService(path).tulis({kode: dict(BAWAAN) for kode in LINE_CODES})

    replace_asli = os.replace

    def replace_ebusy(src, dst):
        # Persis yang dilakukan kernel pada mount point, apa pun izinnya.
        if str(dst) == str(path):
            raise OSError(errno.EBUSY, "Device or resource busy")
        return replace_asli(src, dst)

    monkeypatch.setattr(os, "replace", replace_ebusy)
    MediaEnvService(path).tulis(
        {
            "line-1": {"sumber": "foto", "berkas": "sawit.jpg", "ulang": False},
            "line-2": dict(BAWAAN),
            "line-3": dict(BAWAAN),
        }
    )

    hasil = MediaEnvService(path).baca()
    assert hasil["line-1"]["sumber"] == "foto"
    assert hasil["line-1"]["berkas"] == "sawit.jpg"


def test_tulis_bind_mount_tidak_meninggalkan_berkas_sementara(tmp_path, monkeypatch):
    """Jalur cadangan tetap harus bersih-bersih sesudah dirinya."""
    import errno
    import os

    path = tmp_path / "media.env"
    replace_asli = os.replace

    def replace_ebusy(src, dst):
        if str(dst) == str(path):
            raise OSError(errno.EBUSY, "Device or resource busy")
        return replace_asli(src, dst)

    monkeypatch.setattr(os, "replace", replace_ebusy)
    MediaEnvService(path).tulis({kode: dict(BAWAAN) for kode in LINE_CODES})

    sisa = [p.name for p in tmp_path.iterdir() if p.name.startswith(".media.env.")]
    assert sisa == [], f"berkas sementara tertinggal: {sisa}"


# ───────────────────────────── model deteksi per line (sejak 2026-09-24)

import pytest  # noqa: E402

from palmgrade.domain.pilihan_model import LINE_MODEL, ModelTidakSah  # noqa: E402

KAMERA_VIDEO = {
    "line-1": dict(BAWAAN),
    "line-2": {"sumber": "video", "berkas": "konveyor.mp4", "ulang": True},
    "line-3": dict(BAWAAN),
}


def test_line_codes_sama_dengan_domain_model():
    # Domain menyalin tuple ini supaya tidak bergantung pada service.
    assert LINE_MODEL == LINE_CODES


def test_baca_model_bawaan_kosong(tmp_path):
    assert MediaEnvService(tmp_path / "media.env").baca_model() == {k: "" for k in LINE_CODES}


def test_tulis_model_lalu_baca(tmp_path):
    path = tmp_path / "media.env"
    svc = MediaEnvService(path)
    svc.tulis_model({"line-1": "", "line-2": "coba.pt", "line-3": "best.pt"})
    assert svc.baca_model() == {"line-1": "", "line-2": "coba.pt", "line-3": "best.pt"}
    isi = path.read_text(encoding="utf-8")
    assert "LINE_2_MODEL_FILE=coba.pt" in isi
    assert "LINE_1_MODEL_FILE=\n" in isi


def test_tulis_model_mempertahankan_sumber_kamera(tmp_path):
    svc = MediaEnvService(tmp_path / "media.env")
    svc.tulis(KAMERA_VIDEO)
    svc.tulis_model({"line-1": "", "line-2": "coba.pt", "line-3": ""})
    assert svc.baca() == KAMERA_VIDEO


def test_simpan_sumber_kamera_tidak_menghapus_model(tmp_path):
    # Dua layar menulis berkas yang sama. `tulis()` dulu menulis ulang seluruh
    # berkas dengan kunci kamera saja, jadi tanpa penjaga ini menyimpan Sumber
    # Kamera diam-diam mengembalikan ketiga line ke model bawaan.
    svc = MediaEnvService(tmp_path / "media.env")
    svc.tulis_model({"line-1": "coba.pt", "line-2": "", "line-3": "best.pt"})
    svc.tulis(KAMERA_VIDEO)
    assert svc.baca_model() == {"line-1": "coba.pt", "line-2": "", "line-3": "best.pt"}


def test_model_disunting_tangan_berbahaya_dibaca_kosong(tmp_path):
    path = tmp_path / "media.env"
    path.write_text(
        "LINE_1_MODEL_FILE=../../etc/x.pt\nLINE_2_MODEL_FILE=bukan-pt\nLINE_3_MODEL_FILE= best.pt \n",
        encoding="utf-8",
    )
    assert MediaEnvService(path).baca_model() == {"line-1": "", "line-2": "", "line-3": "best.pt"}


def test_tulis_model_menolak_nama_yang_menyelundupkan_baris(tmp_path):
    path = tmp_path / "media.env"
    with pytest.raises(ModelTidakSah):
        MediaEnvService(path).tulis_model(
            {"line-1": "a.pt\nLINE_1_CAMERA_TYPE=photo", "line-2": "", "line-3": ""}
        )
    assert not path.exists()


def test_berkas_lama_tanpa_baris_model_tetap_terbaca(tmp_path):
    # media.env dari versi sebelum layar Model Deteksi ada.
    path = tmp_path / "media.env"
    path.write_text("LINE_1_CAMERA_TYPE=photo\nLINE_1_MEDIA_FILE=sawit.jpg\n", encoding="utf-8")
    svc = MediaEnvService(path)
    assert svc.baca_model() == {k: "" for k in LINE_CODES}
    assert svc.baca()["line-1"]["sumber"] == "foto"
