# Frontend Overview — supplier-dashboard

Dokumen ini adalah rangkuman menyeluruh tentang project `supplier-dashboard`
sebagai frontend untuk sistem inspeksi kematangan sawit.

## Tujuan Project

Dashboard web untuk operator pabrik: memantau hasil inspeksi kematangan sawit
secara realtime, mengelola data truck dan supplier, serta melakukan verifikasi
manual hasil AI.

---

## Tech Stack

| Layer | Teknologi |
|---|---|
| Framework | Next.js 15 (App Router) |
| Language | TypeScript |
| UI library | shadcn/ui + Tailwind CSS 4 |
| Data fetching | TanStack Query (React Query) v4 |
| HTTP client | Axios |
| State management | Zustand |
| Table | TanStack Table v8 |
| Schema validation | Zod |
| Realtime | EventSource (SSE) |
| Auth | Clerk (via `[[...sign-in]]` routing) |

---

## API Clients

FE berkomunikasi dengan **tiga backend berbeda**, masing-masing pakai Axios
instance terpisah di [src/lib/axios.ts](../../supplier-dashboard/src/lib/axios.ts).

### `axios` — Main API (Node.js)

```
baseURL: ${NEXT_PUBLIC_API_URL}/api/${NEXT_PUBLIC_API_VERSION}
withCredentials: true
timeout: 20s
```

Dipakai untuk semua data management: quality controls, trucks, suppliers,
companies, machines, users, dll.

Auto-redirect ke login jika response 401.

---

### `axiosSawit` — Python BE (ripe-recognition-main)

```
baseURL: ${NEXT_PUBLIC_SAWIT_API_URL}
timeout: 20s
```

Dipakai hanya untuk 2 endpoint di Python BE:
- `POST /api/capture_reject`
- `POST /api/set_truck`

Video feed diakses langsung via `<img src>`, bukan axios.

---

### `axiosFactory` — Factory API

```
baseURL: ${NEXT_PUBLIC_FACTORY_API_URL}/api/${NEXT_PUBLIC_API_VERSION}
headers: { x-api-key: NEXT_PUBLIC_FACTORY_API_KEY }
timeout: 20s
```

Dipakai untuk data monitoring tangki/pabrik (fitur terpisah dari quality
control).

---

## Env Vars FE

| Variable | Keterangan |
|---|---|
| `NEXT_PUBLIC_API_URL` | URL Node.js API (port 2500) |
| `NEXT_PUBLIC_API_VERSION` | Versi API, default `v1` |
| `NEXT_PUBLIC_SAWIT_API_URL` | URL Python BE (ripe-recognition-main, port 8000) |
| `NEXT_PUBLIC_FACTORY_API_URL` | URL Factory API |
| `NEXT_PUBLIC_FACTORY_API_KEY` | API key untuk Factory API |

Semua wajib diisi. Jika salah satu kosong, app throw error saat startup.

---

## Halaman Utama

### Quality Control (`/dashboard/quality-control`)

Halaman utama untuk operator. Komponen utama:

**[quality-control-list.tsx](../../supplier-dashboard/src/modules/quality-control/list/quality-control-list.tsx)**

- Pilih truck aktif via dropdown
- Tampilkan live video feed dari kamera
- Tombol "Capture Reject" (atau tekan `C` di keyboard)
- Tabel grading history (15 item terbaru)
- Grading summary (total, match rate, avg confidence)

**[quality-control.hooks.ts](../../supplier-dashboard/src/modules/quality-control/list/quality-control.hooks.ts)**

- Connect SSE ke Node.js API untuk real-time detection updates
- Handle capture reject → call `POST /api/capture_reject`
- Handle truck select → call `POST /api/set_truck`
- Handle human approval (match/mismatch) → call `PATCH /qualitycontrols/{id}/status`

---

## Koneksi ke Python BE (ripe-recognition-main)

### 1. Video Feed

```tsx
// quality-control-list.tsx:110
<img src={`${process.env.NEXT_PUBLIC_SAWIT_API_URL}/api/video_feed`} />
```

Langsung ke BE via `<img>` tag. Tidak melewati axios. Format MJPEG.

---

### 2. Capture Reject

```ts
// services/quality-control/mutations/capture-reject.ts
axiosSawit.post('/api/capture_reject')
```

**Response yang diharapkan FE** (`IResultResponse`):
```ts
interface IResultResponse {
  message: string;
  event?: {
    id: string;
    status: 'FAIL' | 'PASS' | 'WARNING';
    title: string;
    description: string;
    timestamp: string;
    image_url: string;
    capture_type?: 'manual' | 'auto';
  }
}
```

Setelah sukses: invalidate query `quality-controls`, tampilkan toast success.

---

### 3. Set Truck ID

```ts
// services/quality-control/mutations/set-truck-id.ts
axiosSawit.post('/api/set_truck', { truck_id: string })
```

**Request body:**
```ts
interface ISetTruckId {
  truck_id: string;
}
```

Setelah sukses: invalidate query `trucks`, tampilkan toast success.

