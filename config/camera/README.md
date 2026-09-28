# Camera config (Hikrobot MVS)

Reference snapshots of Hikrobot GigE camera parameters, exported from MVS via
**Feature Save** (`MV_CC_FeatureSave`). Plain-text GenApi persistence files (`.mfs`).

**This is where the frame rate is set.** `hikrobot.mfs` is pushed to the camera
on every connect (`MV_CC_FeatureLoad`, see `integrations/camera/hikrobot_camera.py`),
and the capture worker then asks the camera what rate it ended up with and paces
itself by that. So the rate lives in exactly one place: `AcquisitionFrameRate` in
this file. `CAMERA_FPS` is only a fallback for cameras that cannot report a rate
(a webcam, a video file) and does nothing on a Hikrobot line.

Changing the rate: edit `AcquisitionFrameRate` here, keep `AcquisitionFrameRateEnable`
at `1`, keep `ExposureTime` under one frame period, and update `EXPECTED_FPS` in
`tests/unit/test_camera_feature_file.py` plus `docs/camera-spec.md` § 2.2, the test
pins the number on purpose, so a drift is caught instead of discovered months later.
⚠️ Read `docs/camera-spec.md` § 3.1 first: GPU, GigE bandwidth and belt speed each
cap the useful rate, and they are not the same ceiling.

## Files

| File | Source camera | Notes |
|---|---|---|
| `hikrobot.mfs` | HIKROBOT GigE Vision (device v1.2.0) | re-exported 2026-06-29 from `SAWIT-latest` MVS Feature Save (adds Decimation params; white balance masih Continuous: locking ke Once di-track terpisah) |

## Apply via MVS

1. Open **MVS** → connect the camera.
2. Right-click device → **Feature** → **Feature Load**.
3. Select the `.mfs` file → load.

## Re-export after tuning

After tuning a camera in MVS, **Feature Save** to a new `.mfs`, drop it here,
and add a row to the table above (keep the date so snapshots stay distinguishable).
