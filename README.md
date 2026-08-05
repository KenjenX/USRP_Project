# USRP B210 Spectrum Monitoring System

## Overview

This project is a web-based spectrum monitoring system built for the USRP B210. The backend acquires IQ samples through UHD, processes them with FFT, detects frequency bins above a configurable threshold, and maps detected frequencies to GSM, UMTS, LTE, and NR band candidates.

The application provides two scan modes:

- **General Scan** monitors a user-defined frequency range.
- **Specific Scan** monitors the channel targets stored for a selected Machine.

A classification candidate indicates that a detected frequency matches a known cellular band or channel range. It does not confirm that a particular cellular service is active.

## Main Features

### Spectrum acquisition

- Frequency scanning from 50 MHz to 6000 MHz.
- Continuous rolling stepped sweep until the active scan is stopped.
- Separate UHD worker process for SDR access.
- RX streamer reuse across compatible sweep hops during a scan.
- 20 MHz sweep policy for spans below 100 MHz.
- 56 MHz sweep policy for wider spans.
- 1,024 IQ samples and a 1,024-point FFT per hop.
- Hann-window FFT processing.
- 2 ms tuner-settle delay after each frequency change.

### Detection and classification

- Configurable threshold in the displayed power scale.
- Every FFT bin above the threshold remains independently eligible for detection.
- No active clustering, peak grouping, peak merging, or merge-gap processing.
- GSM, UMTS, LTE, and NR frequency-band classification.
- Current-session detection history and spectrum details.

### Scan modes

- General Scan for a user-defined frequency range.
- Specific Scan for channel targets associated with a selected Machine.
- Per-channel measured power and ON/OFF status in Specific Scan.
- Isolation between General and Specific results.
- One active scan owner at a time to prevent concurrent SDR access.

### Data management and interface

- Machine CRUD.
- Channel CRUD.
- Channel lookup using supported technology, profile, and channel-number inputs.
- Passive USRP connection-status detection.
- Realtime spectrum transport over WebSocket.
- REST spectrum snapshot fallback when the WebSocket connection is unavailable.
- Shared Canvas-based spectrum renderer for General and Specific Scan.

## System Architecture

```text
USRP B210
  -> UHD worker process
  -> FastAPI scan controller and committed spectrum state
  -> WebSocket stream or REST snapshot fallback
  -> React frontend
  -> shared SpectrumCanvas renderer
```

The backend controls the rolling sweep independently of frontend polling. During an active scan, the UHD worker remains available across sweep hops and reuses the RX streamer while the sample-rate configuration remains compatible.

After each completed window, the backend commits the latest spectrum state. Connected clients receive that state through WebSocket, while REST snapshots remain available as a fallback transport.

## Technology Stack

### Backend

- Python
- FastAPI
- Uvicorn
- UHD Python API
- NumPy
- Pydantic
- SQLAlchemy
- PyMySQL
- python-dotenv

### Frontend

- React
- React DOM
- Vite
- CSS
- Canvas 2D
- WebSocket

### Database and hardware

- MySQL-compatible database through PyMySQL
- USRP B210
- RX channel 0
- RX2 antenna input
- USB 3 connection recommended for deployment

## Project Structure

```text
.
├── backend/
│   ├── main.py
│   ├── scanner_worker.py
│   ├── spectrum_stream.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── machine_routes.py
│   ├── channel_routes.py
│   ├── channel_lookup_routes.py
│   └── *_classifier.py
├── frontend/
│   ├── src/
│   │   ├── main.jsx
│   │   ├── App.jsx
│   │   ├── SpecificChannelPage.jsx
│   │   ├── SpectrumCanvas.jsx
│   │   ├── useSpectrumStream.js
│   │   └── spectrumTransport.js
│   ├── test/
│   └── package.json
├── tests/
├── requirements.txt
└── README.md
```

## Requirements

- Python and the packages listed in `requirements.txt`.
- Node.js and npm.
- UHD with the UHD Python API available in the backend environment.
- A connected USRP B210 for live spectrum acquisition.
- A MySQL-compatible database accessible through PyMySQL.

## Installation

Clone the repository and enter the project directory:

```powershell
git clone <repository-url>
cd <project-folder>
```

Create and activate a Python virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install the frontend dependencies:

```powershell
cd frontend
npm install
```

## Database Configuration

The backend reads database settings from a root `.env` file through `backend/database.py`.

Create the file locally with the following variables:

```text
DB_HOST=<database-host>
DB_PORT=<database-port>
DB_NAME=<database-name>
DB_USER=<database-user>
DB_PASSWORD=<database-password>
```

Equivalent connection format:

```text
mysql+pymysql://<database-user>:<database-password>@<database-host>:<database-port>/<database-name>
```

