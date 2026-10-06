# The runtime as libsoa_runtime.so (specs/android.md 3.1): every runtime/*.c
# with SOA_SDL (the window and sound, L10), SOA_SPLIT (the game comes from
# libsoa_game.so, L12a) and SOA_NO_DECOMP (no decompiled code in the APK,
# distribution 3.1); the seam's runtime side, which tools/android.py writes
# into generated/ from config/seam.txt; and SDL3 from the pinned AAR. The
# version script exports the seam, soa_run and SDL_main, and nothing else;
# the --wrap options send the runtime's own exits through android.c, which
# drains the log first.
cmake_minimum_required(VERSION 3.22)
project(soa C)

set(SOA_TREE ${CMAKE_CURRENT_SOURCE_DIR}/../../../../..)
set(SOA_GENERATED ${CMAKE_CURRENT_SOURCE_DIR}/generated)
# Asked again at every build: a glob is otherwise read once, when the build
# tree is first made, and a runtime file added after it (L12d's import.c) is
# left out of the library until the link fails on its names.
file(GLOB SOA_RUNTIME CONFIGURE_DEPENDS ${SOA_TREE}/runtime/*.c)

find_package(SDL3 REQUIRED CONFIG)

add_library(soa_runtime SHARED ${SOA_RUNTIME} ${SOA_GENERATED}/runtime_seam.c)
target_compile_definitions(soa_runtime PRIVATE SOA_SDL=1 SOA_SPLIT=1 SOA_NO_DECOMP=1 _GNU_SOURCE)
# the gnu profile's flags (tools/soa/toolchain.py): never a contracted multiply-add
target_compile_options(soa_runtime PRIVATE -std=c17 -O2 -ffp-contract=off -fno-strict-aliasing -fwrapv -Wall)
target_include_directories(soa_runtime PRIVATE ${SOA_TREE}/runtime)
target_link_libraries(soa_runtime PRIVATE SDL3::SDL3 log android m dl)
target_link_options(soa_runtime PRIVATE
    -Wl,--version-script=${SOA_GENERATED}/runtime.map
    -Wl,--wrap=exit
    -Wl,--wrap=_exit
    -Wl,--wrap=_Exit
    -Wl,-z,max-page-size=16384)
