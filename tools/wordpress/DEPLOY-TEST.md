# WordPress Test Deploy

Dieser Ablauf deployt den lokalen Stand aus `public/` nach
`test.avfroburger.ch`, ohne host-lokale Konfiguration zu ueberschreiben.

## Regeln

- `wp-config.php` wird niemals deployed.
- `wp-content/uploads/` wird niemals deployed.
- `wp-content/upgrade/`, `wp-content/cache/` und
  `wp-content/backups-dup-lite/` bleiben host-lokal.
- Dateirechte werden nach dem Sync serverseitig auf Webserver-taugliche Werte
  normalisiert.
- Die Verifikation laeuft gegen `https://test.avfroburger.ch/mitglieder/`.

## Voll-Deploy ausfuehren

```powershell
powershell -ExecutionPolicy Bypass -File .\intern\tools\wordpress\deploy-test.ps1
```

## Was das Voll-Deploy-Script tut

1. Baut lokal ein Staging-Verzeichnis ohne `wp-config.php` und ohne volatile
   host-lokale Verzeichnisse.
2. Laedt dieses Staging per `scp -r` nach `/home/avfrobur/deploy-tmp/public`.
3. Synchronisiert auf dem Server per `rsync --delete` nach
   `/home/avfrobur/www/newton/test`.
4. Setzt Verzeichnisrechte auf `755`, Dateirechte auf `644` und
   `wp-config.php` auf `640`.
5. Fuehrt `wp cache flush` und `wp transient delete --all` aus.
6. Fuehrt `wp elementor flush-css` nur aus, wenn das Kommando auf dem Server
   tatsaechlich verfuegbar ist.
7. Verifiziert die Seite per `curl` mit Cache-Buster.

## Minimal-Deploy fuer einzelne Dateien

Fuer kleine Aenderungen an Plugin-, Theme- oder CSS-Dateien ist ein
Einzeldatei-Deploy robuster als manuelles `scp`, weil das Repo-Skript die
Zielpfade validiert und anschliessend den WordPress-Nachlauf kontrolliert
ausfuehrt.

Ausfuehren:

```powershell
powershell -ExecutionPolicy Bypass -File .\intern\tools\wordpress\deploy-test-file.ps1 `
  -LocalFile "C:\Users\phili\Local Sites\av-froburger\app\public\wp-content\plugins\avf-site-styles\assets\css\site-fixes.css" `
  -RemoteRelativePath "wp-content/plugins/avf-site-styles/assets/css/site-fixes.css" `
  -VerifyUrl "https://test.avfroburger.ch/ueber-uns/"
```

Das Skript:

1. blockiert `wp-config.php` und `wp-content/uploads/`
2. prueft serverseitig, dass die WordPress-Root gueltig ist
3. setzt Dateirechte auf `644`
4. fuehrt `wp cache flush` und `wp transient delete --all` aus
5. versucht `wp elementor flush-css`, behandelt einen Fehlschlag dort aber als
   separaten Folgefehler
6. ruft danach die Ziel-URL mit Cache-Buster auf und gibt den HTTP-Header aus

## Diagnose

Auf diesem Hostpoint-Testsystem war `/home/avfrobur/logs/error.log` am
13. August 2026 nicht vorhanden. Fuer Sofortdiagnosen deshalb primaer nutzen:

- `wp-content/debug.log`
- `wp --debug ...`
- `curl -I https://test.avfroburger.ch/...`

## Wichtiger Hinweis

Falls `test.avfroburger.ch` eine eigene Datenbank oder eine eigene
`wp-config.php` verwendet, muss diese Datei einmalig korrekt auf dem Server
vorhanden sein. Das Deploy-Script ueberschreibt sie bewusst nicht.
