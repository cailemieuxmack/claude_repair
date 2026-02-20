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
 * To handle controllers with infinite loops, the driver forks once before
 * the iteration loop. The child runs iterations with alarm() before each
 * step() call. If step() hangs, SIGALRM fires and the handler flushes
 * gcov data (capturing lines executed inside the loop) before exiting.
 * The parent monitors the child as a safety net.
 *
 * Exit codes:
 *   0 - All iterations completed normally
 *   1 - Usage error / file error
 *   2 - Child alarm fired (step() timed out, likely infinite loop)
 *   3 - Parent safety-net kill (alarm handler itself hung)
 *
 * Usage: ./coverage_runner <test_dir> <num_iterations> [timeout_secs]
 */

extern "C" {
    #include "../controller.h"
}

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <csignal>
#include <unistd.h>
#include <sys/wait.h>

/* Matches the State struct layout used by test_driver.cpp / check_distance.py */
struct CovState {
    int idx;
    MappedJointTrajectory value;
    int32_t cur_time_sec;
};

extern "C" void __gcov_dump(void);

static volatile sig_atomic_t alarm_iteration = 0;

static void alarm_handler(int) {
    /* Best-effort flush of gcov data. Not async-signal-safe, but for
       compute-bound infinite loops (no locks held), this works in practice. */
    __gcov_dump();
    _exit(2);
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <test_dir> <num_iterations> [timeout_secs]\n", argv[0]);
        return 1;
    }

    const char *test_dir = argv[1];
    int num_iters = atoi(argv[2]);
    int timeout_secs = 5;
    if (argc >= 4) {
        timeout_secs = atoi(argv[3]);
        if (timeout_secs <= 0) timeout_secs = 5;
    }

    init();

    pid_t child = fork();
    if (child == -1) {
        perror("fork");
        return 1;
    }

    if (child == 0) {
        /* --- Child process: run iterations with per-step alarm --- */
        struct sigaction sa;
        memset(&sa, 0, sizeof(sa));
        sa.sa_handler = alarm_handler;
        sa.sa_flags = 0; /* no SA_RESTART so alarm interrupts blocked calls too */
        sigaction(SIGALRM, &sa, nullptr);

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

            alarm_iteration = i;
            alarm(timeout_secs);
            step();
            alarm(0); /* cancel timer */

            /* Flush coverage after each iteration. Buggy controllers may corrupt
               the heap during step(), making later flushes impossible. */
            __gcov_dump();
        }

        _exit(0);
    }

    /* --- Parent process: monitor child with safety-net timeout --- */
    int total_timeout_ms = (timeout_secs * num_iters + 10) * 1000;
    int elapsed_ms = 0;
    int status = 0;

    while (elapsed_ms < total_timeout_ms) {
        pid_t ret = waitpid(child, &status, WNOHANG);
        if (ret == child) {
            /* Child exited */
            if (WIFEXITED(status)) {
                _exit(WEXITSTATUS(status));
            }
            /* Child killed by signal */
            _exit(2);
        }
        if (ret == -1) {
            perror("waitpid");
            _exit(1);
        }
        usleep(10000); /* 10ms poll */
        elapsed_ms += 10;
    }

    /* Safety net: child didn't exit in time (alarm handler may have hung) */
    fprintf(stderr, "Parent safety-net: killing child after %ds\n",
            total_timeout_ms / 1000);
    kill(child, SIGKILL);
    waitpid(child, &status, 0);
    _exit(3);
}
