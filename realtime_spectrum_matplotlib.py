import uhd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation


center_freq = 100e6
sample_rate = 1e6
gain = 40
num_samps = 4096
channel = 0

usrp = uhd.usrp.MultiUSRP()
usrp.set_rx_antenna("RX2", channel)

freq_axis = np.fft.fftshift(np.fft.fftfreq(num_samps, d=1 / sample_rate))
freq_axis = (freq_axis + center_freq) / 1e6

fig, ax = plt.subplots()
line, = ax.plot(freq_axis, np.zeros(num_samps))

ax.set_title("USRP B210 Realtime Spectrum - RX2A")
ax.set_xlabel("Frequency (MHz)")
ax.set_ylabel("Power (dB)")
ax.grid(True)
ax.set_ylim(-80, 10)

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

    line.set_ydata(power)
    return line,

ani = FuncAnimation(fig, update, interval=200, blit=True)
plt.show()