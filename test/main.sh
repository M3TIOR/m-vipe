#!/bin/sh

SELF="$(readlink -nf "$0")";
PROCDIR="$(dirname "$SELF")";

$PROCDIR/../tools/build.sh

# NOTE:
#  While I normally don't like auto-manual testing like this, so I'll probably
#  move to Python Strategies if the C version of Hypothesis isn't deployable
#  yet. But first this needs to have at least some kind of testing in-place.

# Ensure variables are being passed through correctly.
$PROCDIR/../build/
