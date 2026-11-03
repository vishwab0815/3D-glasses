
import os
import requests
from pathlib import Path

# ==============================
# CONFIGURATION
# ==============================

API_KEY = os.getenv("GROQ_API_KEY")
BASE = "https://api.groq.com/openai/v1"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}"
}

AUDIO_FILE = Path("mic_recording.wav")

# ==============================
# CHECKS
# ==============================

if not API_KEY:
    raise SystemExit("Missing GROQ_API_KEY")

if not AUDIO_FILE.exists():
    raise SystemExit(
        f"mic_recording.wav not found in: {Path.cwd()}"
    )

# ==============================
# 1. SPEECH TO TEXT
# ==============================

print("\n1. Transcribing your voice...")

with AUDIO_FILE.open("rb") as f:
    r = requests.post(
        f"{BASE}/audio/transcriptions",
        headers=HEADERS,
        files={
            "file": (
                "mic_recording.wav",
                f,
                "audio/wav"
            )
        },
        data={
            "model": "whisper-large-v3-turbo",
            "language": "en",
            "response_format": "json"
        },
        timeout=120
    )

if not r.ok:
    print("STT ERROR:", r.status_code, r.text)
    raise SystemExit("Transcription failed")

transcript = r.json().get("text", "").strip()

print("YOU SAID:", transcript)

if not transcript:
    raise SystemExit("No speech recognized. Record again.")

# ==============================
# 2. AI CHAT
# ==============================

print("\n2. Asking Groq AI...")

r = requests.post(
    f"{BASE}/chat/completions",
    headers={
        **HEADERS,
        "Content-Type": "application/json"
    },
    json={
        "model": "openai/gpt-oss-20b",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a friendly voice assistant. "
                    "Reply naturally and briefly, "
                    "in one or two sentences. "
                    "If asked about live weather, "
                    "explain that you need weather data."
                )
            },
            {
                "role": "user",
                "content": transcript
            }
        ],
        "max_completion_tokens": 300
    },
    timeout=120
)

if not r.ok:
    print("CHAT ERROR:", r.status_code, r.text)
    raise SystemExit("Chat request failed")

data = r.json()

# Diagnostics
choices = data.get("choices", [])

if not choices:
    print("Full API response:", data)
    raise SystemExit("No choices returned by Groq.")

choice = choices[0]
message = choice.get("message") or {}

print("Finish reason:", choice.get("finish_reason"))
print("Usage:", data.get("usage"))
print("Raw assistant message:", message)

reply = message.get("content")

# Handle unexpected content format
if isinstance(reply, list):
    reply = " ".join(
        item.get("text", "")
        for item in reply
        if isinstance(item, dict)
    )

if not isinstance(reply, str) or not reply.strip():
    print("\nFull API response:", data)
    raise SystemExit(
        "No text reply. Check diagnostics above."
    )

reply = reply.strip()

print("\nASSISTANT:", reply)

# ==============================
# 3. TEXT TO SPEECH
# ==============================

print("\n3. Generating assistant voice...")

# Orpheus input limit: 200 characters
spoken_text = reply[:200]

tts_payload = {
    "model": "canopylabs/orpheus-v1-english",
    "voice": "austin",
    "input": spoken_text,
    "response_format": "wav"
}

r = requests.post(
    f"{BASE}/audio/speech",
    headers={
        **HEADERS,
        "Content-Type": "application/json"
    },
    json=tts_payload,
    timeout=120
)

if not r.ok:
    print("\nTTS ERROR STATUS:", r.status_code)
    print("TTS ERROR DETAILS:", r.text)
    raise SystemExit("TTS request failed")

# Validate WAV response
if not r.content.startswith(b"RIFF"):
    print(
        "Content type:",
        r.headers.get("Content-Type")
    )
    print("Response preview:", r.content[:300])
    raise SystemExit("Response is not a WAV file.")

out = Path("assistant_reply.wav")
out.write_bytes(r.content)

print("\nSUCCESS!")
print("Saved:", out.resolve())
print("Audio bytes:", len(r.content))
print("Open assistant_reply.wav to hear your assistant.")
