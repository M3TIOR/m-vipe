// TODO: put copyright jargon here in all the necessary files.

// Special Include (Necessary for working with gnulib)
#include <config.h>

// Standard Includes
#include <stdbool.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include <errno.h>
#include <error.h>
#include <stdio.h>
#include <math.h>

// External Includes
#include <unistd.h> // may need to be included before string.h for strdup
#include <spawn.h>
#include <fcntl.h>
#include <limits.h> // ARG_MAX
#include <sys/mman.h>
#include <sys/wait.h>
#include <gnulib/stat-size.h> // TODO: get licensing sorted for gnulib
#include <gnulib/safe-read.h>
#include <gnulib/full-write.h>
#include <gnulib/xalloc.h>
#include <argparse.h>

// Internal Includes
#include <m-vipe.h>
#include "die.h"
#include "ioblksize.h"


/**
 * NOTE: See https://stackoverflow.com/questions/3437404/min-and-max-in-c
 *   for why this implementation is better and should probably be migrated to
 *   gnulib.
 */
#define max(a,b)           \
({                         \
	__typeof__ (a) _a = (a); \
	__typeof__ (b) _b = (b); \
	_a > _b ? _a : _b;       \
})
#define min(a,b)           \
({                         \
	__typeof__ (a) _a = (a); \
	__typeof__ (b) _b = (b); \
	_a < _b ? _a : _b;       \
})
#undef MAX
#undef MIN
#define MAX max
#define MIN min

// NOTE: how large a space we need to contain the following objects
//       using binary growth
#define BINALLOC(size, count) ( \
	size * ((1 << (int) floor(log2((count) * size))) >> 1) \
)


static const char *const usage[] = {
	"m-vipe [-Vwv] [-f FILE] [[--] EDITOR [ARGS...]]",
	"m-vipe [-h] [--version]",
	NULL,
};


// Near clone of simple_cat from coreutils. Thanks for that guys! Makes buffer
// management easier on my end.
int very_simple_cat(const char *action, int infd, int outfd) {
	/* NOTE:
	 *  Lucky for me I'm not really wanting to target all the systems on earth.
	 *  GNU coreutils does a lot of funky stuff in cat.c because some systems
	 *  like Cygwin actually distingquish between BINARY and TEXT io on pipes
	 *  files. Which is a little bit rediculous in C. This cuts out a lot of their
	 *  well intentioned scaffolding in favor of a simpler, easier to maintain
	 *  method.
	 *
	 *  If this ever does get integrated into moreutils or some other
	 *  GNU toolchain, I imagine this will need to get refactored to target
	 *  systems like Cygwin again.
	 */

	size_t page_size = (size_t) sysconf(_SC_PAGESIZE);

	/* Optimal size of i/o operations of input.  */
	size_t insize, outsize;

	struct stat stat_buf;
	stat_buf.st_blksize = 0; // ensure no undefined behavior on fstat error
	fstat (infd, &stat_buf); // this should be fine without error handling
	insize = io_blksize(stat_buf);
	fstat (outfd, &stat_buf);
	outsize = io_blksize(stat_buf);

	// All values herein are MAXed so they should at least default to a decent
	// size. `io_blksize` in gnulib actually has a builtin default. Be careful
	// however, MAX is a macro.
	insize = MAX(insize, outsize);

	char* buf = xmalloc(insize + page_size - 1);

	size_t n_read;
	while (true) {
		n_read = safe_read(infd, buf, insize);
		if (n_read == SAFE_READ_ERROR)
			die(1, errno, action);

		if (n_read == 0) return 0;

		{
			/* The following is ok, since we know that 0 < n_read.  */
			size_t n = n_read;
			if (full_write(outfd, buf, n) != n)
				die(1, errno, action);
		}
	}
}

/**
 * @description - Performs path search, shell argument expansion and
 *   concatenation of variadic string arguments. Will set errno on error.
 *   All errors inherited from realloc and access.
 * @argument str - previously malloc allocated string to add
 * @argument argv - malloc allocated variadic argument container
 * @argument argc - a pointer to the count of variadic arguments contain by argv
 * @return - True when str contained a command found in PATH, false otherwise.
 */
