# USRP B210 Spectrum Monitoring System

## Overview

This project is a responsive web application for monitoring the 50–6000 MHz spectrum with a USRP B210. It provides General and Specific scan modes, an autonomous rolling sweep, threshold-point detection, GSM/UMTS/LTE/NR candidate classification, Machine and Channel management, and authenticated local administrator access.

Cellular classification is frequency and channel-plan candidate matching. It does not demodulate cellular protocols, decode network traffic, or prove that a cellular service is active. Spectrum power uses the project's empirical reference display scale for visualization and threshold comparison; values are not calibrated laboratory dBm.

## Features

### Spectrum acquisition and processing

- 50–6000 MHz monitoring range.
- Autonomous continuous stepped sweep until Stop is requested.
- Isolated UHD worker process with persistent device, RX streamer, metadata, and receive-buffer resources.
- 20 MHz acquisition/hop policy for requested spans below 100 MHz.
- 56 MHz acquisition/hop policy for spans of 100 MHz or wider.
- 1,024 complex IQ samples and a 1,024-point FFT per hop.
- Symmetric Hann window and FFT frequency shift.
- 2 ms settling delay after each center-frequency change.
- Latest committed spectrum snapshots delivered independently of acquisition.

### Threshold detection and classification

Every FFT bin whose power passes the configured threshold is an independent detection candidate. Neighboring threshold-passing bins are not clustered or deduplicated. There is no merge-gap grouping, signal clustering, or one-peak-per-signal reduction.

Each eligible bin is matched against frequency/channel definitions for:

- GSM / 2G
- UMTS / 3G
- LTE / 4G
- NR / 5G

### General Scan

- Operator-selected start and end frequencies.
- Configurable display-scale threshold.
- Autonomous rolling sweep with start and stop controls.
- Realtime shared-Canvas spectrum view.
- Detection count, current-session detection list, candidate classification, sweep progress, completed cycles, and last-window state.
- WebSocket spectrum updates with REST snapshot fallback.

### Specific Scan

- Selects a stored Machine and uses its associated Channels as scan targets.
- Handles available downlink (DL) and uplink (UL) target frequencies.
- Measures each target from the nearest FFT bin, including targets below the threshold.
- Reports measured power and `ON`, `OFF`, or `NOT SCANNED` state.
- Keeps Specific results isolated from General results and from other Machines.
- Enforces one General or Specific scan owner at a time.

### Data management

- Machine create, read, update, and delete operations.
- Channel create, read, update, and delete operations.
- Channel lookup by supported technology/profile and FCN.
- One-to-many Machine-to-Channel relationship with cascading Channel deletion.
- MySQL/MariaDB-compatible persistence through SQLAlchemy and PyMySQL.

### Authentication and interface

- Local/internal administrator login, session check, password change, and logout.
- Plaintext administrator password stored in the local `users.password` column and managed through MySQL/MariaDB.
- Signed HttpOnly session cookie.
- Protected application API routes and authenticated spectrum WebSocket.
- Safe logout that stops an active General or Specific scan before clearing the session.
- Independent password visibility controls for login and each Change Password field.
- Responsive desktop, tablet, and mobile web layouts, including compact navigation, scan panels, Machine cards, Login, and Change Password views.

## Architecture

```text
Browser
  -> authentication gate and signed session
  -> React General / Specific scan interface
  -> FastAPI backend
  -> autonomous scan controller
  -> isolated persistent UHD worker
  -> USRP B210
  -> IQ samples
  -> Hann window + 1,024-point FFT + frequency shift
  -> reference display-power processing
  -> independent threshold-point detection and candidate classification
  -> committed backend scan state
  -> authenticated WebSocket or REST snapshot
  -> React state
  -> shared Canvas 2D spectrum renderer
```

The frontend does not drive acquisition by polling. FastAPI owns the scan lifecycle and commits state after completed acquisition windows. A bounded WebSocket fan-out sends each client the latest available snapshot; REST remains a read-only fallback.

UHD runs outside the web server process. This keeps native hardware interaction separated from FastAPI, permits device and streamer reuse throughout a scan, and allows the parent process to handle worker failure or hardware disconnect cleanup without running UHD directly in the API process.

