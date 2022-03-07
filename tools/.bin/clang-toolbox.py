#!/usr/bin/env python3

# NOTE: Use `semver` from the following git repo or a newer version.
#  git+https://github.com/python-semver/python-semver.git@3.0.0-dev.3

# Internal Imports
#...

# External Imports
# try:
# 	from elftools.elf.elffile import ELFFile
# except:
# 	import sys
# 	print(
# 		"Error: `pyelftools v0.28+ is required for this application.`",
# 		"Info: To install, run `python -m pip install pyelftools>=0.28`",
# 		file=sys.stderr
# 	)
try:
	from semver.version import Version as semver
except:
	import sys
	print(
		"Error: `semver v3+` is required for this application.",
		"Info: To install, run `python -m pip install semver>=3`.",
		file=sys.stderr
	)
	exit(1)
try:
	from pgpy import PGPSignature, PGPKey
	_has_PGPy = True
except:
	_has_PGPy = False
	import sys
	print(
		"Warning:",
		"\tPGPy is not installed. `clang-toolbox` will be unable to",
		"\tverify that downloaded binaries are secure and stable.",
		file=sys.stderr
	)

# Standard Imports
from argparse import ArgumentParser
from tempfile import TemporaryFile
from urllib.request import urlopen
from urllib.parse import urlparse
from shutil import copyfileobj
from shlex import shlex
from pathlib import Path
import platform
import locale
import math
import curses
import tarfile
import json
import re, os, stat, sys, io
import pprint


# This maps all the different input names associated with each clang tool to
# it's initial path within the binary builds.
# NOTE: NOTE: NOTE: NOTE: NOTE: NOTE: /bin/ filenames reside in the same
# location between all supported UNIX binary builds; OSes and architectures!
# This simplifies my work a whole fucking shitload. Even Apple is reasonable.
# Still don't know about Winderps though and I imagine that's going to be
# the ugly duckling of the bunch.
entry_map = (
	(
		("ClangFormat", "Clang Format", "clangformat", "clang-format"),
		(
			Path("bin","clang-format"),
			Path("bin","git-clang-format")
		)
	),
	(
		("ClangTidy", "Clang Tidy", "clangtidy", "clang-tidy"),
		(
			Path("bin", "clang-tidy")
		)
	),
	(
		("ClangCheck", "Clang Check", "clangcheck", "clang-check"),
		(
			Path("bin", "clang-check")
		)
	),
)

__dirname__=Path(__file__).parent
_openpgp_api_url = "https://keys.openpgp.org/vks/v1"
_COPY_BUFSIZE = 64 * 1024 # 1024 * 1024 if _WINDOWS else 64 * 1024
_IEC_PREFIX = ["B","KiB","MiB","GiB","TiB","PiB","EiB","ZiB","YiB"]
_unknown = "unknown"


# https://rust-lang.github.io/rfcs/0131-target-specification.html
# http://0pointer.de/blog/projects/os-release.html
# NOTE: Mentioned above, /etc/os-release is vaguely standard. Should work in
#   most if not all cases. It's therefor reliable enough that I feel safe using
#   it.
# NOTE: These are the supported CPU archetectures with associated flags in
#   pyelftool v0.28; I just realized that some architectures names provided by
#   clang's volunteer build team are totally bonkers. They're unorganized so
#   some people are using different arch labels for the same arch. UGH.
#   Here's the plan. Naturalize the clang naming conventions by returning
#   the target triple (or quartet) in split fashion, and doing a multi-pass
#   for the arch when comparing available cloud builds. This information
#   should be encoded explicetly using rust's internal platform support list.
#   https://doc.rust-lang.org/nightly/rustc/platform-support.html
#
#   (;n;) This makes me sad, I can't wait for the volunteer team to be
#   restricted with their build stuff. They NEED TO HAVE UNIFORM NAMES
#   STANDARDS HELP PEOPLE GOD DAMMIT.
#
# _DESCR_E_MACHINE = dict(
# 	EM_NONE='None',
# 	EM_M32='WE32100',
# 	EM_SPARC='Sparc',
# 	EM_386='Intel 80386',
# 	EM_68K='MC68000',
# 	EM_88K='MC88000',
# 	EM_860='Intel 80860',
# 	EM_MIPS='MIPS R3000',
# 	EM_S370='IBM System/370',
# 	EM_MIPS_RS4_BE='MIPS 4000 big-endian',
# 	EM_IA_64='Intel IA-64',
# 	EM_X86_64='Advanced Micro Devices X86-64',
# 	EM_AVR='Atmel AVR 8-bit microcontroller',
# 	EM_ARM='ARM',
# 	EM_AARCH64='AArch64',
# 	EM_BLACKFIN='Analog Devices Blackfin',
# 	EM_PPC='PowerPC',
# 	EM_PPC64='PowerPC64',
# 	RESERVED='RESERVED',
# )
def loose_target_triple():
	# TODO: Use elftools and os-release to generate this.
	#   The ELF Header and Attribute Section can properly classify ARM distros.
	#   may need a better method for Solaris and legacy / older Linux distros.
	#   Pretty much what "readelf -Ah" tell you. Look up / reverse engineer
	#   https://github.com/eliben/pyelftools/blob/master/scripts/readelf.py
	#   It's a reimplementation of the binutils version using 'pyelftools'.
	arch=_unknown; vendor=_unknown; types=_unknown; env=_unknown;
	try:
		with open(sys.executable, 'rb') as f:
			elf=ELFFile(f)
			arch_enum = elf.header["e_machine"]
	except:
		# If reading the ELF file failed, then fallback to python internals.
		arch=platform.machine()
		if len(arch) == 0: arch=_unknown

	try:
		os_release = parse_envlikeconf("/etc/os-release")
		os_release["ID"] = [os_release["ID"]]
		os_release["ID"] += os_release["ID_LIKE"].split(" ")
		del(os_release["ID_LIKE"])
		# REEEEEEEEEEEEEEEEEEEEEEEEE
		# There's no VERSION_ID_LIKE which makes cross compatability between
		# impossible for the most part. I'm gonna email freedesktop.org and see
		# if I can't open an RFC about this or something. I've come across this
		# multiple times and I'm getting really annoyed.
	except:
		pass

	return (arch, vendor, types, env)

