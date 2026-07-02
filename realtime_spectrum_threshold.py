import uhd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import json
from datetime import datetime

center_freq = 100e6
sample_rate = 2e6
gain = 35
num_samps = 4096
channel = 0
threshold_db = 0   # ubah nilai threshold di sini

usrp = uhd.usrp.MultiUSRP()
usrp.set_rx_antenna("RX2", channel)

freq_axis = np.fft.fftshift(np.fft.fftfreq(num_samps, d=1 / sample_rate))
freq_axis = (freq_axis + center_freq) / 1e6

fig, ax = plt.subplots()
line, = ax.plot(freq_axis, np.zeros(num_samps))
threshold_line = ax.axhline(threshold_db, linestyle="--", label="Threshold")
status_text = ax.text(0.02, 0.95, "STATUS: NORMAL", transform=ax.transAxes)

ax.set_title("USRP B210 Realtime Spectrum with Threshold - RX2A")
ax.set_xlabel("Frequency (MHz)")
ax.set_ylabel("Power (dB)")
ax.grid(True)
ax.set_ylim(-80, 10)
ax.legend()

LOG_FILE = "signal_log.json"

def save_warning_log(peak_freq, peak_power):
    event = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "peak_freq_mhz": float(peak_freq),
        "peak_power_db": float(peak_power),
        "threshold_db": float(threshold_db),
        "center_freq_mhz": float(center_freq / 1e6),
        "sample_rate_mhz": float(sample_rate / 1e6),
    }

    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []

    logs.append(event)

    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=4)

def update(frame):
    samples = usrp.recv_num_samps(
        num_samps,
        center_freq,
        sample_rate,
        [channel],
        gain
    )

    iq = samples[0]
    fft_data = np.fft.fftshift(np.fft.fft(iq * np.hanning(len(iq))))
    power = 20 * np.log10(np.abs(fft_data) + 1e-12)

    peak_index = np.argmax(power)
    peak_power = power[peak_index]
    peak_freq = freq_axis[peak_index]

    line.set_ydata(power)

    if peak_power > threshold_db:
        status_text.set_text(f"WARNING: {peak_freq:.6f} MHz | {peak_power:.2f} dB")
        save_warning_log(peak_freq, peak_power)
    else:
        status_text.set_text(f"NORMAL | Peak: {peak_freq:.6f} MHz | {peak_power:.2f} dB")

    return line, status_text

ani = FuncAnimation(fig, update, interval=200, blit=False)
plt.show()