## Technology Stack

### Backend

- Python
- FastAPI and Uvicorn
- UHD Python API
- NumPy and Pydantic
- SQLAlchemy and PyMySQL
- python-dotenv
- itsdangerous and Starlette session support
- WebSockets
- Python multiprocessing and threading primitives

### Frontend

- React and React DOM
- Vite
- Native Fetch and WebSocket APIs
- Canvas 2D
- Responsive CSS
- Chakra Petch and Jost fonts

### Database

- MySQL/MariaDB-compatible database
- `users`: local administrator identities and plaintext passwords
- `machines`: named monitored equipment records
- `channels`: cellular channel targets belonging to a Machine

## USRP Hardware and Current Scanner Configuration

A UHD-compatible USRP B210 is required for live acquisition. The B210 provides two RX channels. This project uses the `RX2` receive input and 35 dB RX gain as its established RF configuration.

Before live acquisition, configure the USRP values in `backend/main.py`:

```python
USRP_SERIAL = "SET_DEVICE_SERIAL"
CHANNEL = 0
RX_ANTENNA = "RX2"
GAIN_DB = 35
```

`USRP_SERIAL = "SET_DEVICE_SERIAL"` is a placeholder for a new installation and must be replaced with the serial number of the B210 connected to the system.

`CHANNEL` defaults to `0` and may be changed to `1` when the other RX channel is used. The scanner uses one selected RX channel at a time.

`RX_ANTENNA = "RX2"` and `GAIN_DB = 35` are the project's fixed RF operating configuration and normally do not need to be changed.

### Finding the USRP Serial on Windows

If UHD commands are not available globally from PowerShell or Command Prompt, open Command Prompt and change to the UHD binary directory:

```cmd
cd /d "C:\Program Files\UHD\bin"
```

Detect connected UHD devices:

```cmd
uhd_find_devices.exe
```

Find the USRP B210 entry and note the value shown after:

```text
serial: <device-serial>
```

Replace the placeholder in `backend/main.py`:

```python
USRP_SERIAL = "<device-serial>"
```

Restart the backend after changing the serial.

To inspect the connected B210 in more detail, run:

```cmd
uhd_usrp_probe.exe --args="serial=<device-serial>"
```

The probe can be used to verify that the B210 is recognized by UHD and to inspect its available RX channels and hardware capabilities.

## Project Structure

```text
.
|-- backend/
|   |-- main.py
|   |-- scanner_worker.py
|   |-- spectrum_stream.py
|   |-- database.py
|   |-- models.py
|   |-- schemas.py
|   |-- auth_session.py
|   |-- auth_middleware.py
|   |-- auth_routes.py
|   |-- bootstrap_admin.py
|   |-- migrations/
|   |   `-- 20260807_create_users.sql
|   |-- machine_routes.py
|   |-- channel_routes.py
|   |-- channel_lookup.py
|   |-- channel_lookup_routes.py
|   |-- gsm_classifier.py
|   |-- umts_classifier.py
|   |-- lte_classifier.py
|   `-- nr_classifier.py
|-- frontend/
|   |-- src/
|   |   |-- main.jsx
|   |   |-- AuthGate.jsx
|   |   |-- LoginPage.jsx
|   |   |-- App.jsx
|   |   |-- SpecificChannelPage.jsx
|   |   |-- SpectrumCanvas.jsx
|   |   |-- useSpectrumStream.js
|   |   `-- spectrumTransport.js
|   |-- test/
|   `-- package.json
|-- tests/
|-- requirements.txt
`-- README.md
```

Generated dependencies, build output, caches, virtual environments, and local data are omitted.

## Requirements

- Python and the packages in `requirements.txt`.
- Node.js and npm.
- UHD and its Python API available to the backend environment.
- A connected USRP B210 for live spectrum acquisition.
- An accessible MySQL/MariaDB-compatible database.

## Installation

Clone the repository using a non-identifying repository URL:

```powershell
git clone <repository-url>
cd <project-folder>
```

Create the backend environment and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
cd frontend
npm install
```