def _IEC_bformat(size, prefix=None):
	if size == 0: return (0, "B")
	pow = math.floor(math.log(size) / math.log(1024))
	return (size/(1024**pow), _IEC_PREFIX[pow])

def first(func, iter):
	return filter(func, iter).__next__()

def _read_http_headers(resp):
	rlen = resp.getheader("content-length")
	rname = resp.getheader("content-disposition")
	if rname.startswith("attachment"):
		rname = rname.removeprefix("attachment").lstrip(" ;")
		if rname.startswith("filename"):
			rname = rname.removeprefix("filename").lstrip(" =")
			rname = rname.removeprefix('"').removesuffix('"')
		else:
			rname = Path(urlparse(resp.url).path).name
	else:
		rname = Path(urlparse(resp.url).path).name

	return rname, rlen

def copyfileobjwstatus(fsrc, fdst, fname, fbs, buflen=0):
	"""copy data from file-like object fsrc to file-like object fdst.
	Additionally, when stdout is a tty, print a progress bar headed by name."""
	if not buflen:
		buflen = _COPY_BUFSIZE
	fsrc_read = fsrc.read
	fdst_write = fdst.write
	bytes_moved = 0
	if os.isatty(2):
		# 13 + 22 = 34 ; 80 - 34 = 46
		fname = (fname[:46]+"..." if len(fname) > 49 else fname.ljust(49, " "))
		print(f"Copying: {fname} , Size: {fbs}", file=sys.stderr)
		while True:
			buf = fsrc_read(buflen)
			if not buf:
				break
			fdst_write(buf)
			quotient = (fbs/bytes_moved)
			percent = 100*quotient
			qf = floor(quotient)
			sys.stderr.write(f"\r{' '*80}\r")
			sys.stderr.write(
				f"{'#'*(70*qf)}{' '*(70-(70*qf))} % {str(percent)[:7]}"
			)

		sys.stderr.write("\n\r")
	else:
		while True:
			buf = fsrc_read(buflen)
			if not buf:
				break
			fdst_write(buf)

def extract_with_stream(b_url, archive_paths, dir=Path.cwd()):
	"""Extracts binary `archive_paths` from the `url` provided. URL must be an
	archive of some type.
	"""
	rname=None; rlen=None; dir=Path(dir); resolved=[]; passes=0; tc=0; ts=0
	with urlopen(b_url) as resp:
		if rlen is None: rname, rlen = _read_http_headers(resp)
		# NOTE: compression method discovery handled by Python STDLIB
		tf = tarfile.open(rname, "r|*", resp)

		archive_paths = [
			(Path(rname.removesuffix(".tar.xz")) / t) for t in archive_paths
		]

		for entry in tf:
			entry_path = Path(entry.name)
			local = dir / entry_path.name;
			if entry_path not in archive_paths:
				sys.stderr.write(f"{' '*80}\rSkipped: {tc} entries, totaling")
				sys.stderr.write(" {0:3f}{1}\r".format(*_IEC_bformat(ts)))
				tc += 1; ts += entry.size
				continue;
			else:
				sys.stderr.write(f"\n{' '*80}\rExtracting: {local.name}\n\r")

			with tf.extractfile(entry) as ff:
				with open(local, "wb") as ft:
					copyfileobj(ff, ft)

		sys.stderr.write("\n")
		tf.close()

