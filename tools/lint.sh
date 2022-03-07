#!/bin/sh
# @file - lint.sh
# @brief - A script to simplify the linting process for the project.
# @copyright - (C) 2021  Ruby Allison Rose
# SPDX-License-Identifier: MIT

################################################################################
## Globals (Comprehensive)
SELF="$(readlink -nf "$0")";
PROCDIR="$(dirname "$SELF")";

################################################################################
## Imports

################################################################################
## Functions

# @describe - Tokenizes a string into semver segments, or throws an error.
tokenize_semver_string(){
	s="$1"; l=0; major='0'; minor='0'; patch='0'; prerelease=''; buildmetadata='';

	# Check for build metadata or prerelease
	f="${s%%[\-+]*}"; b="${s#*[\-+]}";
	if test -z "$f"; then
		echo "\"$1\" is not a Semantic Version." >&2; return 2;
	fi;
	OIFS="$IFS"; IFS=".";
	for ns in $f; do
		# Can't have empty fields, zero prefixes or contain non-numbers.
		if test -z "$ns" -o "$ns" != "${ns#0[0-9]}" -o "$ns" != "${ns#*[!0-9]}"; then
			echo "\"$1\" is not a Semantic Version." >&2; return 2;
		fi;

		case "$l" in
			'0') major="$ns";; '1') minor="$ns";; '2') patch="$ns";;
			*) echo "\"$1\" is not a Semantic Version." >&2; return 2;;
		esac;
		l=$(( l + 1 ));
	done;
	IFS="$OIFS";

	# Determine what character was used, metadata or prerelease.
	if test "$f-$b" = "$s"; then
		# if it was for the prerelease, check for the final build metadata.
		s="$b"; f="${s%%+*}"; b="${s#*+}";

		prerelease="$f";
		if test "$f" != "$b"; then buildmetadata="$b"; fi;

	elif test "$f+$b" = "$s"; then
		# If metadata, we're done processing.
		buildmetadata="$b";
	fi;

	OIFS="$IFS"; IFS=".";
	# prereleases and build metadata can have any number of letter fields,
	# alphanum, and numeric fields separated by dots.
	# Also protect buildmetadata and prerelease from special chars.
	for s in $prerelease; do
		case "$s" in
			# Leading zeros is bad juju
			''|0*[!1-9a-zA-Z-]*|*[!0-9a-zA-Z-]*)
				echo "\"$1\" is not a Semantic Version." >&2;
			IFS="$OIFS"; return 2;;
		esac;
	done;
	for s in $buildmetadata; do
		case "$s" in
			''|*[!0-9a-zA-Z-]*)
				echo "\"$1\" is not a Semantic Version." >&2;
			IFS="$OIFS"; return 2;;
		esac;
	done;
	IFS="$OIFS";
}

clang_major() {
	clang-format --version | {
		read n v semver extra;
		tokenize_semver_string "$semver";
		printf "%s" "$major";
	}
}

# @describe - Ask user for a yes or no; when $NOPROMPT is set, will use default.
#   Additionally, default option will be uppercase at prompt ie. recommended.
# @arg 1 - Default response one of 0/y/Y for Yes or 1/n/N for No.
#   Leaving this entry blank will force a prompt.
# @arg 2 - Custom prompt; Will appear before "[Yn]:"
prompt_yn(){
	case "$1" in
		[0yY]) default="Yn";;
		[1nN]) default="Ny";;
		*)
			echo "Error: Prompt recieved invalid default argument." >&2;
			exit 2;;
	esac;

	if test -z "$NOPROMPT" && test -n "$default"; then
		answer="$1";
	else
		test -n "$default" || default="yn";
		while read -p "$2 [$default]:" answer; do
			case "$answer" in
				[yY]*|[nN]*) answer="$default"; break;;
				*) echo "Invalid response, please answer Yes or No.";;
			esac;
		done;
	fi;

	case "$answer" in
		[yY]*) return 0;;
		[nN]*) return 1;;
	esac;
}


################################################################################
## Main Script

PATH="$PROCDIR/.bin:$PATH";
if ! command -v clang-format > /dev/null || test "13" != "$(clang_major)"; then
	echo "Error: The Clang Format on your system is incompatable with this" >&2;
	printf "\tproject. Please use version 13 or above.\n" >&2;
	exit 1;
fi;


# Currently using clang-format latest stable to lint; clang-format ~13.0.0
clang-format $*;
