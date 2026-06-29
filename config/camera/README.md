# Camera config (Hikrobot MVS)

Reference snapshots of Hikrobot GigE camera parameters, exported from MVS via
**Feature Save** (`MV_CC_FeatureSave`). Plain-text GenApi persistence files (`.mfs`).

These are **reference / backup only** — the service does **not** auto-load them.
To apply on a camera, use MVS (or `MV_CC_FeatureLoad`) manually.

## Files

| File | Source camera | Notes |
|---|---|---|
| `hikrobot.mfs` | HIKROBOT GigE Vision (device v1.2.0) | exported 2026-06-17 from production-tuned line |

## Apply via MVS

1. Open **MVS** → connect the camera.
2. Right-click device → **Feature** → **Feature Load**.
3. Select the `.mfs` file → load.

## Re-export after tuning

After tuning a camera in MVS, **Feature Save** to a new `.mfs`, drop it here,
and add a row to the table above (keep the date so snapshots stay distinguishable).
