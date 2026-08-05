# USRP B210 Spectrum Monitoring System

## Overview

This project is a web application for monitoring radio spectrum with a USRP B210. The backend acquires IQ samples through UHD, processes the spectrum, detects threshold-exceeding frequency bins, and produces cellular-band classification candidates.

The application provides two scan workflows:

- **General Scan** monitors a user-selected frequency range.
- **Specific Scan** monitors channel targets associated with a selected Machine.

Classification candidates cover GSM, UMTS, LTE, and NR frequency bands. A candidate indicates a frequency-band match; it is not proof that a particular cellular service is active.

## Current features

### Spectrum acquisition

- USRP B210 spectrum monitoring across an approximately 50–6000 MHz supported range.
- Autonomous, continuous rolling stepped sweep over the requested range.
- Persistent UHD scanner worker and persistent RX streamer across sweep hops.
- A 20 MHz sweep window for ranges below 100 MHz and a 56 MHz window for wider ranges.
- 1,024 IQ samples and a 1,024-point FFT for each hop, with a 2 ms tuner-settle delay.
- Hann-window FFT processing and an empirical, reference-style displayed-power conversion.

### Detection and classification

- Threshold-point detection: every FFT bin above the configured threshold remains independently eligible for detection.
- No active clustering, peak grouping, peak merging, or merge-gap processing.
- GSM, UMTS, LTE, and NR candidate classification.
- Current-session detection history and signal details.

### Scan workflows

- General Scan for a user-selected frequency range.
- Specific Scan based on the Channels stored for a selected Machine.
- Per-channel measured power and ON/OFF status in the Specific Scan interface.
- One active scan owner at a time, preventing General and Specific scans from using the SDR concurrently.

### Transport, management, and interface

- Realtime spectrum delivery over WebSocket, with REST snapshot fallback.
- Machine CRUD, Channel CRUD, and channel lookup by supported cellular channel number.
- Passive SDR connection status detection.
- English React user interface with a shared Canvas-based spectrum renderer.

## System architecture

```text
USRP B210
  → UHD scanner worker
  → FastAPI backend
  → committed spectrum state
  → WebSocket stream or REST fallback
  → React frontend
  → shared SpectrumCanvas
```

The backend runs the sweep controller independently of HTTP spectrum reads. Its scanner worker stays available during a scan, and its RX streamer is reused across compatible sweep hops rather than being recreated for each hop. After each committed window, the backend publishes the latest spectrum state to connected WebSocket clients. The frontend uses REST snapshots only when the WebSocket stream is unavailable.

## Technology stack

### Backend

- Python
- FastAPI and Uvicorn
- UHD Python API
- NumPy
- SQLAlchemy and PyMySQL
- python-dotenv

### Frontend

- React
- Vite
- Canvas 2D
- WebSocket

### Database and hardware

- MySQL or MariaDB
- USRP B210 with the RX2 receive input
- USB 3 connection where supported by the deployment

## Project structure

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
│   │   ├── App.jsx
│   │   ├── SpecificChannelPage.jsx
│   │   ├── SpectrumCanvas.jsx
│   │   ├── useSpectrumStream.js
│   │   └── spectrumTransport.js
│   └── package.json
├── requirements.txt
└── README.md
```

## Requirements

- Python 3.12 or another compatible version supported by the dependencies.
- Node.js and npm compatible with the frontend dependencies.
- UHD installation with the UHD Python API available to the backend environment.
- A compatible USRP B210 connected for live acquisition.
- MySQL or MariaDB for Machine and Channel persistence.

## Installation

Clone the repository and enter the project directory.

```powershell
git clone <repository-url>
cd <project-folder>
```

Create a Python environment and install backend dependencies.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install frontend dependencies.

```powershell
cd frontend
npm install
```

## Configuration

The backend loads database configuration from the root `.env` file through `backend/database.py`. Create that file locally and keep it out of version control. The supported settings are `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`.

Equivalent database URL format:

```text
mysql+pymysql://<database-user>:<database-password>@<host>:<port>/<database-name>
```

Use database values appropriate to the local deployment. Do not place credentials, private hosts, or device identifiers in documentation or tracked configuration.

## Running the application

From the project root, start the FastAPI backend:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The backend is then available at `http://127.0.0.1:8000`, and FastAPI interactive documentation is available at `http://127.0.0.1:8000/docs`.

In a separate terminal, start the Vite frontend:

```powershell
cd frontend
npm run dev
```

Vite serves the development interface at the local address displayed in its terminal output; the backend CORS configuration permits `http://localhost:5173` and `http://127.0.0.1:5173`.

## Main API and transport

Important active interfaces include:

- `POST /api/scan/start` — starts a General or Specific scan. The request includes a threshold, start frequency, end frequency, scan owner, and, for Specific Scan, a selected Machine ID.
- `POST /api/scan/stop` — stops the active scan for its owner.
- `GET /api/status` — returns scan state and rolling-sweep progress.
- `GET /api/scan/results` — returns current-session detections, channel measurements, and spectrum preview data.
- `GET /api/spectrum` — returns a read-only snapshot of the latest committed spectrum window; used as the frontend fallback transport.
- `GET /api/device/status` — returns passive SDR connection and scan-ownership status.
- `GET`, `POST /api/machines` and `GET`, `PUT`, `DELETE /api/machines/{machine_id}` — Machine CRUD.
- `GET`, `POST /api/machines/{machine_id}/channels` and `GET`, `PUT`, `DELETE /api/channels/{channel_id}` — Channel CRUD.
- `GET /api/channel-lookup` — resolves supported technology/profile and FCN inputs into channel candidates.
- `WS /api/spectrum/stream` — primary realtime spectrum transport.

## Scan behavior

The application divides a requested range into stepped windows and continuously repeats the sweep until it is stopped. Ranges below 100 MHz use the 20 MHz policy; wider ranges use the 56 MHz policy. Each hop acquires 1,024 IQ samples, applies a Hann window, and computes a 1,024-point FFT.

The displayed spectrum uses an empirical reference-style power scale. It is suitable for the application display and threshold workflow, but it is not presented as calibrated laboratory dBm.

For each hop, every FFT bin above the threshold is independently eligible for detection and classification. General Scan reports detections across its requested range. Specific Scan uses the selected Machine's stored Channel targets and returns measured power plus ON/OFF status for those channels. Both workflows expose the latest current-session spectrum preview through the same persistent worker, streamer, and shared frontend canvas.

## Limitations

- Wide frequency ranges require a stepped sweep because instantaneous bandwidth is limited.
- Tuning performance depends on UHD and USRP hardware behavior.
- Displayed power is reference-style and is not guaranteed to be calibrated laboratory dBm.
- Live acquisition requires a compatible UHD installation and connected USRP hardware.

## Current development status

The following work has been implemented and validated:

- Autonomous rolling sweep.
- Persistent RX streamer.
- Faster spectrum scanning.
- Shared Canvas renderer.
- Realtime WebSocket transport.
- REST fallback.
- General and Specific spectrum status UI cleanup.
- Obsolete Scan History and dead-code cleanup.

## Planned work

The following items are planned and are not currently implemented:

- User login and authentication.
- Improved responsive layout for Android and mobile portrait screens.
- Mobile top-bar and navigation optimization.

## Safety and privacy

- Credentials must not be committed.
- Personal information and local paths must not be added to public documentation.
- Use environment variables for sensitive configuration where the application supports them.
- Do not publish device serial numbers or private network details.
