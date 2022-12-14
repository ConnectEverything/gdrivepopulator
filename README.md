# GDrive Populator

Replicates text files from local disk to a structure in Google Drive. Intended to be used from a git repo.

# Config
Looks for a YAML file called .gdrive.yaml in the current working directory

| Config Keys      | Expected values                                          | 
-------------------|----------------------------------------------------------|
| base_name        | name for google drive folder as base dir                 |
| credentials      | path subkey                                              |
| credentials.path | path to service account credentials file                 |
| deletion         | one of 'trash', 'dry', 'skip' (default: dry)             |
| drive            | name or id subkey                                        |
| drive.name       | name of the shared drive to replicate to                 |
| drive.id         | id of the shared drive to replicate to                   |
| logging          | logging config - currently only level subkey             |
| logging.level    | one of 'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'   |
| matchers         | list of globs to match to find files to replicate        |
| excludes         | list of globs to match to exclude files from replication |

For a file to be replicated, in must both match a matcher glob and not match any excludes globs.
