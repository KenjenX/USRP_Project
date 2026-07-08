# USRP B210 Realtime Spectrum Scanner

A web-based frequency spectrum monitoring system using **USRP B210**.  
This project receives signal data from the USRP, processes it with FFT, displays a realtime spectrum chart in the browser, detects frequencies that pass a threshold, and classifies them as GSM band candidates.

---

## Main Features

- Realtime spectrum monitoring from USRP B210.
- Frequency vs power chart in dB.
- Adjustable threshold line for signal detection.
- Multiple signal detection based on threshold.
- Simple threshold cluster system:
  - consecutive FFT points above the threshold are treated as one cluster;
  - if a point drops below the threshold, the cluster is split;
  - each cluster uses its highest peak for band classification.
- GSM candidate classification based on downlink frequency.
- React-based frontend.
- FastAPI-based backend.

---

## Technologies Used

### Hardware

- USRP B210
- RX2 antenna

### Backend

- Python
- FastAPI
- UHD Python API
- NumPy
- Uvicorn

### Frontend

- React
- Vite
- JavaScript
- CSS
- Custom SVG chart

---

## System Flow

```text
USRP B210
→ IQ sample
→ FFT
→ Power spectrum in dB
→ FastAPI backend
→ JSON API
→ React frontend
→ Realtime spectrum chart
→ Threshold cluster detection
→ GSM classification
```

---

## Project Structure

```text
USRP_Project/
├── backend/
│   ├── main.py
│   ├── gsm_classifier.py
│   └── gsm_band_registry.py
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── App.css
│   │   └── ...
│   ├── package.json
│   └── vite.config.js
│
└── README.md
```

---

## Running the Backend

Open a terminal in the project folder:

```powershell
cd C:\Users\Deltra\Documents\Magang\USRP_Project
```

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run the backend server:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Backend URL:

```text
http://127.0.0.1:8000
```

Swagger API documentation:

```text
http://127.0.0.1:8000/docs
```

---

## Running the Frontend

Open a new terminal:

```powershell
cd C:\Users\Deltra\Documents\Magang\USRP_Project\frontend
```

Install dependencies if needed:

```powershell
npm install
```

Run the frontend development server:

```powershell
npm run dev
```

Frontend URL:

```text
http://localhost:5173
```

---

## Main API Endpoints

### Check Device

```text
GET /api/device
```

Checks the USRP connection status.

### Check Scan Status

```text
GET /api/status
```

Returns the current scan status.

### Start Scan

```text
POST /api/scan/start
```

Starts spectrum scanning based on the selected frequency range and threshold.

### Stop Scan

```text
POST /api/scan/stop
```

Stops the scanning process.

### Get Spectrum

```text
GET /api/spectrum
```

Returns realtime spectrum data, peak information, cluster detection results, and GSM classification results.

---

## Threshold and Cluster Concept

The detection system uses the threshold as the main detection boundary.

Example:

```text
50–70 MHz    above threshold → Cluster 1
71–75 MHz    below threshold → cluster split
76–100 MHz   above threshold → Cluster 2
```

From each cluster, the system selects the point with the highest power.

```text
Cluster
→ find the highest peak
→ classify GSM based on the peak frequency
```

If the threshold is too low, for example `-100 dB`, almost all FFT points may be above the threshold.  
As a result, the whole frequency range can become one large cluster.

If the threshold is increased, the system will only detect areas that actually pass the threshold.

---

## Important Notes

- Do not run the old Matplotlib script and the FastAPI backend at the same time, because both may try to access the USRP device simultaneously.
- The frontend chart displays the actual FFT data used by the backend for threshold and cluster detection.
- GSM classification is currently based on downlink frequency candidates. It does not prove that the detected signal is truly GSM.
- Future development may include UMTS, LTE, and 5G NR classification.

---

## Development Branch

The main development branch for threshold and multi-detection features is:

```text
threshold-multi-detection
```

This branch includes:

- actual FFT spectrum display;
- simple threshold cluster detection;
- multiple signal detection;
- GSM classification;
- cluster and detected peak indicators in the frontend.

---

## Project Status

This project is still under development and testing.  
The current focus is to make sure the threshold, clustering, and band classification system works properly for spectrum monitoring using USRP B210.
