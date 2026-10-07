---
name: scanner-qr
description: The truck QR scanner the mill bought (CASHCOW HC-4208DB, a rebranded YuRiot HID keyboard scanner), how it connects (2.4G dongle, Bluetooth, cable), what works on macOS, Windows and the Linux factory PC, its lights and beeps, the settings done by scanning barcodes in the paper manual, and how the console receives a scan. Use when connecting or debugging the scanner ("scanner nggak ngetik", "beep tapi nggak muncul", "huruf ngaco"), setting it up on a factory PC, or changing how the console reads QR scans.
---

# QR scanner: CASHCOW HC-4208DB

Bought 2026-10-05 for the four gate steps (rules 20 and 37). Since
2026-10-06 the console has **one** scan field that records the truck's next step; it shows
only when support turns on **Settings > Scanner QR** (PR #249, default off). Since 2026-10-07 a scan
works from **any tab** and the answer is a popup (see Device).

## Device

| | |
|---|---|
| Sold as | CASHCOW HC-4208DB (OEM rebrand) |
| USB name | "Barcode Scanner Keyboard", manufacturer string "YuRiot" |
| USB ids | vendor `0x0461`, product `0x4d86` |
| Type | HID keyboard wedge: a scan arrives as typed keys. No driver, no SDK, no WebHID or Web Serial |
| Reads | 1D (Code-128, EAN, ...) and 2D (QR), also from a phone screen |
| Connects | 2.4G USB dongle, Bluetooth 4.2 (device name "Barcode Scanner HID"), or USB cable |
| Memory | 16 MB Storage Mode: keeps scans made out of range |
| In the box | scanner, dock (auto-sense when docked, manual trigger when lifted), 2.4G dongle, USB-C cable, paper manual |

## What works where (tested 2026-10-06)

| OS | 2.4G dongle | Bluetooth |
|---|---|---|
| macOS | Detected (`system_profiler SPUSBHostDataType`; `SPUSBDataType` is gone on new macOS) but **types nothing** | Works: use this on the MacBook |
| Windows | Works | not tried |
| Linux (factory PC, Lampung) | **not tried yet** | not tried; check first that the PC has Bluetooth at all |

Scanner and dongle are both healthy; the macOS problem is only dongle versus macOS.

## Lights and beeps

- Blue light = on and connected; red = charging; off = not connected.
- 1 short beep = scan or pairing OK; 3 short beeps = wireless link lost; 5 short beeps = battery empty.

## Settings (scan the barcodes in the paper manual; there is no software)

- Connection: 2.4G Mode, Bluetooth Mode, Pair with dongle, Pair with Bluetooth.
- Scan mode: Normal Scan Mode, Storage Mode, Data Upload, Sum Data, Clear Data.
- Trigger: Manual Trigger, Sense Mode (auto).
- Symbologies: enable or disable all 1D, enable or disable all 2D. Keep 2D on (QR).
- Case: All Capital, All lowercase, Cancel case setting.
- Hide characters: drop 1 to 4 characters from the front or the back.
- Sleep: Immediately, 5 min, 30 min (default), Never Sleep.
- Sound: Off, Low, Medium, High.
- Reset: Restore Wireless Parameters (wireless only; pair again afterwards).

The paper manual lists no suffix (Enter) and no keyboard-language setting.

## How the console receives a scan

- Since 2026-10-07 a capture-phase key catcher on `document` (`tangkapScan`) reads the scanner
  on every tab, so no field needs the focus: at most 100 ms between characters, Enter within
  500 ms of the last one, at least 3 characters. A fast run that breaks off is a failed read
  ("Scan tidak terbaca, ulangi scan"), never sent half. The field `#scan-otomatis` still keeps
  the focus on the Timbangan tab (`jagaFokusScan`) and still takes a plate typed by hand.
- Space+N (Manual Reject) and P+N (piston) are guarded by `ledakanScan()`: only 3 or more fast
  characters count as a scan, so the plate `B 1995 SME` does not fire Space+1.
- It submits **only on Enter**. This scanner **does send Enter**
  after a scan: verified 2026-10-06 over Bluetooth on a Mac (all four steps worked).
- The server picks the step from the truck's state (`POST /api/console/scan/auto`, rule 20):
  datang, timbang isi, timbang kosong, keluar. Weight comes from the live scale when fit
  (rule 39), otherwise a popup with a weight field opens, on any tab (Enter saves, the same QR
  scanned again saves, another QR or Esc closes it, 60 s idle closes it; letters never become a
  weight). With **Timbangan dummy** on (support, Settings > Mode Developer) the weight is 30,000
  kg (isi) or 10,000 kg (kosong) and the popup never opens.
- The answer is a popup (`#scan-popup`, a `div`, not a dialog): success closes in 4 s, a failure
  in 8 s, and lists the lines in card order.
- Double reads: the screen drops the same QR within 2 s (`JEDA_BACA_ULANG_MS`), and a step
  within 3 minutes of the truck's previous step asks "Catat?" first; scanning the same QR again
  (from 2 s after the question opened) answers Catat, another QR answers Batal.
- The QR holds the normalised plate and nothing else (rule 20). A test QR for any truck:
  `GET /api/console/trucks/{plate}/qr.png`, e.g. `http://127.0.0.1:8100/api/console/trucks/BE%206311%20TSA/qr.png`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Beep, but nothing typed | Normal Scan Mode, not Storage Mode. On macOS: dongle does not type, switch to Bluetooth |
| 3 beeps | Wireless link lost: move closer, or pair again (Pair with dongle / Pair with Bluetooth) |
| Nothing at all, light off | Charge it (red light), press the trigger to wake it (sleep is 30 min by default) |
| Text arrives but the console does nothing | Settings > Scanner QR is off, or the scanner is too slow (over 100 ms between characters shows "Scan tidak terbaca") |
| Wrong or lowercase letters | Scan "All Capital"; the console normalises the plate anyway |
