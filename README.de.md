# Wyoming Noise Cancelling Proxy

**Lokale Audioaufbereitung für Wyoming-Spracherkennung**

[![Auf Ko-fi unterstützen](https://img.shields.io/badge/Ko--fi-Unterst%C3%BCtzen-FF5E5B?style=for-the-badge&logo=kofi&logoColor=white)](https://ko-fi.com/dominik_w)
[![Mit PayPal unterstützen](https://img.shields.io/badge/PayPal-Unterst%C3%BCtzen-003087?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/DominikWeiland)

<img src="assets/logo.png" alt="Wyoming Noise Cancelling Proxy Logo" width="180">

Deutsch · [English](README.md)

`Sprachgerät → DTLN → Hush → Wyoming-STT-Dienst`

Vier Varianten stehen in der Weboberfläche bereit: Originalton, DTLN, Hush und DTLN → Hush. Grundeinstellung: **beide Filter aktiv, Hush mit 12 dB Dämpfungsbegrenzung**. Keine GPU, Cloud-Audioverarbeitung oder Home-Assistant-Zugangsdaten nötig.

## Starten

```sh
docker compose up -d
```

Weboberfläche: **Port 10323**. Dort STT-Host und dessen Wyoming-Port eintragen. Das Sprachgerät oder die Wyoming-Integration in Home Assistant verbindet sich mit dem Proxy auf **Port 10322**.

Image: `ghcr.io/dominik-1980/wyoming-noise-cancelling-proxy:0.3.1`

Compose verwendet ein eigenes Volume für `/data`. Dort liegen Einstellungen und optionale Aufnahmen. Der Container läuft als UID99/GID100; ein eigener Bindmount muss dieser Kennung Schreibzugriff erlauben. Die Vorlage für Unraid liegt unter [unraid/wyoming-noise-cancelling-proxy.xml](unraid/wyoming-noise-cancelling-proxy.xml).

`UPSTREAM_URI=tcp://stt-server:10300` ist als initiales Ziel optional. Gespeicherte Einstellungen haben Vorrang. Die Weboberfläche ist für das vertrauenswürdige LAN gedacht und besitzt keine Anmeldung.

## Bedienung

- **Audiofilter aktiv:** aus bedeutet bitgenaue Weiterleitung des Originals.
- **DTLN aktiv:** erste Stufe der Audioaufbereitung.
- **Hush aktiv:** zweite Stufe; bei ausgeschaltetem DTLN arbeitet Hush allein.
- **Maximale Hush-Absenkung:** 0–60 dB, Standard **12 dB**. Höhere Werte filtern stärker.
- **WAV-Aufnahme:** speichert Original und Endausgabe mit Transkript, Zeitpunkt und Filtereinstellungen. Standardmäßig ausgeschaltet.

Änderungen greifen beim nächsten Sprachbefehl. Laufende Anfragen behalten ihre Einstellungen. Aufnahmen lassen sich lokal abspielen, herunterladen und nach Bestätigung einzeln oder gesammelt löschen. Aktive Aufnahmen und Einstellungen bleiben geschützt; die Speicherbegrenzung wird dabei aktualisiert.

## Echtzeitverarbeitung

DTLN verarbeitet 128-Sample-Schritte mit 512-Sample-Fenstern; Hush arbeitet in 160-Sample-Schritten. Beide Stufen behalten ihre Zustände während des Sprachbefehls. Bearbeitetes Audio wird schon während der Eingabe weitergeleitet. Am Ende werden Restpuffer ausgegeben; die Samplezahl bleibt erhalten.

Benötigt werden **16 kHz, Mono, PCM16** und ein Wyoming-STT-Dienst. Der Client muss das Sprachende mit `audio-stop` melden; der Proxy führt keine eigene Spracherkennung oder Sprachende-Erkennung aus. Zwischen den Stufen findet keine zusätzliche Lautheitsnormalisierung statt.

Die Filter können je nach Aufnahme auch Sprachdetails verändern. Angenehmerer Klang garantiert keine bessere Erkennung; eine gezielte Trennung beliebiger Sprecher ist nicht zugesichert. Für die gesamte Assist-Latenz zählen zusätzlich Übertragungsblöcke, Rechenzeit und STT.

## Aktualisierung vom Hush-Proxy

Dieses Projekt führt Wyoming Hush Proxy fort. Historie und ältere Releases bleiben erhalten. Bei einer bestehenden Installation das bisherige `/data`-Volume und die Hostports weiterverwenden. Einstellungen und Aufnahmeformat bleiben kompatibel. Die zusätzlichen Filterschalter sind standardmäßig an.

**Bereits gespeicherte Absenkungswerte bleiben erhalten.** 12 dB gilt für neue Einstellungen und überschreibt keinen bewusst gespeicherten Wert. Die bisherige Hush-only-Version 0.2.0 bleibt als älteres Release verfügbar. Home-Assistant-Einstellungen werden vom Container nicht verändert.

## Technik, Tests und Lizenz

Alle Modelle sind im Image enthalten und werden gegen Prüfsummen geprüft; zur Laufzeit werden keine Gewichte heruntergeladen. Die Tests decken Streaming, kurze und fragmentierte Eingaben, Auslauf, getrennte Sitzungen, Filtermodi, Weiterleitung und Aufnahmeverwaltung ab. Es werden simulierte STT-Dienste und keine echten Haussteuerungsaktionen verwendet.

[Entwicklungs- und API-Dokumentation](README.md#development-and-verification) · [Änderungen](CHANGELOG.md)

DTLN stammt von [Nils L. Westhausen](https://github.com/breizhn/DTLN). Hush basiert auf [livekit-plugins-hush](https://github.com/arpesenti/livekit-plugins-hush), Hush und DeepFilterNet. Proxy/Hush-Komponenten: Apache-2.0; DTLN: MIT. Vollständige Hinweise unter [NOTICE](NOTICE) und [licenses/](licenses/).
