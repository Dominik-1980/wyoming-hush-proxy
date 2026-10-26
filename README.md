# Wyoming Noise Cancelling Proxy

**Local streaming audio enhancement for Wyoming speech-to-text services**

[![Auf Ko-fi unterstützen](https://img.shields.io/badge/Ko--fi-Unterst%C3%BCtzen-FF5E5B?style=for-the-badge&logo=kofi&logoColor=white)](https://ko-fi.com/dominik_w)
[![Mit PayPal unterstützen](https://img.shields.io/badge/PayPal-Unterst%C3%BCtzen-003087?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/DominikWeiland)

<img src="assets/logo.png" alt="Wyoming Noise Cancelling Proxy logo" width="180">

[Deutsch](README.de.md) · English

`Voice client → DTLN → Hush → your Wyoming STT service`

DTLN and Hush can be switched independently. Choose original audio, DTLN, Hush, or the DTLN → Hush cascade in the web interface. The default is the cascade with a **12 dB Hush attenuation limit**. No GPU, cloud audio service, LiveKit server, or Home Assistant token is required.

## Features

- Processes audio while it arrives; forwards filtered chunks before `audio-stop`.
- Original DTLN ONNX models and stateful Hush ONNX/NumPy inference, with independent state per utterance.
- Arbitrary input chunk boundaries, compensated framing delay, complete tails and preserved sample counts.
- Global bit-exact bypass; independent DTLN/Hush switches; Hush attenuation adjustable from 0 to 60 dB.
- STT host/port and filters configurable without restarting. Changes apply to the next utterance.
- Discovers installed downstream models/languages and forwards model selection, language, context and backend errors.
- Optional paired original/processed WAV recordings, transcript and per-recording filter settings; local playback/downloads.
- Recording is **off by default**. Quota, per-utterance limits and confirmed deletion protect recording storage.
- Bundled, checksum-verified models; no runtime model downloads.

**Compatibility:** Wyoming ASR over TCP, **16 kHz mono PCM16**. Clients must send `audio-stop`; the proxy does not implement end-of-speech detection. HTTP/OpenAI-compatible STT services need a Wyoming adapter. This is audio enhancement, not a guarantee of target-speaker separation or improved recognition on every recording.

## Docker

Image: `ghcr.io/dominik-1980/wyoming-noise-cancelling-proxy:0.3.1`

```sh
docker compose up -d
```

Open the web interface on **port 10323**, then set the existing STT server's hostname and Wyoming port. Point the voice client or Home Assistant Wyoming integration at this proxy on **port 10322**.

The Compose file maps host ports 10322/10323 to container ports 10326/10327 and uses a dedicated named volume for `/data`. It runs as UID99/GID100 with a read-only root filesystem, restricted capabilities and a writable temporary filesystem.

`UPSTREAM_URI=tcp://stt-server:10300` can supply an optional initial target. Saved web settings take precedence. The proxy image does not include an STT model.

Manual equivalent:

```sh
docker run -d --name wyoming-noise-cancelling-proxy   -p 10322:10326 -p 10323:10327   -v noise-data:/data   --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m   --cap-drop ALL --security-opt no-new-privileges:true   --memory 512m --cpus 2   ghcr.io/dominik-1980/wyoming-noise-cancelling-proxy:0.3.1
```

The UI has no login and is intended for a trusted LAN. Keep it behind your normal access controls rather than exposing it directly to the internet.

## Unraid and upgrades

Import [the Unraid template](unraid/wyoming-noise-cancelling-proxy.xml). It includes the project icon, web UI, ports and a separate appdata path. Bind-mounted appdata must be writable by UID99/GID100.

This project continues **Wyoming Hush Proxy**. Git history and the older release remain available. Existing settings and recording files are compatible: keep the existing `/data` mount and host ports when upgrading. New filter switches default to enabled. Existing explicitly saved attenuation values are preserved; **12 dB is the default for fresh settings**, not a forced overwrite.

Before replacing a running container, save its template/settings and keep the old image for rollback. The proxy does not modify Home Assistant configuration. The old `wyoming-hush-proxy:0.2.0` release remains a Hush-only version.

## Filtering and latency

DTLN uses 512-sample windows and 128-sample steps. Hush uses 160-sample steps. The proxy buffers only the required frames and carries neural/DSP state between chunks. Both filters flush at the end of an utterance. It does not wait for the whole sentence before forwarding audio.

Framing, transfer buffers, CPU processing and downstream STT add latency. Offline processing speed is not the same as full Assist latency. No loudness normalization is added between stages.

## Development and verification

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python verify_models.py
.venv/bin/python -m unittest discover -s tests -v
```

The tests use a simulated Wyoming STT server, not Home Assistant actions. Coverage includes chunk fragmentation, short clips/tails, state isolation, settings snapshots, all four modes, early forwarding, routing and recording controls. The current runtime has been tested on Linux/amd64; the publishing workflow also builds Linux/arm64 images.

`tools/validate_recordings.py` can compare streaming outputs against a separately supplied offline baseline. Personal recordings, settings and local deployment artifacts are excluded from the repository and image. `scripts/verify_release.py` checks release contents and model provenance.

Build from source with `docker build -t wyoming-noise-cancelling-proxy:local .`.

## APIs and limits

- `GET /healthz`: process readiness/version.
- `GET /api/state`: filter settings, upstream, session and storage status.
- `POST /api/settings`: validated changes persisted atomically.
- `GET /api/recordings`: completed/inactive recording metadata.
- `/recordings/<id>/<file>`: finalized WAV/metadata downloads.
- Recording deletion requires explicit confirmation and same-origin JSON requests.

Environment: `MAX_RECORDING_MB=512`, `MAX_AUDIO_SECONDS=60`, `MAX_SESSIONS=2`, optional `UPSTREAM_URI`, `DATA_DIR`, `LISTEN_HOST`, `WYOMING_PORT`, `WEB_PORT` and `LOG_LEVEL`. The default container ports are 10326/10327; the supplied deployment files expose 10322/10323.

## Credits and licensing

Based on [Wyoming Hush Proxy](https://github.com/Dominik-1980/wyoming-noise-cancelling-proxy/tree/74cf7682d6e59ec510f20f96554bf20c8b1428e8), [DTLN by Nils L. Westhausen](https://github.com/breizhn/DTLN), and the stateful Hush core from [livekit-plugins-hush](https://github.com/arpesenti/livekit-plugins-hush). Hush derives from [pulp-vision/Hush](https://github.com/pulp-vision/Hush) and [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet).

Proxy/Hush components: Apache-2.0. DTLN: MIT. See [LICENSE](LICENSE), [NOTICE](NOTICE), and [third-party license texts](licenses/). Pinned source/model identities are recorded in `vendor-manifest.json`, `model-checksums.json`, `dtln-models.json` and `base-provenance.json`.