bool shexpaccvar(char **str, char ***argv, size_t *argc) {
	// Use two pass algorithm to decide whether or not we need to extend the
	// variadic args list. Use binary exponential growth when expanding like
	// C++ strings for malloc efficency.

	// TODO: make this function and shpaccvar not fail when user supplied full path.
	if (*str == NULL) return false;

	// NOTE: This isn't actually a "correct" use for IFS. Though it's not very far off.
	//   See: https://web.archive.org/web/20210513070928/http://mywiki.wooledge.org/IFS
	char *ifs = " \t\n";
	char *path = getenv("PATH"); if (path == NULL) path="";
	size_t slenb = strlen(*str) * sizeof(char);
	size_t plenb = strlen(path) * sizeof(char);

	// Count the new arguments after IFS parsing and prep reuse of str in-place
	size_t nc = *argc+1;
	for (char *c, *acc=*str; (c=strpbrk(acc, ifs)) != NULL; acc=c+sizeof(char)) {
		nc++;
		*c = '\0';
	}

	// Extend the argument pointer array if necessary.
	size_t nb = BINALLOC(sizeof(void*), nc+1);
	size_t ob = BINALLOC(sizeof(void*), (*argc)+1);
	if (nb >= ob) {
		if (*argv == NULL)
			*argv = malloc(nb);
		else
			*argv = realloc(*argv, nb);
		if (*argv == NULL)
			return false;
	}

	if (access(*str, R_OK | X_OK) != 0) {
		// Reallocate str to buffer PATH search
		*str = realloc(*str, plenb + slenb + 2*sizeof(char)); // + pathsep & NULL
		if (*str == NULL) return false;

		// NOTE: remove when regression testing is finished.
		*((*str)+plenb+slenb) = '\0'; // append null to reallocated space as a precaution

		// perform PATH search
		char *c, *sloc=*str, *pacc=path;
		for (;(c=strpbrk(pacc, ":")) != NULL; pacc=c+sizeof(char)) {
			// move str value to be in front of path segment, then memcpy path
			// into place.
			plenb = c - pacc;
			sloc=memmove((*str)+plenb+sizeof(char), sloc, slenb+sizeof(char));
			memcpy(*str, pacc, plenb);
			*((*str)+plenb) = '/'; // replace fieldsep with POSIX pathsep

			int s = access(*str, R_OK | X_OK);
			if (s == 0) break;
		}
		// Final pass / when IFS not found
		if (c == NULL) {
			plenb = strlen(pacc) * sizeof(char);
			sloc=memmove((*str)+plenb+sizeof(char), sloc, slenb+sizeof(char));
			memcpy(*str, pacc, plenb);
			*((*str)+plenb) = '/';

			int s = access(*str, R_OK | X_OK);
			if (s == -1) return false;
		}
		slenb += plenb+sizeof(char);
	}

	// Populate args from buffer
	errno=0;
	(*argv)[(*argc)++] = *str;
	for (size_t l=0; l < (slenb/sizeof(char)); l++)
		if ((*str)[l] == '\0')
			(*argv)[(*argc)++] = &((*str)[l+1]);

	(*argv)[*argc] = (char *) NULL;
	return true;;
}

bool shpaccvar(char **str, char ***argv, size_t *argc) {
	// Use two pass algorithm to decide whether or not we need to extend the
	// variadic args list. Use binary exponential growth when expanding like
	// C++ strings for malloc efficency.

	if (*str == NULL) return false;

	char *path = getenv("PATH");
	size_t slenb = strlen(*str) * sizeof(char);
	size_t plenb = strlen(path) * sizeof(char);

	// Extend the argument pointer array if necessary.
	size_t nc = *argc+1;
	size_t nb = BINALLOC(sizeof(void*), nc+1);
	size_t ob = BINALLOC(sizeof(void*), (*argc)+1);
	if (nb >= ob) {
		if (*argv == NULL)
			*argv = malloc(nb);
		else
			*argv = realloc(*argv, nb);
		if (*argv == NULL)
			return false;
	}

	if (access(*str, R_OK | X_OK) != 0) {
		// Reallocate str to buffer PATH search
		*str = realloc(*str, plenb + slenb + 2*sizeof(char)); // + pathsep & NULL
		if (*str == NULL) return false;

		// NOTE: remove when regression testing is finished.
		*((*str)+plenb+slenb) = '\0'; // append null to reallocated space as a precaution

		// perform PATH search
		char *c, *sloc=*str, *pacc=path;
		for (;(c=strpbrk(pacc, ":")) != NULL; pacc=c+sizeof(char)) {
			// move str value to be in front of path segment, then memcpy path
			// into place.
			plenb = c - pacc;
			sloc = memmove((*str)+plenb+sizeof(char), sloc, slenb+sizeof(char));
			memcpy(*str, pacc, plenb);
			*((*str)+plenb) = '/'; // replace fieldsep with POSIX pathsep

			int s = access(*str, R_OK | X_OK);
			if (s == 0) break;
		}
		// Final pass / when IFS not found
		if (c == NULL) {
			plenb = strlen(pacc) * sizeof(char);
			sloc = memmove((*str)+plenb+sizeof(char), sloc, slenb+sizeof(char));
			memcpy(*str, pacc, plenb);
			*((*str)+plenb) = '/';

			int s = access(*str, R_OK | X_OK);
			if (s == -1) return false;
		}
	}

	// Populate args from buffer
	errno=0;
	(*argv)[(*argc)++] = *str;
	(*argv)[*argc] = (char *) NULL;
	return true;;
}

