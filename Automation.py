import pyvisa
import time
import numpy as np
import pandas as pd
import datetime
import os

#User Configuration
Rails={
    "+3V6": {"nominal": 3.6, "max_current": 2.5},
    "+1V8": {"nominal": 1.8, "max_current": 3.0},
    "+3V3": {"nominal": 3.3, "max_current": 3.0},
    "+2V5": {"nominal": 2.5, "max_current": 1.5},
}
CAPTURE_COUNT = 5   #5 times the oscilloscope will capture the waveform
DATA_FOLDER = "Transient_Data_TestReport"
os.makedirs(DATA_FOLDER, exist_ok=True)

#Visa Initialization
rm = pyvisa.ResourceManager()

psu = rm.open_resource("USB0::0x05E6::0x2230::PSU123::INSTR")       # Keithley 2230
eload = rm.open_resource("USB0::0x05E6::0x2380::LOAD123::INSTR")    # Keithley 2380
scope = rm.open_resource("USB0::0x0957::0x17A6::SCOPE123::INSTR")   # Keysight DSOX6004A
dmm = rm.open_resource("USB0::0x05E6::0x6500::DMM123::INSTR")       # Keithley DMM6500

for inst in [psu, eload, scope, dmm]:
    try:
        inst.timeout = 10000
        idn = inst.query("*IDN?")
        print("Connected:", idn)
    except Exception as e:
        print("Connection failed:", e)

# Initializing the functions

def initialize_psu():
    psu.write("*RST")
    psu.write("VOLT 5")
    psu.write("CURR 5")
    psu.write("OUTP ON")

def initialize_eload(max_current):
    eload.write("*RST")
    eload.write("MODE TRAN")
    eload.write(f"CURR:LOW {0.5 * max_current}")
    time.sleep(0.01) #waits 10ms
    eload.write(f"CURR:HIGH {max_current}")
    eload.write("TRAN:TIM 0.005")  #current switches every 5ms
    eload.write("INPUT ON")

def initialize_scope():
    scope.write("*RST")
    scope.write("CHAN1:DISP ON")
    scope.write("TIM:SCAL 200E-6")
    scope.write("TRIG:EDGE:SOUR CHAN1")
    scope.write("ACQ:TYPE NORM")

def measure_dc_voltage():
    dmm.write("CONF:VOLT:DC")
    voltage = float(dmm.query("READ?"))
    return voltage

# WAVEFORM CAPTURE
def capture_waveform():
    scope.write("DIGITIZE")
    time.sleep(0.5)
    scope.write("WAV:FORM ASCII")
    raw = scope.query("WAV:DATA?")
    data = np.array(raw.split(','), dtype=float)
    return data


# ANALYSIS
def analyze_transient(data, time_axis, nominal):
    # Calculate tolerance band (±5%)
    voltage_low = nominal * 0.95
    voltage_high = nominal * 1.05

    # Find minimum and maximum voltage
    min_v = np.min(data)
    max_v = np.max(data)

    # Calculate deviations
    undershoot = nominal - min_v
    overshoot = max_v - nominal

    # Find first index where voltage goes outside tolerance
    out_of_band = np.where((data < voltage_low) | (data > voltage_high))[0]

    if len(out_of_band) == 0:
        recovery_time = 0
    else:
        first_event_index = out_of_band[0]

        # Find when voltage comes back within tolerance
        recovery_indices = np.where(
            (data[first_event_index:] >= voltage_low) &
            (data[first_event_index:] <= voltage_high)
        )[0]

        if len(recovery_indices) == 0:
            recovery_time = float("inf")
        else:
            recovery_index = first_event_index + recovery_indices[0]
            recovery_time = time_axis[recovery_index] - time_axis[first_event_index]

        # PASS/FAIL Criteria
    result = "PASS"

    if undershoot > 0.05 * nominal:
        result = "FAIL"

    if overshoot > 0.05 * nominal:
        result = "FAIL"

    if recovery_time > 500e-6:  # 500 microseconds limit
        result = "FAIL"

    return undershoot, overshoot, recovery_time, result


# MAIN TEST LOOP
def run_test():

    results = []

    initialize_psu()
    initialize_scope()

    for rail, params in RAILS.items():

        nominal = params["nominal"]
        max_current = params["max_current"]

        print(f"\nTesting Rail {rail}")

        initialize_eload(max_current)

        dc_voltage = measure_dc_voltage()

        dc_result = "PASS"
        if not (nominal * 0.95 <= dc_voltage <= nominal * 1.05):#3.135<=dc voltage<=3.465
            dc_result = "FAIL"

        for i in range(CAPTURE_COUNT):

            data = capture_waveform()

            undershoot, overshoot, recovery, transient_result = analyze_transient(data, time_axis, nominal)

            timestamp = datetime.datetime.now()

            filename =  f"{DATA_FOLDER}/{rail}_capture{i}_{timestamp}.csv"
            np.savetxt(filename, data, delimiter=",")

            final_result = "PASS"
            if dc_result == "FAIL" or transient_result == "FAIL":
                final_result = "FAIL"

            results.append([
                timestamp,
                rail,
                dc_voltage,
                undershoot,
                overshoot,
                final_result
            ])

    return results


# SAVE CSV & REPORT
def save_and_report(results):

    df = pd.DataFrame(results, columns=[
        "Timestamp",
        "Rail",
        "DC Voltage (V)",
        "Undershoot (V)",
        "Overshoot (V)",
        "Result"
    ])

    csv_file = f"{DATA_FOLDER}/Final_Result.csv"
    df.to_csv(csv_file, index=False)

    stats = df.groupby("Rail").agg(["mean", "max", "min"])

    report_file = f"{DATA_FOLDER}.txt"

    with open(report_file, "w") as f:
        f.write("PRODUCTION LOAD TRANSIENT TEST REPORT\n")
        f.write("====================================\n")
        f.write("Summary Statistics:\n")
        f.write(str(stats))

    return csv_file, report_file


# EXECUTION
if __name__ == "__main__":

    test_results = run_test()
    csv_file, report_file = save_and_report(test_results)
    print("\nTest Completed")
    print("CSV saved at:", csv_file)
    print("Report saved at:", report_file)