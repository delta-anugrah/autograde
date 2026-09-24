"""Daftar model di `models/release/` + kelas tiap model, dibaca TANPA torch.

Layar Model Deteksi harus menampilkan kelas sebuah model SEBELUM model itu
dipilih: memasang model yang salah kelas tidak pernah error, line tetap jalan
dan tidak menghitung apa pun (Lampung, seminggu, 2026-09-23). Konsol tidak
memasang torch, dan memang tidak boleh butuh: memuat checkpoint 137 MB ke RAM
konsol cuma untuk membaca empat nama itu tidak sepadan.

**`.pt`** Ultralytics adalah zip buatan `torch.save`. Nama kelas ada di
`data.pkl` di dalamnya, sebagai atribut `names` objek model. Pickle itu dibaca
dengan unpickler yang TIDAK PERNAH memanggil kelas asli: setiap `find_class`
dijawab `_Stub`, sebuah dict kosong yang menelan argumen apa pun, dan tensor
(storage terpisah di zip) dijawab `None`. Hasilnya pohon dict yang cukup untuk
menemukan `names`, tanpa mengimpor torch/ultralytics, tanpa membaca bobot, dan
tanpa mengeksekusi apa pun dari berkasnya — pickle jahat cuma menghasilkan stub.
Terbukti pada dua model asli 2026-09-24: ±9 ms per model.

**`.engine`** hasil ekspor Ultralytics diawali 4 byte panjang (little-endian)
lalu JSON metadata yang memuat `names` — cara yang sama dipakai Ultralytics
sendiri saat memuatnya. Engine buatan alat lain tidak punya header itu dan
dilaporkan "kelas tidak terbaca", bukan error.

**Engine basi.** Line memilih engine dari NAMA berkas saja
(`<stem>.sm<cc>.engine`). Isi `best.pt` diganti tanpa ganti nama = engine lama
tetap dipakai, tanpa error. Yang bisa dilihat dari luar cuma dua tanda: engine
lebih tua dari `.pt`-nya, atau kelas engine berbeda dari kelas `.pt`. Dua-duanya
dipakai. Waktu diambil dari mtime berkas, bukan dari tanggal di metadata
engine: tanggal itu tanpa zona waktu, ditulis container yang zona waktunya bisa
berbeda dengan konsol.
"""
from __future__ import annotations

import collections
import json
import logging
import pickle
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain.grade_class import periksa_kelas
from ..domain.pilihan_model import ModelTidakSah, bersihkan_nama_model

logger = logging.getLogger(__name__)

#: `data.pkl` checkpoint YOLO asli 130–160 KB. Batas ini cuma penjaga terhadap
#: zip bom; bobot tidak pernah ada di berkas ini.
_BATAS_DATA_PKL = 32 * 1024 * 1024

#: Metadata engine Ultralytics beberapa KB. Lebih dari ini = bukan header.
_BATAS_META_ENGINE = 1_000_000

#: `(jenis, path, ukuran, mtime_ns)` -> hasil baca. Modul-level karena `ModelLibrary`
#: dibuat baru tiap request, seperti `MediaLibrary`.
_CACHE: dict[tuple[str, str, int, int], Any] = {}
_BATAS_CACHE = 256


class _Stub(dict):
    """Pengganti setiap kelas dan fungsi di dalam pickle.

    Dict, supaya `SETITEMS` dan `BUILD` bisa mengisinya dan `names` bisa dicari
    dengan `.get()`. `append`/`extend` ada untuk opcode `APPENDS`. Tidak ada
    satu pun method yang menyentuh dunia luar.
    """

    def __new__(cls, *_a: Any, **_k: Any) -> _Stub:
        return dict.__new__(cls)

    def __init__(self, *_a: Any, **_k: Any) -> None:
        pass

    def __setstate__(self, state: Any) -> None:
        if (
            isinstance(state, tuple)
            and len(state) == 2
            and all(s is None or isinstance(s, dict) for s in state)
        ):
            state = {**(state[0] or {}), **(state[1] or {})}
        if isinstance(state, dict):
            self.update(state)

    def append(self, _item: Any) -> None:
        pass

    def extend(self, _items: Any) -> None:
        pass


