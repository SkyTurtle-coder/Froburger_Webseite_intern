# Zeitangabe s.t. / c.t.

Im Anlassformular steht nach Beginn das optionale Feld Zeitangabe mit den
Werten Ohne Zusatz, s.t. und c.t. Bestehende Anlässe erhalten keine automatische
Zuordnung. Die eingegebene Uhrzeit bleibt unverändert; auch Kalenderexporte
verschieben den Beginn nicht. Es gibt keine automatische Erklärung oder Legende.

Die öffentlichen APIs liefern das optionale Feld `start_timing` mit `st`, `ct`
oder leerem String. WordPress akzeptiert nur diese Werte und zeigt den Zusatz
auf den Anlasskarten, den Detailseiten und den Startseiten-Terminen. Ältere
API-Antworten und Cache-Einträge ohne das Feld funktionieren weiterhin.

## Geänderte Laufzeitdateien

Django:
- events/models.py
- events/forms.py
- events/admin.py
- events/public_views.py
- events/migrations/0010_event_start_timing.py
- templates/events/event_list.html
- templates/events/public_event_detail.html
- templates/core/dashboard.html

WordPress, unter wp-content/plugins/avf-events-integration/includes/:
- class-avf-events-api-client.php
- class-avf-events-view-helpers.php
- class-avf-events-list-shortcode.php
- class-avf-upcoming-events-shortcode.php
- class-avf-event-detail-shortcode.php

Für die Live-Übernahme beide Anwendungen aktualisieren. Auf Django die Migration
`manage.py migrate events --noinput` mit der produktiven Umgebung ausführen und
den Dienst neu starten. WordPress-Anlasscache mit
`wp eval 'AVF_Events_API_Client::clear_cache();'` sowie vorhandene Seitencaches
leeren. Danach bei einem Anlass s.t./c.t. auswählen und die unveränderte Uhrzeit
auf Übersicht und Detailseite prüfen. Diese Änderung ist noch nicht live installiert.

## Prüfungen

`python manage.py test events --noinput`

PHP CLI: `php wp-content/plugins/avf-events-integration/tests/start-timing-check.php`