---

## Koneksi ke Node.js API (Main API)

### Quality Controls (data history)

```ts
// services/quality-control/queries/get-quality-controls.ts
axios.get('/qualitycontrols')
```

**Response type:**
```ts
interface IQualityControl {
  id: string;
  timestamp: string;
  image_path: string;
  prediction: 'reject' | 'Rej' | 'Acc';
  tp_status: 'PASS';
  tp_confidence: number;
  ripeness_status: 'ACC';
  ripeness_confidence: number;
  capture_type: 'manual' | 'auto';
  truck_id: string;
  bounding_box: { x_min, x_max, y_min, y_max };
  plate_number: string;
  capacity: string;
  manufacturing_year: number;
  truck_status: 'active' | 'inactive';
  loading_zone: string;
  supplier_name: string;
  contact_person: string;
  inserted_at: string;
}
```

Data ini berasal dari webhook yang dikirim Python BE ke Node.js setiap ada
detection. FE tidak fetch langsung dari Python BE untuk history.

---

### Realtime Update (SSE)

```ts
// quality-control.hooks.ts:109
const eventSource = new EventSource(
  `${NEXT_PUBLIC_API_URL}/api/${NEXT_PUBLIC_API_VERSION}/qualitycontrols/stream`
);

eventSource.addEventListener('new_quality_control', (e) => {
  const data = JSON.parse(e.data);
  setCurrentData(data?.saved);
  refetch();
});
```

FE listen ke SSE dari Node.js API. Setiap ada `new_quality_control` event:
1. Update `currentData` (tampil di panel kiri)
2. Refetch list quality controls

**Flow lengkap:**
```
Python BE detect buah
  → kirim webhook ke Node.js API
  → Node.js simpan ke DB + broadcast SSE
  → FE terima SSE event
  → FE update UI
```

---

### Update Status (Human Verification)

```ts
// services/quality-control/mutations/update-quality-control-status.ts
axios.patch(`/qualitycontrols/${id}/status`, { prediction: 'Acc' | 'Rej' })
```

Operator bisa override hasil AI. Hanya aktif jika `supplier.human_verification === true`.

---

## Services Directory Structure

```
src/services/
  quality-control/
    mutations/
      capture-reject.ts       → POST /api/capture_reject  (axiosSawit)
      set-truck-id.ts         → POST /api/set_truck        (axiosSawit)
      update-quality-control-status.ts → PATCH /qualitycontrols/{id}/status (axios)
      create-quality-control.ts
      delete-quality-control.ts
      update-quality-control.ts
    queries/
      get-quality-controls.ts → GET /qualitycontrols       (axios)
      get-quality-control.ts  → GET /qualitycontrols/{id}  (axios)
      get-quality-control-stat.ts → GET /qualitycontrols/stats (axios)
    quality-control.keys.ts   # Endpoint paths + React Query keys

  truck/
    mutations/                # CRUD truck → Main API
    queries/
      get-trucks.ts           → GET /trucks                (axios)

  supplier/
    queries/
      get-supplier.ts         → GET /suppliers/{id}        (axios)
      # Dipakai untuk cek human_verification flag

  # ... service lain (companies, machines, users, dll) semuanya ke Main API
```

---

## Types yang Relevan dengan Python BE

### `IResultResponse` — response dari `capture_reject`

```ts
interface IResult {
  id: string;
  status: 'FAIL' | 'PASS' | 'WARNING';
  title: string;
  description: string;
  timestamp: string;
  image_url: string;
  capture_type?: 'manual' | 'auto';
}

interface IResultResponse {
  message: string;
  event?: IResult;
}
```

### `ISetTruckId` — request body ke `set_truck`

```ts
interface ISetTruckId {
  truck_id: string;
}
```

---

## Hal-hal Kritis untuk Migrasi BE

Agar FE tidak break setelah migrasi ke `ripe-recognition-main`:

1. **`GET /api/video_feed`** — wajib return MJPEG stream. FE load langsung via
   `<img src>`. Kalau endpoint return JSON, gambar tidak tampil.

2. **`POST /api/capture_reject`** — wajib return body JSON. FE expect `IResultResponse`.
   Response lama dari `sawit-main` hanya `{"message": "..."}` tanpa field `event`.
   Sudah di-cover oleh schema `CaptureRejectResponse` di skeleton.

3. **`image_url` path format** — harus `captures/results/{date}/{timestamp}.jpg`
   (bukan `artifacts/results/...`). FE akan prepend `NEXT_PUBLIC_SAWIT_API_URL`
   untuk akses static file. StaticFiles mount di main.py harus konsisten.

4. **CORS** — FE origin harus di-allow di `CORSMiddleware`. Set via env var
   `FRONTEND_URL`.

5. **Webhook ke Node.js** — ini yang bikin data muncul di tabel history FE.
   Kalau webhook putus, tabel kosong.

6. **`NEXT_PUBLIC_SAWIT_API_URL`** — satu-satunya env var FE yang perlu diubah
   setelah migrasi (point ke port/host baru jika berubah).
