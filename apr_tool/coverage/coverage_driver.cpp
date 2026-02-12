/*
 * Lightweight coverage driver for gcov instrumentation.
 *
 * The real IPC-based test_driver.cpp cannot be used for gcov because:
 * 1. It runs in an infinite loop and must be killed (no clean exit)
 * 2. Buggy controllers may corrupt the heap, causing gcov's atexit handler
 *    to abort when it tries to allocate memory
 *
 * This driver calls controller functions directly and flushes gcov data
 * via __gcov_dump() after EACH iteration. Buggy controllers may corrupt
 * the heap during step(), so we flush early before corruption compounds.
 * Uses _exit() to skip atexit handlers which may fail on a corrupted heap.
 *
 * Usage: ./coverage_runner <test_dir> <num_iterations>
 */

extern "C" {
    #include "../controller.h"
}

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>

/* Matches the State struct layout used by test_driver.cpp / check_distance.py */
struct CovState {
    int idx;
    MappedJointTrajectory value;
    int32_t cur_time_sec;
};

extern "C" void __gcov_dump(void);

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <test_dir> <num_iterations>\n", argv[0]);
        return 1;
    }

    const char *test_dir = argv[1];
    int num_iters = atoi(argv[2]);

    init();

    for (int i = 1; i <= num_iters; i++) {
        char filename[512];
        snprintf(filename, sizeof(filename), "%s/t%d", test_dir, i);

        FILE *f = fopen(filename, "rb");
        if (!f) {
            fprintf(stderr, "Cannot open %s\n", filename);
            break;
        }

        struct CovState state;
        memset(&state, 0, sizeof(state));
        fread(&state, sizeof(struct CovState), 1, f);
        fclose(f);

        in->value = state.value;
        in->cur_time_seconds = state.cur_time_sec;

        step();

        /* Flush coverage after each iteration. Buggy controllers may corrupt
           the heap during step(), making later flushes impossible. */
        __gcov_dump();
    }

    _exit(0);
}
