#!/bin/bash
# Local SSH configuration is deliberately excluded from Git.
if [[ -f .local/remote-build.env ]]; then
    source .local/remote-build.env
fi
: "${EDGLANTINE_BUILD_HOST:?Set EDGLANTINE_BUILD_HOST or create .local/remote-build.env}"
EDGLANTINE_REMOTE_ROOT=${EDGLANTINE_REMOTE_ROOT:-/tmp/edglantine-ps5-build}
# These arguments also cross SSH's remote shell; reject shell metacharacters.
[[ $EDGLANTINE_BUILD_HOST =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.@-]*$ ]] || exit 2
[[ $EDGLANTINE_REMOTE_ROOT =~ ^/[a-zA-Z0-9_./-]+$ ]] || exit 2