## Database Configuration

`backend/database.py` loads a project-root `.env` file and reads the following settings:

```dotenv
DB_HOST=<database-host>
DB_PORT=<database-port>
DB_NAME=<database-name>
DB_USER=<database-user>
DB_PASSWORD=<database-password>
```

Equivalent connection-string form:

```text
mysql+pymysql://<database-user>:<database-password>@<database-host>:<database-port>/<database-name>
```

Keep `.env` private and outside version control. Normal application startup does not create tables or run complete database migrations; provision the `users`, `machines`, and `channels` tables before use.

## Authentication Configuration

The backend requires a session-signing secret in the project-root `.env` file:

```dotenv
SESSION_SECRET=<session-secret>
```

Keep this value private and never commit it. The implementation requires at least 32 characters and at least 8 distinct characters.

Apply the tracked users-table migration through the database administration workflow:

```text
backend/migrations/20260807_create_users.sql
```

Then create the local administrator interactively from the project root:

```powershell
python -m backend.bootstrap_admin
```

The command prompts locally for an administrator username, password, and confirmation, then stores the password directly in `users.password`. After provisioning, edit that field in MySQL/phpMyAdmin to change the administrator password. Credentials are not repository configuration.

## Local Development

Start FastAPI from the project root:

```powershell
python -m uvicorn backend.main:app --host localhost --port 8000
```

Start Vite in another terminal:

```powershell
cd frontend
npm run dev
```

Vite normally serves the development frontend on port `5173`. Frontend code uses relative `/api` requests. During development, Vite proxies both HTTP and WebSocket `/api` traffic to FastAPI on port `8000`. These commands describe the local development workflow.

## Authentication Flow

- `POST /api/auth/login` compares the submitted password directly with `users.password` and creates a signed session when it matches.
- `GET /api/auth/me` checks the current session and returns the authenticated identity.
- `POST /api/auth/change-password` requires authentication, verifies the current plaintext password, and stores a valid replacement directly in `users.password`. The current session remains active after success.
- `POST /api/auth/logout` clears the session. The frontend first stops an active scan using its current General/Specific owner.
- Application API access requires a valid session, and unauthenticated spectrum WebSocket connections are rejected.

The current implementation intentionally does not include registration, OAuth, JWT, role-based access control, email recovery, or password-reset workflows.

## API and Transport

| Group | Method | Path | Purpose |
|---|---|---|---|
| Authentication | `POST` | `/api/auth/login` | Verify credentials and create a session |
| Authentication | `GET` | `/api/auth/me` | Check the current session |
| Authentication | `POST` | `/api/auth/change-password` | Replace the authenticated administrator password |
| Authentication | `POST` | `/api/auth/logout` | Clear the current session |
| Device | `GET` | `/api/device/status` | Read passive SDR connection state |
| Device | `GET` | `/api/device` | Compatibility alias for device status |
| Scanner | `GET` | `/api/status` | Read scanner, progress, and cycle state |
| Scanner | `POST` | `/api/scan/start` | Start a General or Specific rolling scan |
| Scanner | `POST` | `/api/scan/stop` | Stop the active scan for its owner |
| Scanner | `GET` | `/api/scan/results` | Read current-session detections, measurements, and preview |
| Spectrum | `GET` | `/api/spectrum` | Read the latest committed spectrum snapshot |
| Spectrum | `WS` | `/api/spectrum/stream` | Receive authenticated realtime spectrum snapshots |
| Machines | `GET`, `POST` | `/api/machines` | List or create Machines |
| Machines | `GET`, `PUT`, `DELETE` | `/api/machines/{machine_id}` | Read, update, or delete a Machine |
| Channels | `GET`, `POST` | `/api/machines/{machine_id}/channels` | List or create Channels for a Machine |
| Channels | `GET`, `PUT`, `DELETE` | `/api/channels/{channel_id}` | Read, update, or delete a Channel |
| Lookup | `GET` | `/api/channel-lookup` | Resolve supported technology/profile and FCN candidates |

