/* The btw runtime (Implementation Spec 10.7), linked into every native binary:
 *
 *     gcc -o OUT prog.s runtime/btw_rt.c
 *
 * Printing, runtime errors and git history live here so the generated
 * assembly never has to format a number. Every function is called from
 * generated code with rsp aligned to 16 bytes, following System V.
 */

#include <stdio.h>
#include <stdlib.h>

#define HISTORY_LIMIT 16
#define TRACKED_LIMIT 64

/* Printing (Language Spec 0, decision 5) */

void btw_rt_print_int(long v) {
    printf("%ld\n", v);
}

void btw_rt_print_bool(long v) {
    puts(v ? "LGTM" : "404");
}

void btw_rt_print_str(const char *s) {
    puts(s);
}

/* Runtime errors (Language Spec 10): flush stdout first, then stderr. */

static void fail(const char *message, int code) {
    fflush(stdout);
    fputs(message, stderr);
    fputc('\n', stderr);
    exit(code);
}

void btw_rt_div_zero(void) {
    fail("Runtime error: division by zero. Have you tried turning it off and on again?", 1);
}

void btw_rt_stack_overflow(void) {
    fail("Stack overflow. Please search stackoverflow.com.", 1);
}

/* Git history (Language Spec 9.3, P2). Each tracked variable gets an id from
 * the codegen. Its commits are a ring of the 16 newest values. */

static struct {
    long values[HISTORY_LIMIT];
    long start; /* index of the oldest commit */
    long count;
} history[TRACKED_LIMIT];

static long nth(long id, long k) { /* k = 0 is the oldest kept commit */
    return history[id].values[(history[id].start + k) % HISTORY_LIMIT];
}

void btw_rt_hist_reset(long id, long v) {
    history[id].values[0] = v;
    history[id].start = 0;
    history[id].count = 1;
}

void btw_rt_hist_commit(long id, long v) {
    long count = history[id].count;
    if (count < HISTORY_LIMIT) {
        history[id].values[(history[id].start + count) % HISTORY_LIMIT] = v;
        history[id].count = count + 1;
    } else {
        history[id].values[history[id].start] = v; /* overwrite the oldest */
        history[id].start = (history[id].start + 1) % HISTORY_LIMIT;
    }
}

long btw_rt_hist_revert(long id, const char *name) {
    long count = history[id].count;
    if (count < 2) {
        fflush(stdout);
        fprintf(stderr, "fatal: bad revision '%s~1'\n", name);
        exit(128);
    }
    long previous = nth(id, count - 2);
    btw_rt_hist_commit(id, previous);
    return previous;
}

void btw_rt_hist_log(long id, const char *name, long is_bool) {
    for (long k = history[id].count - 1; k >= 0; k--) {
        long v = nth(id, k);
        if (is_bool) {
            printf("* %s", v ? "LGTM" : "404");
        } else {
            printf("* %ld", v);
        }
        if (k == history[id].count - 1) {
            printf(" (HEAD -> %s)", name);
        }
        putchar('\n');
    }
}
