# SPDX-License-Identifier: GPL-3.0-or-later
# Consume an explicit LLVM instrumentation profile. Never silently fall back to
# an ordinary build when PGO was requested, or download a mutable profile at configure time.
set(EDEN_PGO_PROFILE "" CACHE FILEPATH "LLVM instrumentation profile for PS5 CPU hot paths")
if(EDEN_PGO_PROFILE)
    if(NOT PS5_NATIVE OR NOT CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
        message(FATAL_ERROR "EDEN_PGO_PROFILE requires the native Clang build")
    endif()
    if(NOT EXISTS "${EDEN_PGO_PROFILE}" OR IS_DIRECTORY "${EDEN_PGO_PROFILE}")
        message(FATAL_ERROR "PGO profile does not exist: ${EDEN_PGO_PROFILE}")
    endif()
    find_program(EDEN_LLVM_PROFDATA NAMES llvm-profdata-18 REQUIRED)
    execute_process(COMMAND "${EDEN_LLVM_PROFDATA}" show "${EDEN_PGO_PROFILE}"
        RESULT_VARIABLE pgo_status OUTPUT_VARIABLE pgo_summary ERROR_VARIABLE pgo_error)
    if(NOT pgo_status EQUAL 0 OR NOT pgo_summary MATCHES "Instrumentation level: (IR|Front-end)")
        message(FATAL_ERROR "PGO profile is unreadable or unsupported: ${pgo_error}${pgo_summary}")
    endif()
    file(SHA256 "${EDEN_PGO_PROFILE}" pgo_hash)
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${EDEN_PGO_PROFILE}")
    # A different profile changes every consumer's command line, even at the same input path.
    file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/pgo")
    set(pgo_input "${CMAKE_BINARY_DIR}/pgo/${pgo_hash}.profdata")
    configure_file("${EDEN_PGO_PROFILE}" "${pgo_input}" COPYONLY)
    foreach(pgo_target video_core shader_recompiler dynarmic)
        # Desktop profiles have uninstrumented/new functions and changed hashes in
        # this port. Clang only applies matching records; report coverage separately.
        target_compile_options(${pgo_target} PRIVATE
            "-fprofile-use=${pgo_input}"
            -Wno-profile-instr-unprofiled -Wno-profile-instr-out-of-date)
    endforeach()
    file(WRITE "${CMAKE_BINARY_DIR}/pgo/provenance.txt"
        "profile_sha256=${pgo_hash}\ncompiler=${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}\ntargets=video_core;shader_recompiler;dynarmic\n${pgo_summary}")
    message(STATUS "PS5 PGO enabled: ${pgo_hash} (video_core, shader_recompiler, dynarmic)")
endif()
