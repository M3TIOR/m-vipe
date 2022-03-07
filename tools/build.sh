#!/bin/sh -e

SELF="$(readlink -nf "$0")";
PROCDIR="$(dirname "$SELF")";

help(){
	echo "Usage: build.sh [-R]";
	echo "       build.sh --update-gnulib";
	echo;
}

update_gnulib_modules()
(
	cd "$PROCDIR/../deps";
	if ! command -v gnulib-tool; then
		if ! test -d .gnulib-source; then
			echo "Couldn't find a local copy of gnulib, fetching...";
			git clone https://git.savannah.gnu.org/git/gnulib.git .gnulib-source;
		fi;
		if ! test -x .gnulib-source/gnulib-tool; then
			cd .gnulib-source;
			make;
			cd ..;
		fi;
		PATH="$PWD/.gnulib-source:$PATH";
	fi;

	cd gnulib;
	{
		echo "AC_INIT([depme], [0.0.1], [m3tior@users.noreply.github.com])";
		echo "AM_INIT_AUTOMAKE([-Wall -Werror foreign])";
		echo "AC_PROG_CC";
		echo "gl_EARLY";
		echo "AC_CONFIG_MACRO_DIRS([m4])";
		echo "AC_CONFIG_HEADERS([config.h])";
		echo "AC_CONFIG_FILES([";
		echo "  Makefile";
		echo "  lib/Makefile";
		echo "])";
		echo "gl_INIT";
		echo "AC_OUTPUT";
	} > configure.ac;
	{
		echo "AUTOMAKE_OPTIONS = foreign";
		echo "SUBDIRS = lib";
		echo "bin_PROGRAMS = depgen";
		echo "EXTRA_DIST = m4/gnulib-cache.m4";
	} > Makefile.am;

	gnulib-tool --import \
		assert-h limits-h minmax stat-size verify intprops crypto/af_alg \
		full-read full-write safe-alloc safe-read safe-write \
		xalloc xalloc-die xvasprintf ialloc idx;

	# Generates config and other necessary build files using automake
	aclocal;
	automake --add-missing || true;
	autoreconf;
	./configure;

	cd lib;
	# XXX: This is extremely hacky. Could break if package maintainer shifts the
	#      naming conventions of the configuration files around.
	CONFIGS="$(ls -f1 *.in.h)";
	make $(echo "$CONFIGS" | sed -E 's/(.*)\.in\.h/\1.h/g' | tr "_" "/");
	rm -f $CONFIGS;
	cd ..;

	ln -fsT lib gnulib;

	# Squeaky Clean, removes all automake garbage for easy maintenance and
	# consistency.
	rm -rf \
		config.h.in config.log config.guess config.sub config.status \
		missing depcomp install-sh \
		m4 autom4te.cache aclocal.m4 \
		configure.* configure \
		Makefile.* Makefile \
		stamp-h1 lib/.deps;

	{
		echo "cmake_minimum_required(VERSION 3.10)";
		echo "project(gnulib VERSION 0.0.0 LANGUAGES C)";

		# TODO: remove msvc or make their addition to the library conditional
		#       for now, best option is to filter because Windows doesn't support
		#       a lot of the library functions I'm using.
		SOURCES=$(ls -f1 lib/*.c | {
			while read line; do
				test "$line" != "${line#lib/msvc}" || \
				test "$line" != "${line#lib/windows}" || \
				echo "$line";
			done;
		});
		echo "add_library(gnulib OBJECT $SOURCES)";
		echo "target_include_directories(gnulib PUBLIC . lib)";
	} > CMakeLists.txt;
)

while test "${#}" -gt 0; do
	case "$1" in
		"-P"|"--production");; # TODO: implement production build. make use of cmake --target clean; post
		"-R"|"--rebuild-cmake") CLEANCMAKE="true";;
		"--update-gnulib") update_gnulib_modules; exit;;
		*) echo "Error: unknown argument '$1'" >&2; exit 1;;
	esac;
	shift;
done;

if ${CLEANCMAKE:-false}; then rm -rf "$PROCDIR/../build"; fi;
mkdir "$PROCDIR/../build" || true;
cd "$PROCDIR/../build";

if cmake ..; then
	cmake --build . || true;

	# TODO: fix cmake build and remove this l8r.
	echo "Running GCC...";
	gcc -ggdb -o vipe $(find . -name *.o -print) -lm
	echo "DONE";
fi;
