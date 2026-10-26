# Changelog

## 0.3.1 — 2026-10-26

- Fix the icon test fixture path when tests are mounted separately into the Docker image.
- Complete the 0.3 release publication; no change to the filtering algorithm.

## 0.3.0 — 2026-10-26

- Rename the project to **Wyoming Noise Cancelling Proxy**; retain repository history and the existing icon.
- Add causal DTLN streaming before the existing Hush filter, with independent per-stage switches and bit-exact global bypass.
- Default to DTLN → Hush with a **12 dB** Hush attenuation limit. Explicitly saved settings are preserved.
- Preserve Wyoming routing, downstream model/language discovery, context, errors and paired recording controls.
- Complete partial frames/tails, retain sample counts and isolate state/settings per utterance.
- Add matching English/German documentation, Ko-fi/PayPal support links, branded UI and Unraid template.
- Verify streaming against offline audio, cover four modes and publish Docker images for Linux/amd64 and Linux/arm64.

## Earlier Hush-only releases

Versions through 0.2.0 are retained in Git history and GitHub Releases. The original Hush implementation and licensed model provenance remain documented in `NOTICE` and `vendor-manifest.json`.
