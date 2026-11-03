# ESP32-S3 Voice Assistant

Talk to a small speaker. The ESP32 listens all the time, records while you
speak, sends the audio to a laptop, and plays back a spoken answer.

```
 You speak ──► INMP441 mic ──► XIAO ESP32-S3 ──Wi-Fi──► laptop: server.py
                                                         │ Groq Whisper (speech → text)
                                                         │ Groq chat    (answer)
                                                         │ Groq Orpheus (text → speech)
 You hear ◄── speaker ◄── MAX98357A ◄── XIAO ESP32-S3 ◄──┘ WAV reply
```

- Starts recording by itself when you speak, stops after about 2 s of silence (10 s max).
- Finds the laptop on the network automatically, so you never type an IP address.
- Remembers the conversation for follow-up questions (forgets after 5 quiet minutes).
- Wi-Fi is set up over USB with one command, or from a phone.

---

## 1. Parts and wiring

| Part | Notes |
|---|---|
| Seeed Studio **XIAO ESP32-S3** | must be the S3 (has 8 MB PSRAM) |
| **INMP441** I2S microphone | |
| **MAX98357A** I2S amplifier | + a 4–8 Ω speaker |
| Breadboard, jumper wires, USB-C **data** cable | |

The mic and amplifier **share** the BCLK and WS lines.

| INMP441 pin | XIAO pin (GPIO) | | MAX98357A pin | XIAO pin (GPIO) |
|---|---|---|---|---|
| VDD | 3V3 | | VIN | 5V |
| GND | GND | | GND | GND |
| SCK | **D1** (GPIO2) | | BCLK | **D1** (GPIO2) |
| WS | **D2** (GPIO3) | | LRC | **D2** (GPIO3) |
| SD | **D0** (GPIO1) | | DIN | **D3** (GPIO4) |
| L/R | GND | | GAIN, SD | leave unconnected |

