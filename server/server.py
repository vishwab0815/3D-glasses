"""
Voice assistant server (runs on the laptop).

ESP32 --(WAV)--> /ask --> Groq STT --> Groq chat --> Groq TTS --(WAV)--> ESP32

Also answers UDP discovery broadcasts so the ESP32 finds this laptop
automatically, whatever its IP address is.

Run:  python server/server.py
"""

import os
import re
import socket
import struct
import sys
import threading
import time
import unicodedata
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request

# Windows consoles/redirects may not be UTF-8; never crash on printing.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"


class Tee:
    """Print to the console and also append to server/server.log."""

    def __init__(self, stream, path):
        self.stream = stream
        self.file = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, text):
        self.stream.write(text)
        self.stream.flush()
        self.file.write(text)
        return len(text)

    def flush(self):
        self.stream.flush()
        self.file.flush()

    def __getattr__(self, name):  # isatty, encoding, ... from the console
        return getattr(self.stream, name)


sys.stdout = Tee(sys.stdout, HERE / "server.log")


# ==========================================
# CONFIGURATION (.env file or environment)
# ==========================================
def load_env_file():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def ask_for_key():
    """First run: ask for the Groq key and keep it in server/.env."""
    if not sys.stdin or not sys.stdin.isatty():
        return None
    print("\nNo Groq API key found.")
    print("Get a free key at https://console.groq.com/keys")
    key = input("Paste your Groq API key (starts with gsk_): ").strip()
    if not key.startswith("gsk_"):
        return None
    with ENV_FILE.open("a", encoding="utf-8") as f:
        f.write(f"\nGROQ_API_KEY={key}\n")
    print(f"Saved to {ENV_FILE}")
    return key


load_env_file()

KEY = os.environ.get("GROQ_API_KEY", "").strip()
PORT = int(os.environ.get("PORT", "5000"))
DISCOVERY_PORT = int(os.environ.get("DISCOVERY_PORT", "5001"))
LANGUAGE = os.environ.get("LANGUAGE", "en")
STT_MODEL = os.environ.get("STT_MODEL", "whisper-large-v3-turbo")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "openai/gpt-oss-20b")
TTS_MODEL = os.environ.get("TTS_MODEL", "canopylabs/orpheus-v1-english")
TTS_VOICE = os.environ.get("TTS_VOICE", "austin")
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    "You are a friendly voice assistant speaking through a small speaker. "
    "Answer in one or two short sentences, under 40 words. "
    "Use plain spoken English only: no lists, markdown, emojis, URLs or code. "
    "If you need live data such as weather or news, say you can't access it.",
)

# Optional wake word, e.g. WAKE_WORD=jarvis. When set, only sentences that
# contain it get an answer (stops replies to people talking nearby).
# Extra spellings Whisper might produce can follow, comma-separated:
# WAKE_WORD=jarvis,jervis,travis. Follow-ups within FOLLOWUP_SECONDS of an
# answer don't need it.
WAKE_WORDS = [w.strip().lower() for w in os.environ.get("WAKE_WORD", "").split(",")
              if w.strip()]
WAKE_WORD = WAKE_WORDS[0] if WAKE_WORDS else ""
FOLLOWUP_SECONDS = int(os.environ.get("FOLLOWUP_SECONDS", "30"))

BASE = "https://api.groq.com/openai/v1"
TTS_CHUNK_CHARS = 195       # Orpheus accepts at most 200 characters
MAX_TTS_CHUNKS = 4          # caps reply length at roughly 15 seconds
HISTORY_TURNS = 4           # remembered question/answer pairs per device
HISTORY_IDLE_SECONDS = 300  # forget the conversation after 5 quiet minutes

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
session = requests.Session()


def auth():
    return {"Authorization": f"Bearer {KEY}"}


