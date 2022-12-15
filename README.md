# GDrive Populator

Replicates text files from local disk to a structure in Google Drive. Intended to be used from a git repo.

# Config
Looks for a YAML file called .gdrive.yaml in the current working directory. These can be specified or overriden
with environment variables

| Config Keys      | Expected values                                          | Environment Variable Name         |
-------------------|----------------------------------------------------------|-----------------------------------|
| base_name        | name for google drive folder as base dir                 | GDRIVEPOPULATOR_BASE_NAME         |
| credentials      | path subkey                                              |                                   |
| credentials.path | path to service account credentials file                 | GDRIVEPOPULATOR_CREDENTIALS__PATH |
| credentials.json | service account info in json string form                 | GDRIVEPOPULATOR_CREDENTIALS__JSON |
| deletion         | one of 'trash', 'dry', 'skip' (default: dry)             | GDRIVEPOPULATOR_DELETION          |
| drive            | name or id subkey                                        |                                   |
| drive.name       | name of the shared drive to replicate to                 | GDRIVEPOPULATOR_DRIVE__NAME       |
| drive.id         | id of the shared drive to replicate to                   | GDRIVEPOPULATOR_DRIVE__ID         |
| logging          | logging config - currently only level subkey             |                                   |
| logging.level    | one of 'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'   | GDRIVEPOPULATOR_LOGGING__LEVEL    |
| matchers         | list of globs to match to find files to replicate        | GDRIVEPOPULATOR_MATCHERS_0...N    |
| excludes         | list of globs to match to exclude files from replication | GDRIVEPOPULATOR_EXCLUDES_0...N    |

For a file to be replicated, in must both match a matcher glob and not match any excludes globs.