bool pushvar(char **str, char ***argv, size_t *argc) {
	size_t nb = BINALLOC(sizeof(void*) , (*argc)+2);
	size_t ob = BINALLOC(sizeof(void*), (*argc)+1);
	if (nb >= ob) {
		if (*argv == NULL)
			*argv = malloc(nb);
		else
			*argv = realloc(*argv, nb);
		if (*argv == NULL)
			return false;
	}

	errno=0;
	(*argv)[(*argc)++] = *str;
	(*argv)[*argc] = (char *) NULL;
	return true;
}

bool ccvar(char ***toargv, size_t *toargc, char **fromargv, size_t fromargc) {
	size_t nc = (*toargc)+fromargc;

	size_t nb = BINALLOC(sizeof(void*), nc+1);
	size_t ob = BINALLOC(sizeof(void*), (*toargc)+1);
	if (nb >= ob) {
		if (*toargv == NULL)
			*toargv = malloc(nb);
		else
			*toargv = realloc(*toargv, nb);
		if (*toargv == NULL)
			return false;
	}

	for (size_t l=0; *toargc < nc; (*toargc)++)
		(*toargv)[*toargc] = fromargv[l++];

	errno=0;
	(*toargv)[*toargc] = (char *) NULL;
	return true;
}

void passive_error(int verbose, const char* message) {
	switch (errno) {
		case 0: return;
		// TODO: process fatal errors with more vigor, fatals always output.
		case ENOMEM: case EHWPOISON: case ENOSPC:
			error(1, errno, "Fatal: %s", message);
		default:
			if (verbose != 0)
				error(0, errno, "Error: %s", message);
			return;
	}
}