# ==========================================
# WAV HELPERS
# ==========================================
def parse_wav(data):
    """Return (channels, rate, bits, pcm). Tolerates streaming headers
    whose data size is 0xFFFFFFFF, as Groq TTS sends."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    pos, fmt = 12, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b"fmt ":
            tag, channels, rate, _, _, bits = struct.unpack(
                "<HHIIHH", data[body:body + 16])
            if tag != 1:
                raise ValueError(f"WAV format {tag} is not PCM")
            fmt = (channels, rate, bits)
        elif cid == b"data":
            if fmt is None:
                raise ValueError("WAV data before fmt chunk")
            end = len(data) if size == 0xFFFFFFFF else min(len(data), body + size)
            pcm = data[body:end]
            align = fmt[0] * fmt[2] // 8
            return (*fmt, pcm[:len(pcm) - len(pcm) % align])
        pos = body + size + (size & 1)
    raise ValueError("WAV has no data chunk")


def make_wav(channels, rate, bits, pcm):
    align = channels * bits // 8
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate,
                                rate * align, align, bits)
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    )


def wav_seconds(data):
    try:
        ch, rate, bits, pcm = parse_wav(data)
        return len(pcm) / (rate * ch * bits // 8)
    except ValueError:
        return 0.0


# ==========================================
# TEXT CLEANUP FOR SPEECH
# ==========================================
PUNCT_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": ", ", "…": "...", " ": " ", " ": " ",
    "°": " degrees",
})

# Whisper "hears" these in silence or noise.
HALLUCINATIONS = {
    "", "you", "thank you", "thanks", "thank you very much",
    "thanks for watching", "thank you for watching", "bye", "okay",
    "subtitles by the amaraorg community", "music",
}


# Background noise often comes back as just these.
FILLER_WORDS = {"hmm", "hm", "mm", "mhm", "um", "uh", "ah", "oh", "so", "okay",
                "ok", "the", "a", "and", "huh"}


def is_real_speech(text):
    words = re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()
    if not words or words in HALLUCINATIONS:
        return False
    return not all(w in FILLER_WORDS for w in words.split())


def strip_wake_word(text):
    """Return the question without the wake word, or None if it's absent."""
    words = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()
    for spelling in WAKE_WORDS:
        wake = spelling.split()
        for i in range(len(words) - len(wake) + 1):
            if words[i:i + len(wake)] == wake:
                # Drop everything up to and including the wake word
                # ("Hey Jarvis, what's ..." -> "what's ...").
                pattern = (r"^.*?\b" + r"\W+".join(map(re.escape, wake))
                           + r"\b[\s,.!?]*")
                return re.sub(pattern, "", text, count=1, flags=re.I | re.S).strip()
    return None


