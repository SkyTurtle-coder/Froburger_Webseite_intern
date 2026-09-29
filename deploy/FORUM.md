# Forum

Alle angemeldeten Mitglieder lesen PDF-Ausgaben, kommentieren, antworten und
liken Kommentare. ADMIN und WEB_X verwalten Ausgaben und moderieren Kommentare.
Ausgaben erscheinen neueste zuerst; Kommentare und Antworten nach Likes,
anschliessend nach Erstellungszeit absteigend. Antworten bleiben in ihrem Thread
und verlinken den direkten Empfänger. Gelöschte Kommentare werden geleert, ihre
Antworten bleiben erhalten. Änderungen tragen einen Zeitstempel.

Antworten benachrichtigen den direkten Kommentarverfasser über die bestehende
Django-Mailkonfiguration. Keine Mail bei eigenen Antworten, Likes, Bearbeitungen,
gelöschten Elternkommentaren oder inaktiven Empfängern. SMTP-Fehler werden geloggt;
der Kommentar bleibt gespeichert. Es gibt keine automatische Mail-Wiederholung.

PDFs: maximal 20 MB, nur über authentifizierte Forum-Endpunkte; Speicherung unter
MEDIA_ROOT/protected/forum. Nginx muss wie bisher /media/ sperren (ausser
/media/public/). PDF.js 6.3.289 samt Fonts, CMaps und WASM liegt lokal unter
static/vendor/pdfjs; keine externen PDF-Dienste oder CDN-Aufrufe im Browser.
Die ES-Module verwenden .js-Dateiendungen für bestehende Nginx-MIME-Zuordnungen.

## Lokal prüfen

```powershell
.venv/Scripts/python.exe manage.py test forum.tests --noinput
# Optional: benötigt Playwright und dessen Chromium-Browser.
.venv/Scripts/python.exe manage.py test forum.tests_browser --noinput
```

## Installation

In lokaler PowerShell, nicht auf dem Server:

```powershell
Set-Location 'C:\Users\phili\Local Sites\av-froburger\app'
powershell -NoProfile -ExecutionPolicy Bypass -File .\intern\deploy\Deploy-Forum.ps1 -Deploy
```

Ohne `-Deploy` wird nur das Paket vorbereitet. Das Skript nimmt ausschliesslich
committete Forum-Dateien aus dem lokalen Branch `feature/forum` und nennt den
vollständigen Commit. Lokale Dokument-/Tabellenänderungen bleiben ausserhalb des
Pakets. Unbekannte Änderungen an gemeinsamen Serverdateien führen vor der
Installation zum Abbruch, statt sie zu überschreiben.

Ziel: debian@179.237.81.250, /srv/avf-intern/app. Das Skript sichert Code und
MariaDB-Datenbank avf_intern, installiert die Forum-Migration, sammelt statische
Dateien und startet avf-intern neu. Keine neuen Python-Abhängigkeiten.
Bei Fehlern wird der gesicherte Code zurückkopiert. Neue Datenbanktabellen
bleiben erhalten; es erfolgt kein automatischer Datenbank-Restore oder Löschen
von Forum-Daten. Vor einem erneuten Versuch Migration und Fehlermeldung prüfen.

Nach der Installation eine echte Ausgabe als Web-X/Admin hochladen und eine
Antwort mit einem zweiten Konto testen. Der produktive SMTP-Versand wird durch
die lokalen Tests nicht verifiziert.
