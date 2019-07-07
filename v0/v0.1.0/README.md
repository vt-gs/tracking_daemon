# Tracking Daemon v0.1.0

This is the last version of the tracking daemon from the old 'tracking' repo.  Uses the 'VTGS Tracking Protocol' (VTP) which is a simple comma delimited ASCII format for comms between the client and the daemon.  This was originally called 'v2.1'.  Keeping a copy in this repo as a reference and modifying slightly to work with updated MD-01 Firmware.

v0.1.0 includes updates mainly to the logging features of the daemon.  The old version was used with 'upstart' which redirected the print statements (STDOUT) to daemon logs.  For finer control of the logging, the print statements have been replaced with the python logging module.  Additionally, uses a new thread control structure, also uses new JSON config file feature instead of command line options.

Companion Client:  https://github.com/vt-gs/tracking_client/tree/master/v0/v0.1.0