def extract_with_file(
		build_url,
		archive_paths,
		signature_url=None,
		volatile=False,
		dir=Path.cwd()
	):
	rname=None; rlen=None; key=None; sig=None; dir=Path(dir)
	with (io.BytesIO() if volatile else TemporaryFile()) as tf:
		with urlopen(build_url) as resp:
			rname, rlen = _read_http_headers(resp)
			copyfileobjwstatus(resp, tf, rname, rlen)

		tf.seek(0)

		if s_url is not None:
			with urlopen(signature_url) as resp:
				sig = PGPSignature.from_blob(resp.read())

			# Query OpenPGP database for keys since I don't want to interact
			# with local GNUpg / other database jargon...
			with urlopen(f"{_openpgp_api_url}/by-keyid/{sig.signer}") as resp:
				key = PGPKey.from_blob(resp.read())

			# Note: Refactor when verify can accept a file. This is a bit
			#   rediculous tbh. Each blob rn is about .5 GiB; too much to
			#   reasonably put in ram.
			key.verify(tf.read(), signature=sig)

		tf.seek(0)

		with tarfile.open(rname, "r:*", tf) as ttf:
			ttf.extractall(dir, [tff.getmember(p) for p in archive_paths])

def tuigui_selector(stdscr, options):
	curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
	curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)
	stdscr.clear()

	max_height, max_width = stdscr.getmaxyx()
	index = 0
	windows = []
	optc = len(options) - 1
	for row, option in enumerate(options):
		win = stdscr.derwin(1, max_width, row + 4, 0)
		win.addstr(0, 0, option["name"])
		windows.append(win)

	stdscr.addstr(0, 0, "Please select the build below that best matches your system.")
	stdscr.addstr(1, 0, "To navigate use the arrow keys or WASD. Enter or space will select the build.")
	stdscr.addstr(2, 0, "In the absence of a proper build, press 'q' to exit; you will have to build from source.")

	windows[index].bkgd(' ', curses.color_pair(2))
	while True:
		key = stdscr.getch()
		windows[index].bkgd(' ', curses.color_pair(1))
		windows[index].refresh()
		if key == curses.KEY_UP or key == ord('w'):
			index = ( index - 1 if index > 0 else 0 )
		elif key == curses.KEY_DOWN or key == ord('d'):
			index = ( index + 1 if index < optc else optc )
		elif key == curses.KEY_ENTER or key == ord(' '):
			return options[index]
		elif key == ord('q'):
			return None
		windows[index].bkgd(' ', curses.color_pair(2))
		windows[index].refresh()
		curses.doupdate()

def _newest_major_remote_clang_version(json):
	full = None
	for v in json:
		full = semver.parse(v["tag_name"].removeprefix("llvmorg-"))
		if full.prerelease is None: break;
	return semver(full.major, 0, 0)

def fetch_clang_build_url(target_version):
	options = {};
	arch = os.uname().machine
	# XXX: this has become so hacky that this probably isn't portable...
	#      I hate writing code like this, but I'm annoyed so IDFC rn
	# os = subprocess.run(["uname", "-o"],
	# 	text=True,
	# 	capture_output=True,
	# 	check=True,
	# ).stdout
	# os = os.lower().strip().replace("/", "-")
	# if os.startswith("gnu"):
	# 	os= os.split("-")
	# 	os.reverse()
	# 	os= "-".join(os)
	select_clang = lambda x: x["name"].startswith("clang+llvm-");
	select_tarballs = lambda x: x["name"].endswith(".tar.xz");
	select_not_sha = lambda x: not x["name"].endswith(".sha256");

	github_api_url = 'https://api.github.com/repos/llvm/llvm-project/releases';
	with urlopen(github_api_url) as resp:
		releases = json.load(resp)

		if target_version is None:
			target_version = _newest_major_remote_clang_version(releases)

		for release in releases:
			ver = semver.parse(release["tag_name"].removeprefix("llvmorg-"));
			# if target is None: target = semver(ver.major, ver.minor)

			# Select only versions of the same feature updates of the same
			# API version. Patches will be filtered later. Exclude prereleases
			if target_version.major > ver.major:
				continue
			elif ver < target_version:
				break
			elif ver >= target_version and ver.prerelease is None:
				clangbuilds = filter(select_clang, release["assets"])
				for build in clangbuilds:
					signature = build["name"].removeprefix("clang+llvm-"+str(ver))
					if signature not in options.keys():
						options[signature] = build



	# this is kinda hacky and I"m too tired of this shit to care
	options = list(options.values())
	options.sort(key=lambda x: x["name"])
	tarballs = list(filter(select_tarballs, options))

	selected = curses.wrapper(tuigui_selector, tarballs)

	if selected is None:
		return (None, None)

	def sigfilter(x):
		return x["name"].startswith(selected["name"]) \
		   and x["name"] != selected["name"]

	signopts = list(filter(sigfilter, options))
	# Try PGP signature first, if not PGP fall back to SHA256
	sign = first(lambda x: x["name"].endswith(".sig"), signopts)
	if sign is None:
		sign = first(lambda x: x["name"].endswith(".sha256"), signopts)

	if sign is not None:
		sign = sign["browser_download_url"]

	return (selected["browser_download_url"], sign)

