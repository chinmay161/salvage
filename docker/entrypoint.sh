#!/bin/sh
# Accept both "IMAGE /salvage IN OUT" and "IMAGE IN OUT"; no arguments shows help.
if [ "$#" -eq 0 ]; then
    exec /salvage --help
fi
case "$1" in
    /salvage|salvage) shift ;;
esac
exec /salvage "$@"
