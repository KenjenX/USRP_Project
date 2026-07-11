import uhd

USRP_SERIAL = "000000929"
CHANNEL = 0
GAIN_DB = 35
NUM_SAMPS = 4096
SAMPLE_RATE_HZ = 2e6

test_frequencies_mhz = [
    10,
    49,
    50,
    937,
    6000,
    5500,
]

usrp = uhd.usrp.MultiUSRP(f"serial={USRP_SERIAL}")
usrp.set_rx_antenna("RX2", CHANNEL)

for freq_mhz in test_frequencies_mhz:
    print("=" * 50)
    print(f"REQUEST FREQUENCY : {freq_mhz} MHz")

    try:
        samples = usrp.recv_num_samps(
            NUM_SAMPS,
            freq_mhz * 1e6,
            SAMPLE_RATE_HZ,
            [CHANNEL],
            GAIN_DB,
        )

        try:
            actual_freq_mhz = usrp.get_rx_freq(CHANNEL) / 1e6
            print(f"ACTUAL RX FREQUENCY REPORTED BY UHD : {actual_freq_mhz} MHz")
        except Exception as read_error:
            print(f"Cannot read actual RX frequency: {read_error}")

        print(f"SAMPLES RECEIVED : {len(samples[0])}")

    except Exception as error:
        print(f"ERROR : {error}")