# Tracking Daemon v0

Uses the 'VTGS Tracking Protocol' (VTP) which is a simple comma delimited ASCII format for comms between the client and the daemon.  



## Version Changelog:

### v0.1.0
* Updating logging features of the daemon.  The old version was used with 'upstart' which redirected the print statements (STDOUT) to daemon logs.  For finer control of the logging, the print statements have been replaced with the python logging module.
* Updating thread initialization and control structure.
* updated to use JSON config file.
* See companion tracking_client version:  https://github.com/vt-gs/tracking_client/tree/master/v0/v0.1.0

### v0.0.1
* This is the last version of the tracking daemon from the old 'tracking' repo.  This was originally called 'v2.1'.  Keeping a copy in this repo as a reference.
* Modifying slightly to work with updated MD-01 Firmware. New firmware responds with a 'status' message after the set command.  Updated md01.py to handle this change.
* * See companion tracking_client version:  https://github.com/vt-gs/tracking_client/tree/master/v0/v0.0.1