def clean_for_speech(text):
    text = unicodedata.normalize("NFKC", text).translate(PUNCT_MAP)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)   # markdown links
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^\s*(?:[-*+#>]+|\d+[.)])\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`#|~]", "", text)
    text = text.encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip()


def split_for_tts(text):
    """Split into <=195-char pieces at sentence, then comma, then word
    boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces = []
    for sentence in sentences:
        while len(sentence) > TTS_CHUNK_CHARS:
            cut = max(sentence.rfind(", ", 0, TTS_CHUNK_CHARS),
                      sentence.rfind("; ", 0, TTS_CHUNK_CHARS))
            if cut < 60:
                cut = sentence.rfind(" ", 0, TTS_CHUNK_CHARS)
            if cut <= 0:
                cut = TTS_CHUNK_CHARS
            pieces.append(sentence[:cut + 1].strip())
            sentence = sentence[cut + 1:].strip()
        if sentence:
            pieces.append(sentence)

    chunks = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + 1 + len(piece) <= TTS_CHUNK_CHARS:
            chunks[-1] += " " + piece
        else:
            chunks.append(piece)
    return chunks[:MAX_TTS_CHUNKS]


# ==========================================
# GROQ CALLS
# ==========================================
class StageError(Exception):
    def __init__(self, stage, status, detail):
        super().__init__(f"{stage} failed ({status}): {detail}")
        self.stage = stage


def groq_error(r):
    try:
        return r.json()["error"]["message"]
    except Exception:
        return r.text[:300]


def transcribe(wav_bytes):
    data = {"model": STT_MODEL, "response_format": "json", "temperature": "0"}
    if LANGUAGE:
        data["language"] = LANGUAGE
    r = session.post(
        f"{BASE}/audio/transcriptions", headers=auth(), data=data,
        files={"file": ("input.wav", wav_bytes, "audio/wav")}, timeout=60)
    if not r.ok:
        raise StageError("Speech recognition", r.status_code, groq_error(r))
    return r.json().get("text", "").strip()


def chat(history, text):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += list(history)
    messages.append({"role": "user", "content": text})
    body = {"model": CHAT_MODEL, "messages": messages,
            "max_completion_tokens": 1024}
    if CHAT_MODEL.startswith("openai/gpt-oss"):
        # Keeps the reasoning short so it doesn't use up the token budget
        # and leave an empty answer.
        body["reasoning_effort"] = "low"
    r = session.post(f"{BASE}/chat/completions", headers=auth(), json=body,
                     timeout=60)
    if not r.ok:
        raise StageError("Chat", r.status_code, groq_error(r))
    message = (r.json().get("choices") or [{}])[0].get("message") or {}
    reply = message.get("content") or ""
    if isinstance(reply, list):
        reply = " ".join(p.get("text", "") for p in reply if isinstance(p, dict))
    return reply.strip()


def speak_chunk(text):
    r = session.post(
        f"{BASE}/audio/speech", headers=auth(), timeout=60,
        json={"model": TTS_MODEL, "voice": TTS_VOICE, "input": text,
              "response_format": "wav"})
    if not r.ok:
        raise StageError("Voice generation", r.status_code, groq_error(r))
    return parse_wav(r.content)


def synthesize(text):
    chunks = split_for_tts(text)
    if not chunks:
        raise StageError("Voice generation", 0, "nothing to say")
    with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
        parts = list(pool.map(speak_chunk, chunks))
    channels, rate, bits, _ = parts[0]
    gap = b"\x00" * (int(rate * 0.12) * channels * bits // 8)
    pcm = bytearray()
    for i, (ch, rt, bt, part) in enumerate(parts):
        if (ch, rt, bt) != (channels, rate, bits):
            raise StageError("Voice generation", 0, "mixed audio formats")
        if i:
            pcm += gap
        pcm += part
    return make_wav(channels, rate, bits, bytes(pcm))


# ==========================================
# CONVERSATION MEMORY (per device)
# ==========================================
histories = {}
history_lock = threading.Lock()


def get_history(device):
    with history_lock:
        entry = histories.get(device)
        if not entry or time.time() - entry["t"] > HISTORY_IDLE_SECONDS:
            entry = {"t": time.time(), "msgs": deque(maxlen=HISTORY_TURNS * 2)}
            histories[device] = entry
        return entry


def header_safe(text, limit=300):
    return clean_for_speech(text)[:limit]


def wav_response(wav, heard="", reply=""):
    response = Response(wav, status=200, content_type="audio/wav")
    response.headers["Content-Length"] = str(len(wav))
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Transcript"] = header_safe(heard)
    response.headers["X-Reply"] = header_safe(reply)
    return response


# ==========================================
# ROUTES
# ==========================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok", key=bool(KEY))


@app.route("/ask", methods=["POST"])
def ask():
    if not KEY:
        return jsonify(error="Server has no GROQ_API_KEY"), 500

    # The ESP32 sends a raw WAV body; multipart "audio" is accepted too.
    if "audio" in request.files:
        audio = request.files["audio"].read()
    else:
        audio = request.get_data()
    if len(audio) < 44 or audio[:4] != b"RIFF":
        return jsonify(error="Body must be a WAV file"), 400

    device = request.headers.get("X-Device") or request.remote_addr
    started = time.time()
    # Keep the latest recording so you can listen to what the mic heard.
    try:
        (HERE / "last_question.wav").write_bytes(audio)
        if os.environ.get("SAVE_RECORDINGS") == "1":
            folder = HERE / "recordings"
            folder.mkdir(exist_ok=True)
            (folder / time.strftime("%H%M%S.wav")).write_bytes(audio)
    except OSError:
        pass
    print(f"\n[{time.strftime('%H:%M:%S')}] {device}: "
          f"{len(audio)} bytes, {wav_seconds(audio):.1f}s of audio")

    try:
        heard = transcribe(audio)
        print("  USER:", heard or "(nothing)")
        if not is_real_speech(heard):
            print("  -> no real speech, ignoring")
            return Response(status=204)

        entry = get_history(device)
        if WAKE_WORD and time.time() - entry.get("answered", 0) > FOLLOWUP_SECONDS:
            question = strip_wake_word(heard)
            if question is None:
                print(f"  -> no wake word \"{WAKE_WORD}\", ignoring")
                return Response(status=204)
            if not is_real_speech(question):
                print("  -> wake word but no question, ignoring")
                return Response(status=204)
            heard = question

        reply = clean_for_speech(chat(entry["msgs"], heard))
        if not reply:
            reply = "Sorry, I didn't catch that. Could you say it again?"
        print("  ASSISTANT:", reply)

        wav = synthesize(reply)
        with history_lock:
            entry["msgs"].append({"role": "user", "content": heard})
            entry["msgs"].append({"role": "assistant", "content": reply})
            entry["t"] = entry["answered"] = time.time()

        print(f"  -> {len(wav)} bytes, {wav_seconds(wav):.1f}s of speech, "
              f"total {time.time() - started:.1f}s")
        return wav_response(wav, heard, reply)

    except StageError as e:
        print("  ERROR:", e)
        return jsonify(error=str(e)), 502
    except requests.Timeout:
        print("  ERROR: Groq timed out")
        return jsonify(error="Groq request timed out"), 504
    except requests.RequestException as e:
        print("  NETWORK ERROR:", e)
        return jsonify(error="Cannot reach Groq - check internet"), 502
    except Exception:
        app.logger.exception("Unexpected server error")
        return jsonify(error="Internal server error"), 500


hello_cache = {}


@app.route("/hello", methods=["GET"])
def hello():
    """Short spoken test so the ESP32 can check the download + speaker path."""
    text = "Hi! I'm connected to your laptop and ready. Ask me anything."
    try:
        if "wav" not in hello_cache:
            hello_cache["wav"] = synthesize(text)
        return wav_response(hello_cache["wav"], "", text)
    except StageError as e:
        print("  ERROR:", e)
        return jsonify(error=str(e)), 502
    except requests.RequestException as e:
        print("  NETWORK ERROR:", e)
        return jsonify(error="Cannot reach Groq - check internet"), 502


@app.route("/reset", methods=["POST"])
def reset():
    with history_lock:
        histories.clear()
    return jsonify(status="conversation cleared")


# ==========================================
# AUTO-DISCOVERY (UDP)
# ==========================================
def discovery_responder():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", DISCOVERY_PORT))
    except OSError as e:
        print(f"WARNING: discovery port {DISCOVERY_PORT} unavailable ({e}). "
              "Set the server address on the ESP32 manually.")
        return
    while True:
        try:
            data, addr = sock.recvfrom(64)
        except OSError:
            continue
        if data.strip() == b"VA_DISCOVER":
            sock.sendto(f"VA_SERVER {PORT}".encode(), addr)
            print(f"[discovery] answered ESP32 at {addr[0]}")


# ==========================================
# STARTUP
# ==========================================
def lan_addresses():
    addresses = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except socket.gaierror:
        pass
    try:  # address of the interface that routes to the internet
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        addresses.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(a for a in addresses if not a.startswith(("127.", "169.254.")))


def check_key():
    try:
        r = session.get(f"{BASE}/models", headers=auth(), timeout=10)
    except requests.RequestException as e:
        return f"cannot reach Groq ({e.__class__.__name__}) - check internet"
    if r.status_code == 401:
        return "key rejected (401) - check GROQ_API_KEY"
    if not r.ok:
        return f"Groq error {r.status_code}"
    return "OK"


def main():
    global KEY
    if not KEY:
        KEY = ask_for_key() or ""
    if not KEY:
        sys.exit("Missing GROQ_API_KEY. Put it in server/.env "
                 "(see server/.env.example).")

    print("=" * 52)
    print(" Voice assistant server")
    print("=" * 52)
    print(" Groq key:   ", check_key())
    print(" Chat model: ", CHAT_MODEL)
    print(" Wake word:  ", ", ".join(WAKE_WORDS) if WAKE_WORDS
          else "off (answers everything)")
    print(" Listening on port", PORT, "| discovery on UDP", DISCOVERY_PORT)
    print(" This laptop's addresses (ESP32 finds it automatically):")
    for a in lan_addresses():
        print(f"   http://{a}:{PORT}")
    print("=" * 52)

    threading.Thread(target=discovery_responder, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