// TODO: limit ramfile size to 128MiB; anything larger is unreasonable
int main(int argc, const char** argv) {
	// int stream = 0;
	int volat = 0;
	int verbose = 0;
	int show_version = 0;
	int new_window = 0;
	const char *frompath = NULL;
	posix_spawn_file_actions_t fact;
	FILE* safp = NULL;
	int safd;

	/* clang-format off */
	struct argparse_option options[] = {
		OPT_GROUP("POSIX Options:"),
		OPT_HELP(),
		OPT_BOOLEAN('\0', "version", &show_version,
			"show the version of this program and exit",
			NULL, 0, 0
		),

		OPT_GROUP("Execution Options:"),
		/* TODO: put this in the following manpages
		 * This implies the `--volatile` option for all editors. If the editor is
		 * `vi` or `vim`, this program will concatenate arguments after COMMAND to
		 * ensure pipe contents are NOT written to the disk; only the output pipe.
		 *
		 * NOTE: pipes in newer linux versions are safe for secrets.
		 * https://unix.stackexchange.com/questions/450877/how-do-pipelines-limit-memory-usage
		 */
		OPT_BOOLEAN('v', "verbose", &verbose,
			"Change the verbosity of the program",
			NULL, 0, 0
		),
		OPT_BOOLEAN('V', "volatile", &volat,
			"Stores the pipe contents being modified completely in volatile memory. (RAM)",
			NULL, 0, 0
		),
		OPT_BOOLEAN('w', "new-window", &new_window,
			"Launches the EDITOR from a new terminal window.",
			NULL, 0, 0
		),
		// TODO: figure out how to require a value for this. May need to fork
		//       the project and add that myself.
		OPT_STRING('f', "from", &frompath,
			"Read from FILE instead of stdin.",
			NULL, 0, 0
		),
		OPT_END()
	};
	/* clang-format on */

	struct argparse argparse;
	argparse_init(&argparse, options, usage, 0);
	argparse_describe(&argparse,
		// Argparse by default uses four spaces instead of literal tabs :/
		"\nDescription:\n"
		"    Edit pipe contents manually with a text editor of your choosing.\n"
		"    When no COMMAND is supplied, will use the environment variable EDITOR.",
		NULL
	);

	argc = argparse_parse(&argparse, argc, argv);


	// TODO: Do safety checks for these allocators
	if (volat != 0) {
		safd = memfd_create("ramfile", 0);
	}
	else {
		safp = tmpfile();
		safd = fileno(safp);
	}

	very_simple_cat("Writing input to storage area", STDIN_FILENO, safd);


	// `/proc/$$/fd/$FD`  8 + log10(! pid_t) + log10(! int)
	char *filename;
	size_t fnamelen = 8 + floor(log10(!((pid_t) 0))) + floor(log10(!((int) 0)));
	filename = malloc(fnamelen * sizeof(char) + sizeof(char)); // + null char
	filename[fnamelen] = '\0';

	// NOTE: linux pid_t is signed int so this should be safe.
	sprintf(filename, "/proc/%d/fd/%d", getpid(), safd);

	{
		pid_t child = -1; int status;
		char **cargv = NULL; size_t cargc = 0;
		char *window = NULL;
		char *editor = NULL;
		int l = 0;

		void memsafety() {
			free(cargv);
			free(window);
			free(editor);
			free(filename);
		}

		atexit(&memsafety);

		// Preset errno to zero as it's basically a non-error and we can use it
		// to check for error throws.
		errno = 0;

		posix_spawn_file_actions_init(&fact);

		/* NOTE:
		 *  Struggling to figure out what we need to do to determine the user's preffered
		 *  Terminal emulator. It seems to be different on every Linux distro. The program
		 *  targeted by TERM isn't even guaranteed to exist...
		 *  SOOOOO I'm gonna do a compat move for Debian
		 *  based distros. Try `$TERM`, then `x-terminal-emulator`. Could also query the
		 *  display environment like GTK, Gnome, KDE so on and so forth.
		 *  GTK: gsettings get org.gnome.desktop.default-applications.terminal exec
		 *       gsettings get org.gnome.desktop.default-applications.terminal exec-arg
		 */
		if (new_window != 0) {
			char *winopts[2]; l=0;
			winopts[0] = getenv("TERM");
			winopts[1] = "x-terminal-emulator";
			do {
				if (winopts[l] == NULL) continue;
				passive_error(verbose, window);
				errno = 0;
				free(window);
				window = strdup(winopts[l++]);
			}
			while (shexpaccvar(&window, &cargv, &cargc) != true && l < 2);
			if (errno != 0) error(1, errno, "Couldn't establish a suitable terminal");
		}
		else {
			// If we're preserving the terminal and not using an alt window, ensure
			// we actually inherit the TTY. But we don't need this when we're using
			// a new window.
			// Open only fd 0 and 1 to TTY, we want to inherit stderr
			posix_spawn_file_actions_addopen(&fact, 0, "/dev/tty", O_RDWR, (mode_t) 0);
			posix_spawn_file_actions_adddup2(&fact, 0, 1);
		}

		if (argc != 0) {
			editor = strdup(argv[0]);
			if (shpaccvar(&editor, &cargv, &cargc) != true)
				error(127, errno, "Editor unavailable");

			if (ccvar(&cargv, &cargc, argv+sizeof(void*), argc-1) != true)
				error(1, errno, "Couldn't rellocate arguments");
		}
		else {
			char *editopts[5]; l=0;
			// For implementation considerations see:
			//   https://unix.stackexchange.com/questions/316856
			editopts[0] = "sensible-editor"; // Try Debian-alikes first
			editopts[1] = getenv("VISUAL"); // Then in order of user friendlyness
			editopts[2] = getenv("EDITOR");
			editopts[3] = "nano";
			editopts[4] = "vi";
			do {
				if (editopts[l] == NULL) continue;
				passive_error(verbose, editor);
				errno = 0;
				free(editor);
				editor = strdup(editopts[l]);
			}
			while (shexpaccvar(&editor, &cargv, &cargc) != true && l++ < 5);
			if (errno) error(127, errno, "Editor unavailable");
		}

		if (pushvar(&filename, &cargv, &cargc) != true)
			error(1, errno, "Couldn't append required storage area argument.");

		// NOTE: execv convention makes argument 0 a redundant copy of the
		//   `program` argument; shifting the array will always ignore the first
		//   entry in the supplied variadic list.
		if (errno = posix_spawn(&child, cargv[0], &fact, 0, cargv, environ) != 0)
			error(1, errno, "Failed to execute");


		await:
		waitpid(child, &status, WCONTINUED);
		if (WIFEXITED(status) != 0) {
			if (verbose != 0) fprintf(stderr, "Info: Child exited normally.\n");
		}
		else if (WIFSTOPPED(status) != 0) {
			fprintf(stderr, "Info: Child stopped, waiting for it to continue.\n");
			goto await;
		}
		else if (WIFCONTINUED(status) != 0) {
			fprintf(stderr, "Info: Child continued, waiting for valid termination.\n");
			goto await;
		}
		else {
			switch(WEXITSTATUS(status)) {
				// TODO: specialize error reporting
				default: exit(1);
			}
		}
	}

	lseek(safd, 0, SEEK_SET);
	very_simple_cat("Writing modified contents to stdout", safd, STDOUT_FILENO);

	return 0;
}
