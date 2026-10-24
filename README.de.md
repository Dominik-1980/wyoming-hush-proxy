# Wyoming Sprachfilter Proxy

Lokaler Hush-Sprachfilter für beliebige **Wyoming-kompatible STT-Dienste**. Docker-Image: `ghcr.io/dominik-1980/wyoming-hush-proxy:0.2.0`.

`Sprachclient → Wyoming Sprachfilter Proxy → STT-Ziel`

Die Weboberfläche auf Port **10323** bietet:

- Frei einstellbaren STT-Host und Port.
- Filter an/aus, maximale Absenkung **12 dB Voreinstellung**.
- Optionale WAV-Aufnahmen mit **Original** und **Bearbeitet**, standardmäßig aus.
- Einzelnes oder gemeinsames Löschen abgeschlossener Aufnahmen nach Bestätigung. Laufende Aufnahmen bleiben erhalten.

Änderungen gelten ab dem nächsten Sprachbefehl, ohne Neustart. Modelle und Sprachen werden vom STT-Ziel übernommen. Der Proxy verarbeitet ausschließlich **16 kHz, Mono, PCM16** über Wyoming-TCP; reine HTTP-STT-APIs benötigen einen Wyoming-Adapter.

## Start

Die mitgelieferte `compose.yaml` verwendet das öffentliche Image und einen lokalen Ordner `./data`. Dieser muss für UID 99/GID 100 beschreibbar sein. In Unraid kann die mitgelieferte [DockerMan-Vorlage](unraid/wyoming-hush-proxy.xml) verwendet werden.

Zuerst `http://SERVER:10323` öffnen, STT-Host/Port eintragen und speichern. Danach in Home Assistant eine Wyoming-Integration mit der Proxy-Adresse und Port **10322** hinzufügen und den Dienst in der Sprachpipeline auswählen. Die bisherige direkte STT-Verbindung als Rückweg behalten.

Das Image lädt beim Start nichts nach und benötigt keinen Cloud-/LiveKit-Server, keine GPU und keinen HA-Token. Die Weboberfläche hat keine Anmeldung und ist ausschließlich für ein vertrauenswürdiges lokales Netz gedacht.

Die WAVs werden beim Anhören nicht automatisch auf gleiche Lautheit gebracht. Hush kann auch gewünschte Sprachanteile abschwächen; ein leiseres Ergebnis beweist keine bessere Erkennung. Original/Bearbeitet und die Transkripte praktisch vergleichen.

Vollständige Konfiguration, Entwicklung, Grenzen und Herkunft stehen in der [englischen README](README.md). Lizenz: [Apache-2.0](LICENSE).