class _PembacaAman(pickle.Unpickler):
    """Unpickler yang tidak pernah memanggil kelas asli selain `OrderedDict`.

    ⚠️ Keamanan: ini pola "Restricting Globals" dari dokumentasi modul
    `pickle`. Satu-satunya jalan pickle menjalankan kode adalah memanggil
    callable yang ia dapat lewat `find_class`; di sini semuanya dijawab
    `_Stub` (dict kosong, tanpa efek) kecuali `OrderedDict`. Berkas model
    datang dari folder host yang read-only bagi konsol, tapi penjaga ini tidak
    bergantung pada itu — `test_pickle_jahat_tidak_dijalankan` membuktikannya.
    JANGAN menambah kelas asli ke daftar izin tanpa alasan yang sangat kuat.
    """

    def find_class(self, module: str, name: str) -> Any:
        if (module, name) == ("collections", "OrderedDict"):
            return collections.OrderedDict
        return _Stub

    def persistent_load(self, pid: Any) -> None:
        return None


def _urut_nama(names: Any) -> list[str] | None:
    """`{0: 'JK', 1: 'Ripe'}` atau `['JK', 'Ripe']` -> list menurut indeks."""
    if isinstance(names, dict) and names:
        def indeks(k: Any) -> tuple[int, str]:
            teks = str(k)
            return (int(teks), "") if teks.lstrip("-").isdigit() else (0, teks)

        return [str(names[k]) for k in sorted(names, key=indeks)]
    if isinstance(names, (list, tuple)) and names:
        return [str(n) for n in names]
    return None


def baca_kelas_pt(path: Path) -> list[str] | None:
    """Nama kelas checkpoint YOLO, urut indeks. `None` kalau tidak terbaca."""
    try:
        with zipfile.ZipFile(path) as z:
            info = next(
                (i for i in z.infolist() if i.filename.rsplit("/", 1)[-1] == "data.pkl"),
                None,
            )
            if info is None or info.file_size > _BATAS_DATA_PKL:
                return None
            with z.open(info) as f:
                ckpt = _PembacaAman(f).load()
    except Exception as exc:  # zip rusak, pickle rusak, apa pun: bukan urusan layar
        logger.warning("Kelas model %s tidak terbaca: %s", Path(path).name, exc)
        return None

    if not isinstance(ckpt, dict):
        return None
    for kunci in ("model", "ema"):
        model = ckpt.get(kunci)
        if isinstance(model, dict):
            nama = _urut_nama(model.get("names"))
            if nama:
                return nama
    return None


