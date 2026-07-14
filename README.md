# USRP B210 Spectrum Scanner

A web-based real-time spectrum scanning tool for USRP B210.  
This project uses a FastAPI backend to communicate with the USRP device and a React frontend to display spectrum data, threshold detections, and wireless technology classification results.

## Features

- USRP B210 spectrum scanning
- Frequency range support from 50 MHz to 6000 MHz
- Sweep scan mode using smaller scan windows
- Threshold-based detection
- Detection of every FFT point above the threshold
- 2G GSM candidate classification
- 3G UMTS/WCDMA candidate classification
- 4G LTE candidate classification
- 5G NR candidate classification
- Current Scan History
- Scan session history
- Signal detail modal
- Accordion detail view for 2G, 3G, 4G, and 5G candidates
- ARFCN, UARFCN, EARFCN, and NR-ARFCN details
- Downlink, uplink, and TDD side information when available

## Project Structure

```text
USRP_Project/
├── backend/
│   ├── main.py
│   ├── gsm_classifier.py
│   ├── umts_classifier.py
│   ├── lte_classifier.py
│   └── nr_classifier.py
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   └── App.css
│   ├── package.json
│   └── index.html
│
└── README.md
```

## Technology Stack

### Backend

- Python
- FastAPI
- UHD Python API
- NumPy
- Pydantic
- Uvicorn

### Frontend

- React
- Vite
- JavaScript
- CSS

### Hardware

- USRP B210
- RX antenna input
- USB 3.0 connection recommended

## System Overview

```text
USRP B210
   ↓
UHD Python API
   ↓
FastAPI Backend
   ↓
FFT Processing
   ↓
Threshold Detection
   ↓
2G / 3G / 4G / 5G Classification
   ↓
React Frontend
   ↓
Spectrum Chart + Scan History + Detail Modal
```

## Scan Concept

The USRP B210 cannot scan the entire 50 MHz to 6000 MHz range in one single FFT window.  
To solve this, the backend performs a sweep scan.

Example:

```text
Requested range: 50 MHz – 6000 MHz
Sweep window   : 56 MHz

Scan flow:
50–106 MHz
106–162 MHz
162–218 MHz
...
until 6000 MHz
```

Each sweep window is scanned one by one.  
Every FFT point that is equal to or above the threshold is counted as a detection.

## Detection Concept

The system uses threshold point detection.

```text
If power_db >= threshold_db
→ the frequency point is detected
→ the point is classified
→ the result is added to Current Scan History
```

This means the system does not only take the strongest peak.  
All FFT points above the threshold are processed.

## Classification

Detected frequencies are checked against wireless technology frequency bands.

Supported candidate classifications:

- 2G GSM
- 3G UMTS / WCDMA
- 4G LTE
- 5G NR

The result is a candidate-based classification.  
A frequency can match more than one technology or band depending on the frequency range.

Example:

```text
Detected frequency: 792.875 MHz

Possible candidates:
- LTE Band 14 as UL
- LTE Band 20 as DL
```

## Current Scan History

During a scan, detected threshold points are displayed in Current Scan History.

The history is sorted from lower frequency to higher frequency.

Example:

```text
50 MHz
...
900 MHz
...
1800 MHz
...
3500 MHz
...
6000 MHz
```

## Scan History

After one sweep scan is completed, the result is saved as a scan session in the frontend.

Each scan session contains:

- Scan range
- Threshold value
- Total detected points
- Scan result list
- Candidate technology details

Note: the current scan history is stored in the frontend state.  
Refreshing the browser will clear the frontend history unless persistent storage is added later.

## Signal Detail Modal

Each detected row can be clicked to open a detail modal.

The detail modal displays:

- Detected frequency
- Power
- Threshold
- Window range
- FFT index
- Window index
- Technology candidates
- ARFCN / UARFCN / EARFCN / NR-ARFCN
- Frequency DL / UL information
- Detected side such as DL, UL, or TDD

The candidate details are grouped using accordion sections:

- 2G
- 3G
- 4G
- 5G

All sections are closed by default and can be opened manually.

## Backend Setup

Create and activate a Python virtual environment.

```powershell
cd <project-folder>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies.

```powershell
pip install fastapi uvicorn numpy pydantic
```

Install UHD and make sure the UHD Python API is available in the environment.

Run the backend server.

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Backend URL:

```text
http://127.0.0.1:8000
```

API documentation:

```text
http://127.0.0.1:8000/docs
```

## Frontend Setup

Install frontend dependencies.

```powershell
cd <project-folder>/frontend
npm install
```

Run the frontend development server.

```powershell
npm run dev
```

Frontend URL:

```text
http://localhost:5173
```

## Main API Endpoints

### Device Status

```text
GET /api/device
```

Checks whether the USRP device is accessible.

### Start Scan

```text
POST /api/scan/start
```

Starts a sweep scan.

Example request:

```json
{
  "threshold_db": 0,
  "start_frequency_mhz": 50,
  "end_frequency_mhz": 6000
}
```

### Stop Scan

```text
POST /api/scan/stop
```

Stops the current scan.

### Spectrum Data

```text
GET /api/spectrum
```

Reads one sweep window and returns spectrum data, peak data, and threshold detections.

### Scan Results

```text
GET /api/scan/results
```

Returns cumulative detection results from the current scan.

### Scan Status

```text
GET /api/status
```

Returns the current scan status and sweep progress.

## Important Notes

- The 50–6000 MHz scan is performed using sweep windows.
- The backend does not force the USRP to read the entire range in one sample rate.
- Detection is based on FFT points above the threshold.
- Classification results are candidates, not final proof of the active technology.
- The displayed DL/UL pair depends on the detected side and band type.
- FDD bands have separate DL and UL frequencies.
- TDD bands share the same frequency for DL and UL using time separation.

## Privacy and Security Notes

Do not commit sensitive data to the repository.

Avoid committing:

```text
.env
API keys
passwords
tokens
device serial numbers
personal folder paths
personal usernames
```

Recommended `.gitignore` entries:

```gitignore
.env
.env.local
*.env
.venv/
node_modules/
```

## Future Improvements

Possible next improvements:

- Export scan results to CSV or JSON
- Persistent scan history storage
- SQLite database support
- Search and filter scan history
- Technology-specific filtering
- Better signal grouping or summary view
- Improved scan performance for large frequency ranges
- Optional continuous monitoring mode