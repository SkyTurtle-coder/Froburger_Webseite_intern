# Test System Status

## Current Operating Rule

`test.avfroburger.ch` is not approved as an isolated staging system. Until
separate database and runtime isolation are confirmed, use only explicitly
read-only checks there. Do not deploy, modify WordPress content, run cache or
WP-CLI write commands, or use browser-based admin changes.

## Deployment Policy

After isolation is confirmed, the standard deploy path is a minimal copy of
explicitly identified files. `deploy-test.ps1` requires `-ChangedFiles` for
this mode and delegates each file to the validated single-file deploy helper.

`-FullMirror` is an exceptional, high-risk mode. It must be explicitly passed
and retains the existing `rsync --delete` behavior and exclusions for uploads,
cache, upgrade data, backups, and `wp-config.php`. Both modes reject a target
that differs from the configured test host, target directory, transfer
directory, or verification URL.

## Local Operations History

Detailed environment topology, historical incidents, exact server paths, and
session logs are retained locally in `OPERATIONS-HISTORY.local.md`. That file
is intentionally ignored and must not be committed.

Previously committed operational details remain available in Git history. This
forward-looking trim is not a Git-history rewrite.

## Manual Decisions

The previous incident notes and topology details remain locally available for
operators. Their retention period and any move to a restricted-access runbook
require an operational owner decision.