def baca_meta_engine(path: Path) -> dict[str, Any] | None:
    """`{"kelas": [...]}` dari header engine Ultralytics. `None` kalau tidak ada."""
    try:
        with open(path, "rb") as f:
            kepala = f.read(4)
            if len(kepala) != 4:
                return None
            panjang = int.from_bytes(kepala, "little", signed=True)
            if not 0 < panjang <= _BATAS_META_ENGINE:
                return None
            meta = json.loads(f.read(panjang).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    return {"kelas": _urut_nama(meta.get("names"))}


def _tercache(jenis: str, path: Path, baca: Any) -> Any:
    st = path.stat()
    kunci = (jenis, str(path), st.st_size, st.st_mtime_ns)
    if kunci not in _CACHE:
        if len(_CACHE) >= _BATAS_CACHE:
            _CACHE.clear()
        _CACHE[kunci] = baca(path)
    return _CACHE[kunci]


def _iso(detik: float) -> str:
    return datetime.fromtimestamp(detik, tz=UTC).isoformat(timespec="seconds")


def _alasan(kelas: list[str] | None) -> str:
    if kelas is None:
        return "kelas tidak terbaca — bukan checkpoint YOLO?"
    asing, hilang = periksa_kelas(kelas)
    bagian = []
    if asing:
        bagian.append(f"kelas tidak dikenal: {', '.join(asing)}")
    if hilang:
        bagian.append(f"kelas hilang: {', '.join(hilang)}")
    return "; ".join(bagian)


class ModelLibrary:
    """Model di `release_dir` beserta engine TensorRT-nya di `engines_dir`."""

    def __init__(self, release_dir: Path, engines_dir: Path) -> None:
        self._release = Path(release_dir)
        self._engines = Path(engines_dir)

    def daftar(self) -> list[dict[str, Any]]:
        """Semua `.pt`, urut nama. Model rusak tetap tampil, ditandai tidak cocok."""
        try:
            berkas = sorted(
                p for p in self._release.iterdir() if p.is_file() and p.suffix == ".pt"
            )
        except OSError:
            return []
        hasil = []
        for p in berkas:
            try:
                hasil.append(self._satu(p))
            except OSError:
                # Dihapus (atau dipindah) di antara iterdir() dan stat(). Model
                # yang sudah tidak ada memang tidak boleh tampil; 500 untuk
                # seluruh layar jauh lebih buruk.
                continue
        return hasil

    def terbaca(self) -> bool:
        """Folder model bisa dibuka. False = tidak ada / tidak ter-mount / izin.

        Beda dari folder KOSONG, dan bedanya penting: `daftar()` memulangkan
        `[]` untuk keduanya. Di PC pabrik compose hidup di host, jadi lupa
        menambah mount `./models` ke konsol adalah kegagalan pertama yang akan
        ditemui — dan "belum ada model" mengundang orang menyalin model lagi.
        """
        try:
            next(iter(self._release.iterdir()), None)
        except OSError:
            return False
        return True

    def cari(self, nama: str) -> dict[str, Any] | None:
        return next((m for m in self.daftar() if m["berkas"] == nama), None)

    def _satu(self, pt: Path) -> dict[str, Any]:
        st = pt.stat()
        # Lewat atribut modul, bukan nama lokal, supaya tes bisa menghitung
        # berapa kali berkas benar-benar dibaca.
        kelas = _tercache("pt", pt, lambda p: baca_kelas_pt(p))
        # Nama diperiksa dengan aturan yang sama dengan gerbang simpan: berkas
        # yang namanya tidak bisa ditulis ke media.env tampil dengan alasannya,
        # bukan lolos ke dropdown lalu ditolak 400 saat disimpan.
        try:
            bersihkan_nama_model(pt.name)
            alasan = _alasan(kelas)
        except ModelTidakSah as exc:
            alasan = f"nama berkas: {exc}"
        return {
            "berkas": pt.name,
            "ukuran_mb": round(st.st_size / 1_000_000, 1),
            "diubah": _iso(st.st_mtime),
            "kelas": kelas,
            "cocok": not alasan,
            "alasan": alasan,
            "engine": self._engine_untuk(pt, kelas, st.st_mtime),
        }

    def _engine_untuk(
        self, pt: Path, kelas_pt: list[str] | None, mtime_pt: float
    ) -> list[dict[str, Any]]:
        pola = re.compile(rf"^{re.escape(pt.stem)}\.sm(\d+)\.engine$")
        hasil = []
        try:
            kandidat = sorted(self._engines.iterdir())
        except OSError:
            return []
        for engine in kandidat:
            cocok = pola.match(engine.name)
            if not cocok or not engine.is_file():
                continue
            try:
                meta = _tercache("engine", engine, baca_meta_engine)
                mtime = engine.stat().st_mtime
            except OSError:
                continue  # dihapus di tengah jalan, alasan yang sama dengan daftar()
            kelas = meta["kelas"] if meta else None
            beda_kelas = kelas is not None and kelas_pt is not None and kelas != kelas_pt
            hasil.append(
                {
                    "berkas": engine.name,
                    "sm": cocok.group(1),
                    "kelas": kelas,
                    "dibuat": _iso(mtime),
                    "basi": mtime < mtime_pt or beda_kelas,
                }
            )
        return hasil
