
import serial
import time
import re

PORT = "COM19"
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=5)
time.sleep(2)
ser.reset_input_buffer()

print("Waiting for ESP32...")
ser.write(b"R")
ser.flush()

wav_size = None

# Wait for recording completion
while True:
    line = ser.readline().decode("ascii", errors="ignore").strip()
    if line:
        print(line)

    match = re.search(r"WAV bytes:\s*(\d+)", line)
    if match:
        wav_size = int(match.group(1))
        break

    if "FAILED" in line:
        ser.close()
        raise SystemExit("ESP32 recording failed")

# IMPORTANT: consume the "Send G to transfer" prompt
while True:
    line = ser.readline().decode("ascii", errors="ignore").strip()
    if line:
        print(line)
    if "Send G to transfer" in line:
        break

print("Sending G...")
ser.write(b"G")
ser.flush()

# Receive exact WAV length
data = bytearray()

while len(data) < wav_size:
    chunk = ser.read(wav_size - len(data))
    if not chunk:
        break
    data.extend(chunk)
    print(f"\rReceived {len(data)}/{wav_size}", end="")

print()
ser.close()

# Validate and save
if len(data) == wav_size and data[:4] == b"RIFF":
    with open("mic_recording.wav", "wb") as f:
        f.write(data)
    print("SUCCESS! mic_recording.wav saved")
else:
    print("Transfer failed")
    print("Bytes received:", len(data))
    print("Header:", data[:12])