The WebSocket stream uses bounded per-client queues and replaces stale queued frames with the latest committed snapshot. Client-side session, scan-owner, and selected-Machine checks reject mismatched snapshots. If the WebSocket is unavailable or unhealthy, the frontend polls the read-only spectrum endpoint instead.

## Scan Behavior

The backend validates the requested range, derives ordered hop centers, and advances through them in an autonomous controller thread. A completed pass increments the cycle count and immediately begins another pass until Stop or a lifecycle/acquisition error.

- Spans below 100 MHz use the 20 MHz policy.
- Spans of 100 MHz or wider use the 56 MHz policy.
- Each hop acquires 1,024 IQ samples after a 2 ms tuner settle.
- A symmetric Hann window is applied before the FFT.
- FFT output is shifted into frequency order and cropped to the requested range.
- FFT magnitude-squared power is converted to the project's empirical reference display scale.

Every threshold-passing FFT bin remains independently eligible for detection and classification, including adjacent bins. No clustering, merge-gap processing, or peak-only grouping is active.

For Specific Scan, the backend snapshots the selected Machine's stored DL/UL targets when the scan starts. Each target is measured from the nearest in-range FFT bin. Measurement remains available below the threshold so the UI can derive `ON`/`OFF`; targets not yet covered remain `NOT SCANNED`.

## Responsive Web Interface

Responsive behavior is implemented in the React/CSS frontend. Layouts adapt across desktop, tablet, and narrow mobile portrait widths, including approximately 360–412 px. The application provides compact mobile header/navigation behavior, responsive General and Specific scan views, mobile Machine cards/action controls, and responsive Login and Change Password interfaces. This is a responsive website, not a native mobile application.

## Test Inventory

The tracked source contains **83 statically visible test cases across 10 files**:

| Area | File | Cases |
|---|---|---:|
| Authentication | `backend/test_authentication.py` | 14 |
| Spectrum stream manager | `backend/test_spectrum_stream.py` | 5 |
| Spectrum WebSocket endpoint | `backend/test_spectrum_stream_endpoint.py` | 1 |
| Autonomous lifecycle | `tests/test_autonomous_lifecycle.py` | 23 |
| Reference fast scan | `tests/test_reference_fast_scan.py` | 9 |
| Reference power scale | `tests/test_reference_power_scale.py` | 7 |
| General spectrum preview | `frontend/test/generalSpectrumPreview.test.mjs` | 9 |
| Spectrum Canvas layout | `frontend/test/spectrumCanvasLayout.test.mjs` | 7 |
| Spectrum chart scale | `frontend/test/spectrumChartScale.test.mjs` | 4 |
| Spectrum transport | `frontend/test/spectrumTransport.test.mjs` | 4 |

This inventory comprises 59 Python `unittest` cases and 24 frontend Node `node:test` cases. It describes test coverage present in source and is not a claim that the suite was executed for this documentation update.

## Limitations

- The system is designed around a UHD-compatible USRP B210.
- The complete 50–6000 MHz range cannot be captured simultaneously and is scanned in steps.
- Displayed power is a reference visualization scale, not calibrated RF dBm.
- Cellular results are frequency/channel candidates, not decoded protocols or confirmed services.
- Only one General or Specific scan owner can use the SDR at a time.
- Sweep behavior depends on UHD, USB transport, host performance, physical RF connections, and backend-defined hardware settings.
- Authentication is intentionally a local/internal administrator model without application-based recovery or multi-role administration; direct editing of `users.password` remains the recovery path.
- Database provisioning and migrations are not automatically completed at normal startup.

## Project Status

The web implementation is functionally complete and includes:

- General and Specific scanning.
- Autonomous rolling sweep and passive device detection.
- Isolated UHD worker with persistent acquisition resources.
- Hann-window FFT and reference display-power processing.
- Independent threshold-point detection and GSM/UMTS/LTE/NR candidate classification.
- Machine/Channel CRUD, lookup, and Specific target measurements.
- Authenticated WebSocket transport with REST fallback.
- Shared Canvas spectrum renderer and responsive web UI.
- Administrator authentication, Change Password, password visibility controls, and safe logout.
- Backend and frontend automated test suites.
