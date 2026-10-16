#!/bin/sh
# Accepts "IMAGE ./salvage IN OUT", "IMAGE /salvage IN OUT" and "IMAGE IN OUT";
# no arguments shows help.
if [ "$#" -eq 0 ]; then
    exec /app/salvage --help
fi
case "$1" in
    ./salvage|/salvage|salvage|/app/salvage) shift ;;
esac
exec /app/salvage "$@"
