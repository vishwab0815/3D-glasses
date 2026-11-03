
import os
import requests
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# Keep Groq API key on laptop only
KEY = os.environ.get("GROQ_API_KEY")
BASE = "https://api.groq.com/openai/v1"

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok")


@app.route("/ask", methods=["POST"])
def ask():

    if not KEY:
        print("ERROR: Missing GROQ_API_KEY")
        return jsonify(error="Missing API key"), 500

    if "audio" not in request.files:
        return jsonify(error="Missing audio file"), 400

    audio = request.files["audio"]
    audio_bytes = audio.read()

    if not audio_bytes:
        return jsonify(error="Empty uploaded audio"), 400

    print("\nReceived audio bytes:", len(audio_bytes))

    try:
        # 1. Speech to text
        stt = requests.post(
            f"{BASE}/audio/transcriptions",
            headers={"Authorization": f"Bearer {KEY}"},
            files={
                "file": (
                    "input.wav",
                    audio_bytes,
                    "audio/wav"
                )
            },
            data={
                "model": "whisper-large-v3-turbo"
            },
            timeout=120
        )

        if not stt.ok:
            print("STT ERROR:", stt.status_code, stt.text[:500])
            return jsonify(error="Speech recognition failed"), 502

        text = stt.json().get("text", "").strip()
        print("USER:", text)

        if not text:
            return jsonify(error="No speech recognized"), 422

        # 2. Chat
        chat = requests.post(
            f"{BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {KEY}"
            },
            json={
                "model": "openai/gpt-oss-20b",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a friendly voice assistant. "
                            "Keep replies concise."
                        )
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                "max_completion_tokens": 300
            },
            timeout=120
        )

        if not chat.ok:
            print("CHAT ERROR:", chat.status_code, chat.text[:500])
            return jsonify(error="Chat failed"), 502

        reply = (
            chat.json()["choices"][0]["message"]["content"]
            .strip()
        )

        print("ASSISTANT:", reply)

        if not reply:
            return jsonify(error="Empty assistant reply"), 502

        # 3. Text to speech
        tts = requests.post(
            f"{BASE}/audio/speech",
            headers={
                "Authorization": f"Bearer {KEY}"
            },
            json={
                "model": "canopylabs/orpheus-v1-english",
                "voice": "austin",
                "input": reply[:200],
                "response_format": "wav"
            },
            timeout=120
        )

        if not tts.ok:
            print("TTS ERROR:", tts.status_code, tts.text[:500])
            return jsonify(error="Voice generation failed"), 502

        wav_bytes = tts.content

        print("TTS audio bytes:", len(wav_bytes))

        if len(wav_bytes) < 12 or not wav_bytes.startswith(b"RIFF"):
            print("ERROR: TTS response is not RIFF WAV")
            return jsonify(error="Unexpected audio format"), 502

        # 4. Send raw WAV with explicit length
        response = Response(
            wav_bytes,
            status=200,
            content_type="audio/wav"
        )

        response.headers["Content-Length"] = str(len(wav_bytes))
        response.headers["Content-Disposition"] = (
            'attachment; filename="reply.wav"'
        )
        response.headers["Cache-Control"] = "no-store"

        print("Sending WAV response:", len(wav_bytes), "bytes")

        return response

    except requests.Timeout:
        print("ERROR: Groq request timed out")
        return jsonify(error="Groq request timed out"), 504

    except requests.RequestException as e:
        print("NETWORK ERROR:", str(e))
        return jsonify(error="Groq network request failed"), 502

    except Exception as e:
        app.logger.exception("Unexpected server error")
        return jsonify(error="Internal server error"), 500


if __name__ == "__main__":
    print("Groq key available:", bool(KEY))
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True
    )