Speaker wires go to the amplifier's `+` and `−` screw terminals.
(If L/R goes to 3V3 instead, that's fine too: the firmware detects either.)

---

## 2. One-time laptop setup

1. Install **Python 3.10+** (python.org; tick "Add to PATH").
2. Install the **Arduino IDE 2** (arduino.cc/en/software). The tools use the
   `arduino-cli` that comes inside it.
3. Get a free **Groq API key**: https://console.groq.com/keys
4. Accept the voice model's terms once, or replies will have no voice:
   https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english
5. Copy `server/.env.example` to `server/.env` and paste your key:
   ```
   GROQ_API_KEY=gsk_...
   ```
   (If you skip this, the server asks for the key the first time it runs.)

> `server/.env` holds your private key. Never share or upload it.

---

## 3. Wi-Fi: the one rule

**The ESP32 and the laptop must be on the same Wi-Fi, and it must be 2.4 GHz.**
The ESP32-S3 cannot use 5 GHz networks.

- **Home router:** most broadcast 2.4 GHz already. Use that network.
- **Phone hotspot:** switch it to 2.4 GHz.
  Android: *Hotspot → AP band → 2.4 GHz*. iPhone: *Personal Hotspot → Maximize Compatibility*.
  Then reconnect the laptop to it.
- **College/office Wi-Fi with a login page** won't work. Use a hotspot instead.

---

## 4. Run it

**Windows (double-click):**

1. `start_server.bat` keeps the server running. Leave this window open.
   When Windows Firewall asks, click **Allow** (private and public).
2. Plug in the ESP32, then run `setup_device.bat`. It flashes the firmware and
   sends your laptop's current Wi-Fi name and password to the board over USB.

**Any OS (terminal, from this folder):**

```bash
python -m pip install -r requirements.txt
python server/server.py               # window 1, keep running
python tools/device.py flash          # window 2: build + upload firmware
python tools/device.py setup          # send Wi-Fi to the board
python tools/device.py monitor        # watch it work (optional)
```

When setup prints `SUCCESS`, teach it your voice (recommended, takes 10 s):

```bash
python tools/device.py calibrate
```

Stay quiet for 2 s, then speak normally from where you'll usually sit when it
says so. After that, quieter speech from people further away is ignored.
Then just talk to it. The XIAO's orange LED is on while it records and thinks.

> Low on disk space on C:? The ESP32 tools need about 4 GB. Put them on
> another drive once (it's remembered):
> `python tools/device.py flash --arduino-data D:\ArduinoData`

### No laptop USB? Use a phone

If the board has no Wi-Fi saved, or can't join its saved network, it opens
its own hotspot **VoiceAssistant-XXXX**. Join it on a phone, open
`http://192.168.4.1`, and pick your Wi-Fi. Holding **BOOT** for 3 s opens this
page at any time.

### Using the Arduino IDE instead of `device.py flash`

Open `firmware/voice_assistant/voice_assistant.ino` and set:
- Board: **XIAO_ESP32S3** (esp32 by Espressif, v3.x)
- Tools → **PSRAM: OPI PSRAM** (required for 10 s recordings)
- Tools → USB CDC On Boot: **Enabled**

---

## 5. Commands and settings

Run them with `python tools/device.py cmd <command>`, or type them in
`monitor` / the Arduino Serial Monitor (115200 baud). They're saved on the board.

| Command | What it does |
|---|---|
| `status` | Wi-Fi, server, mic level and settings |
| `calibrate` | learn your voice level; quieter (further away) speech is ignored. `calibrate off` to undo |
| `mic` | live mic level for 5 s (talk to check it hears you) |
| `tone` | test beep on the speaker |
| `hello` | the server speaks a test sentence |
| `volume 60` | speaker volume 0–100 |
| `silence 1500` | how long a pause ends your question (ms) |
| `sensitivity 3` | 1–10; lower = needs a louder or closer voice |
| `mode button` | only record after a short press of **BOOT** (`mode auto` to undo) |
| `server 192.168.1.20:5000` | fixed server address (`server auto` = find it) |
| `pause` / `resume` | stop / start listening |
| `forget` | erase Wi-Fi settings |

Server options go in `server/.env` (restart the server after editing):

| Setting | Meaning |
|---|---|
| `WAKE_WORD=jarvis,jervis,travis` | only answer sentences that contain "jarvis" (extra spellings catch Whisper's mistakes); follow-ups within 30 s don't need it |
| `SAVE_RECORDINGS=1` | keep every recording in `server/recordings/` for tuning |
| `TTS_VOICE=austin` | Orpheus voice (e.g. austin, troy, hannah, diana) |
| `LANGUAGE=en` | speech recognition language |
| `CHAT_MODEL=openai/gpt-oss-20b` | Groq chat model |

---

## 6. Troubleshooting

| You see | Fix |
|---|---|
| `[wifi] FAILED` | wrong password, or the network is 5 GHz (see section 3) |
| `[server] not found` | start `server.py`; laptop on the **same** Wi-Fi; allow Python in Windows Firewall |
| `[mic] NO SIGNAL` | check mic wiring, especially SD → D0 and VDD → 3V3 |
| It answers people talking nearby | run `calibrate`; set `WAKE_WORD=jarvis` in `server/.env`; or use `mode button` |
| `[ignored] quieter than your voice` when *you* speak | you're further away than during calibration: move closer, re-run `calibrate`, or raise `sensitivity` |
| It starts recording by itself | keep the board away from the laptop's fan and vents; try `sensitivity 3` |
| It never notices you speaking | speak within ~1 m; try `sensitivity 7`; run `mic` to see your level |
| `Voice generation failed` in server log | accept the Orpheus terms (section 2, step 4) |
| No sound from the speaker | run `tone`; check DIN → D3 and the speaker terminals; try `volume 100` |
| Port busy / `Cannot open COM` | close the Arduino Serial Monitor |

**Hear what the mic recorded:** the server saves the latest recording as
`server/last_question.wav`.

**Test the server without the ESP32:** with the server running,
`python tools/test_server.py` speaks a test question (Windows) and saves the
answer to `reply.wav`.

---

## Files

```
server/server.py            laptop server (Groq pipeline + auto-discovery)
server/.env.example         settings template (copy to .env)
firmware/voice_assistant/   ESP32 firmware
tools/device.py             flash, Wi-Fi setup, monitor, commands
tools/test_server.py        server test without hardware
start_server.bat            Windows: start the server
setup_device.bat            Windows: flash + Wi-Fi setup
backup_original/            the original project files
```