Keep the `.env` file local and do not commit database credentials.

The application does not currently provide an automatic database migration workflow at startup. Required tables must already be available before using Machine and Channel features.

## Running the Application

Start the backend from the project root:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The backend is available at:

```text
http://127.0.0.1:8000
```

FastAPI interactive documentation is available at:

```text
http://127.0.0.1:8000/docs
```

Start the frontend in a separate terminal:

```powershell
cd frontend
npm run dev
```

The development frontend normally runs on port `5173`. The backend allows the following local origins:

```text
http://localhost:5173
http://127.0.0.1:5173
```

## Main API and Transport

| Method | Interface | Purpose |
|---|---|---|
| `GET` | `/` | Basic API and device information |
| `GET` | `/api/device/status` | Passive SDR connection status |
| `GET` | `/api/device` | Compatibility alias for device status |
| `GET` | `/api/status` | Scan state and rolling-sweep progress |
| `POST` | `/api/scan/start` | Start a General or Specific Scan |
| `POST` | `/api/scan/stop` | Stop the active scan for its owner |
| `GET` | `/api/scan/results` | Current-session detections, channel measurements, and preview data |
| `GET` | `/api/spectrum` | Latest committed spectrum snapshot |
| `WS` | `/api/spectrum/stream` | Primary realtime spectrum transport |
| `GET`, `POST` | `/api/machines` | List or create Machines |
| `GET`, `PUT`, `DELETE` | `/api/machines/{machine_id}` | Read, update, or delete a Machine |
| `GET`, `POST` | `/api/machines/{machine_id}/channels` | List or create Channels for a Machine |
| `GET`, `PUT`, `DELETE` | `/api/channels/{channel_id}` | Read, update, or delete a Channel |
| `GET` | `/api/channel-lookup` | Resolve supported channel candidates |

## Scan Behavior

The backend divides the requested frequency range into stepped windows and repeats the sweep until the scan is stopped.

- Spans below 100 MHz use the 20 MHz sweep policy.
- Wider spans use the 56 MHz sweep policy.
- Each hop acquires 1,024 IQ samples.
- A Hann window is applied before the 1,024-point FFT.
- The tuner waits 2 ms after changing center frequency.
- The FFT output is shifted into frequency order before display and detection.

The displayed power uses an empirical reference-style conversion intended for visualization and threshold-based monitoring. It must not be interpreted as calibrated laboratory dBm.

Every FFT bin above the configured threshold remains independently eligible for detection and classification.

### General Scan

General Scan accepts a user-defined frequency range and reports detections across that range.

### Specific Scan

Specific Scan uses the Channels stored for the selected Machine as measurement targets. It reports measured power and ON/OFF status for each target while keeping the result isolated from General Scan data and from other Machines.

## Automated Tests

Python regression tests include:

```text
backend/test_spectrum_stream.py
backend/test_spectrum_stream_endpoint.py
tests/test_autonomous_lifecycle.py
tests/test_reference_fast_scan.py
tests/test_reference_power_scale.py
```

Frontend regression tests include:

```text
frontend/test/generalSpectrumPreview.test.mjs
frontend/test/spectrumCanvasLayout.test.mjs
frontend/test/spectrumChartScale.test.mjs
frontend/test/spectrumTransport.test.mjs
```

The Python tests use `unittest` and mocking so that most regression checks do not require connected SDR hardware. The frontend tests use Node's built-in `node:test` module.

## Technical Limitations

- The full 50–6000 MHz range cannot be captured instantaneously and must be scanned in stepped windows.
- Scan startup depends on the passive USB detector reporting that the USRP is connected.
- Only one General or Specific scan owner can use the SDR at a time.
- Sweep and tuning performance depend on UHD, USB throughput, and USRP hardware behavior.
- Displayed power is an empirical visualization scale, not calibrated laboratory dBm.
- The frontend API address currently targets the local backend at `127.0.0.1:8000`.
- User authentication is not implemented.
- Automatic database migration is not currently performed at application startup.

## Current Development Status

Implemented and validated features include:

- General and Specific Scan.
- Autonomous continuous rolling sweep.
- Separate UHD worker process.
- Persistent RX streamer across compatible sweep hops.
- Hann-window FFT processing.
- Threshold-point detection without clustering.
- GSM, UMTS, LTE, and NR classification.
- Machine and Channel management.
- Per-channel measurement and status reporting.
- Realtime WebSocket spectrum transport.
- REST fallback transport.
- Shared Canvas spectrum renderer.
- Passive USRP connection detection.
- Automated backend and frontend regression tests.

## Planned Work

- User login and authentication.
- Improved responsive layout for Android and mobile portrait screens.
- Mobile top-bar and navigation optimization.
