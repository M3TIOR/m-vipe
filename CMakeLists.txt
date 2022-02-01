cmake_minimum_required(VERSION 3.10)

project(m-vipe VERSION 0.1.0)

# NOTE: options must happen before paths are added, because option values
#       are used at read-time, not build time. subdirectory is like #include
#       These have to be here because we only want the object file / standalone
option(ARGPARSE_SHARED "Argparse shared library" OFF)
option(ARGPARSE_STATIC "Argparse static library" OFF)
add_subdirectory(deps)

option(C_STANDARD_REQUIRED "C target standard must not decay" ON)
add_executable(m-vipe src/main.c)
set_property(TARGET m-vipe PROPERTY C_STANDARD 17)
target_compile_options(m-vipe BEFORE PUBLIC "-ggdb")
target_link_options(m-vipe PUBLIC "-lm")

# TODO: NOTE: XXX:
#    THIS OF ALL THINGS WORKS: gcc -ggdb -o vipe $(find . -name *.o -print) -lm
#    FIGURE OUT WHY THE FUCK CMAKE ISN'T DOING IT'S JOB!!!!!
#
# gdb

configure_file(src/m-vipe.h.in m-vipe.h)

target_link_libraries(m-vipe PUBLIC
	argparse
	gnulib
)

target_include_directories(m-vipe PUBLIC
	"${PROJECT_BINARY_DIR}"
	"${PROJECT_SOURCE_DIR}/deps/argparse"
	"${PROJECT_SOURCE_DIR}/deps/gnulib"
#	"${PROJECT_SOURCE_DIR}/deps/gnulib/lib"
)