def parse_envlikeconf(filename):
	hashmap = {}
	with open(filename, "rt") as f:
		tokenizer = shlex(f, posix=True, punctuation_chars=True)
		tokenizer.whitespace=" \t\n;";
		lineno = 0;
		for token in tokenizer:
			eq = token.find("=");
			if eq > -1: hashmap[token[:eq]] = token[eq+1:]
	return hashmap

if __name__ == "__main__":
	locale.setlocale(locale.LC_ALL, '')
	code = locale.getpreferredencoding()

	parser = ArgumentParser(
		description="""A script to download the latest clang utilities."""
	)

	parser.add_argument("-u", "--unsigned",
		help="""Downloads the binaries without cryptographic PGP verification.
		Additionally, ignores the absence of the PGPy library when unavailable.
		""",
		action="store_true",
		dest="unsigned",
	)

	parser.add_argument("-X", "--extraction-mode",
		help="""Which method this script will use to extract the target tools.
		 * tempfile(default): Store the full clang build in a tempfile before
		   extracting each tool.
		 * ramfile: Store the full clang build in RAM and extract each tool.
		   removes extrenious disk reads and writes, on systems with enough
		   ram which can improve the longevity of devices using emmc-flash.
		 * stream: Extracts each tool directly from the download stream.
		   Since the full binary won't be stored on the system, this option
		   implies `--unsigned` and PGP verification will be unavailable.
		   This option is specifically tailored to low-memory systems which
		   don't have enough disk space to store the whole binary tarball.
		   It sacrifices security for disk space. Has the same benefits as
		   `-X ramfile`
		""",
		choices=["stream", "ramfile", "tempfile"], dest="mode"
	)

	parser.add_argument("-o", "--output-dir",
		help="""Output to the provided DIR instead of the path where this
		script is located. Program will error out if PATH doesn't exist.
		""",
		action="store", type=Path, default=__dirname__, dest="path",
	)

	parser.add_argument("-V", "--target-version",
		help="""Specify what Clang version your repository uses. If unspecified,
		clang-toolbox will use the latest version available for your system.""",
		action="store", type=semver.parse, default=None, dest="version"
	)

	parser.add_argument("toolnames",
		help="""The names of the tools you desire to fetch from the toolbox.
		Tool names are case insensitive and are used as found in each release's
		documentation.""",
		nargs="+"
	)

	args = parser.parse_args()

	# Ensure we do things as securely as possible unless the user requests
	# otherwise of the program.
	if args.mode != "stream":
		if _has_PGPy is False and args.unsigned is False:
			print(
				"Error: Signature verification is unavailable. Missing PGPy!",
				"Info: To install, run `python -m pip install PGPy>=5.4`.",
				"Info: To proceed without verification, use `--unsigned`.",
				file=sys.stderr,
			)
			exit(1)

	targets = [];
	for toolname in args.toolnames:
		for entry in entry_map:
			if toolname in entry[0]:
				targets += entry[1]

	# TODO: string things together.
	# NOTE: Will need to refactor later when automated selection is possible.
	build, signature = fetch_clang_build_url(args.version)
	key = None

	if build is None:
		# TODO: log that the user will need to build from source, as there was
		#   no build available / found for their system.
		exit(1)

	if signature is None and args.unsigned is False:
		# TODO: check if stdin and stdout are tty, if yes, request user input
		#   to continue, otherwise request that they use --unsigned and re-run
		#   the program.
		exit(1)

	if args.mode == "stream":
		extract_with_stream(build, targets, args.path)
	elif args.mode == "ramfile":
		extract_with_file(build, targets, signature, True, args.path)
	elif args.mode == "tempfile":
		extract_with_file(build, targets, signature, False, args.path)

	# Change extracted file modes
	for p in targets:
		local = args.path / p.name
		st = os.stat(local)
		os.chmod(local, st.st_mode | stat.S_IEXEC)
