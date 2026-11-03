# 3D Glasses: ESP32-S3 Voice Assistant

A voice assistant built into 3D-printed glasses. The ESP32 listens all the
time, records while you speak, sends the audio to a laptop, and plays back a
spoken answer.

```bash
git clone https://github.com/vishwab0815/3D-glasses.git
cd 3D-glasses
```

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
| Breadboard or soldered wires, USB-C **data** cable | |

**Full wiring diagram:** open [docs/wiring_diagram.html](docs/wiring_diagram.html)
in a browser (download it first if you're on GitHub). Part sizes and pin
spacing are in [docs/Hardware_Dimensions.pdf](docs/Hardware_Dimensions.pdf).

### Every connection

| From | To XIAO pin (GPIO) | Notes |
|---|---|---|
| Mic **VDD** | **3V3** | 3.3 V only; 5 V can destroy the mic |
| Mic **GND** | **GND** | |
| Mic **SD** | **D0** (GPIO1) | sound data into the board |
| Mic **SCK** | **D1** (GPIO2) | shared with amp BCLK |
| Mic **WS** | **D2** (GPIO3) | shared with amp LRC |
| Mic **L/R** | **GND** | a short jumper to the mic's own GND pin is fine |
| Amp **VIN** | **5V** | on battery, use BAT+ instead (see below) |
| Amp **GND** | **GND** | |
| Amp **BCLK** | **D1** (GPIO2) | same wire as mic SCK |
| Amp **LRC** | **D2** (GPIO3) | same wire as mic WS |
| Amp **DIN** | **D3** (GPIO4) | sound data out to the speaker |
| Amp **GAIN**, **SD** | not connected | 9 dB gain, always on |
| Speaker red | Amp **SPK +** | |
| Speaker black | Amp **SPK −** | |

**D1 and D2 are shared:** each one goes to both the mic and the amp. The
firmware uses the mic and the speaker one at a time, so this is safe.

### Rules that prevent damage

- The **speaker connects only to the amp's SPK + and SPK −**, never to 3V3,
  5V or GND. That shorts the supply through the speaker coil.
- The **mic runs on 3.3 V only**.
- **Solder joints; don't twist wires around pins.** Twisted joints work on
  the desk and fail when the glasses hinge moves.
- **On battery:** the XIAO's 5V pin has power only while USB is plugged in.
  Connect the amp's VIN to the battery's **BAT+** pad on the back of the XIAO
  (the amp runs on 2.5–5.5 V). Never put the 3.7 V battery on the 3V3 pin.
- Unplug USB before rewiring anything.

The mic's tiny sound hole must face the wearer's mouth and stay uncovered.
If L/R goes to 3V3 instead of GND, that's fine too: the firmware detects either.

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

> The first `flash` downloads the ESP32 tools: about 2 GB, 4 GB once
> installed. Low on space on C:? Put them on another drive once (it's
> remembered): `python tools/device.py flash --arduino-data D:\ArduinoData`.
> On a slow or unstable phone hotspot this download can time out; just run
> `flash` again, or use better internet for the first install.

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
| `micdiag` | if the mic gives no signal: tells you whether it's power, clock or the data wire |
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
| `[mic] NO SIGNAL`, or `mic` shows only 0 | the mic isn't sending data. Run `micdiag`. Check all 6 mic wires, especially **SCK → D1** (no clock = no data), VDD → 3V3 and SD → D0. Once fixed, the board finds the mic within 5 s by itself |
| It answers people talking nearby | run `calibrate`; set `WAKE_WORD=jarvis` in `server/.env`; or use `mode button` |
| `[ignored] quieter than your voice` when *you* speak | you're further away than during calibration: move closer, re-run `calibrate`, or raise `sensitivity` |
| It starts recording by itself | keep the board away from the laptop's fan and vents; try `sensitivity 3` |
| It never notices you speaking | speak within ~1 m; try `sensitivity 7`; run `mic` to see your level |
| `Voice generation failed` in server log | accept the Orpheus terms (section 2, step 4) |
| No sound from the speaker | run `tone`; check DIN → D3 and that the speaker's two wires are on the amp's SPK + and SPK − (not 3V3/GND); try `volume 100` |
| `flash` stops with `Download failed` | the internet dropped during the one-time tool download; run `flash` again |
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
docs/wiring_diagram.html    full wiring diagram (open in a browser)
docs/Hardware_Dimensions.pdf part sizes, pin spacing, chip sizes
start_server.bat            Windows: start the server
setup_device.bat            Windows: flash + Wi-Fi setup
backup_original/            the original project files
```

Not in the repo (kept private on your own machine): `server/.env` with your
Groq key, voice recordings and logs.
