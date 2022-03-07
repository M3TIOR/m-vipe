#!/bin/sh

count="$#";
while test "$#" -gt 0; do
	# $(($count - $#))
	# This should be all we need to pass the arguments down
	printf '"%s"' "$1"; shift;
done;
