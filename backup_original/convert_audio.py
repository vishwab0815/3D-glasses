
import struct
import os

filename = "mic_recording.raw"

print("File size:", os.path.getsize(filename))

with open(filename, "rb") as f:
    data = f.read()

print("First 32 bytes:", data[:32].hex(" "))

samples = struct.unpack("<" + "i" * (len(data) // 4), data)

print("First 20 raw samples:")
print(samples[:20])

print("Minimum:", min(samples))
print("Maximum:", max(samples))
print("Nonzero samples:", sum(x != 0 for x in samples))
