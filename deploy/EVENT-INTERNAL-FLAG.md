# Optional internal event flag

`Event.is_internal` is a separate boolean, independent of `is_public`.
New events select OFF, INOFF, IAOFF or HOCHOFF and may additionally be internal.
Existing status=INTERN events keep that storage representation; migration 0011
backfills their new flag. All forms omit INTERN from the dropdown. An empty
primary status is valid only with the internal checkbox and is stored as
status=INTERN for compatibility. Existing internal-only events render with an
empty dropdown and the checkbox selected. No additional migration is needed.


The list, detail template and API label show e.g. `Off + Intern`. The API retains
the existing status string and adds an `is_internal` boolean. The existing
homepage exclusion also applies to the new flag. WordPress already displays
the API status_label; no WordPress deployment is needed for that label.

This change does NOT restrict public registration. Public visibility remains
controlled by is_public. A later registration restriction must be enforced in
Django's public signup endpoint, not solely in a WordPress form.

## Deployment requirements

Not deployed automatically. Before enabling the updated application, back up
the production database/code and apply `events.0011_event_is_internal` using
the production service environment. Deploy these files together:

- events/models.py, forms.py, views.py, public_views.py, admin.py
- events/migrations/0011_event_is_internal.py
- templates/events/event_list.html and public_event_detail.html

The change has no dependencies on the pending member-directory or memorial
changes in this checkout. Do not run all unrelated local migrations merely
to deploy this feature. Use the production deployment workflow with a targeted
migration plan and maintenance window. A code-only rollback after migration
needs care: the new non-null database column must remain compatible with old
inserts; do not blindly roll back or drop internal flags entered since launch.

Validation: `python manage.py test events --noinput`; focused coverage lives
in events/tests_internal_flag.py and includes all four combinations, legacy
data, API and homepage rules, create/edit permissions and unchanged signup.

## Prepared production command

Run in local PowerShell from app/intern:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\Deploy-EventInternal.ps1 -Deploy
```

Without -Deploy, only prepares the package. Uses the Debian SSH target and
service environment. Backs up code and MariaDB, checks the exact migration
plan and applies only events.0011. Unrelated server changes stop deployment.
If migration fails partway, the service stays stopped for schema inspection;
no automatic database restore or removal of new data is attempted. After a
successful migration, recovery keeps the new code compatible with the schema.
