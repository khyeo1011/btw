/* The btw runtime (Implementation Spec 10.7), linked into every native binary:
 *
 *     gcc -o OUT prog.s runtime/btw_rt.c
 *
 * Printing, runtime errors, git history and curl live here so the generated
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

/* curl (Language Spec 10, P2): the next number on stdin. Hand-rolled, since
 * scanf's %ld has undefined behavior on overflow and accepts +5. It reads
 * the token and the one whitespace character after it, never more. */

static int is_space(int c) { /* ASCII only, whatever the locale */
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f';
}

long btw_rt_curl(void) {
    static const char *weird = "curl: (8) Weird server reply.";
    int c = getchar();
    while (c != EOF && is_space(c)) {
        c = getchar();
    }
    if (c == EOF) {
        fail("curl: (52) Empty reply from server.", 52);
    }
    int negative = c == '-';
    if (negative) {
        c = getchar();
    }
    unsigned long limit = negative ? 9223372036854775808UL : 9223372036854775807UL;
    unsigned long value = 0;
    int digits = 0;
    for (; c != EOF && !is_space(c); c = getchar()) {
        unsigned long d = (unsigned long)(c - '0');
        if (c < '0' || c > '9' || value > (limit - d) / 10) {
            fail(weird, 8);
        }
        value = value * 10 + d;
        digits++;
    }
    if (digits == 0) {
        fail(weird, 8);
    }
    return negative ? (long)(0 - value) : (long)value;
}

/* Git history (Language Spec 9.3, P2). Each tracked variable gets an id from
 * the codegen. Its commits are a ring of the 16 newest values, with a parallel
 * ring of the source line that made each one, for git blame. */

static struct {
    long values[HISTORY_LIMIT];
    long lines[HISTORY_LIMIT];
    long start; /* index of the oldest commit */
    long count;
} history[TRACKED_LIMIT];

static long nth(long id, long k) { /* k = 0 is the oldest kept commit */
    return history[id].values[(history[id].start + k) % HISTORY_LIMIT];
}

static long nth_line(long id, long k) {
    return history[id].lines[(history[id].start + k) % HISTORY_LIMIT];
}

void btw_rt_hist_reset(long id, long v, long line) {
    history[id].values[0] = v;
    history[id].lines[0] = line;
    history[id].start = 0;
    history[id].count = 1;
}

void btw_rt_hist_commit(long id, long v, long line) {
    long count = history[id].count;
    long slot;
    if (count < HISTORY_LIMIT) {
        slot = (history[id].start + count) % HISTORY_LIMIT;
        history[id].count = count + 1;
    } else {
        slot = history[id].start; /* overwrite the oldest */
        history[id].start = (history[id].start + 1) % HISTORY_LIMIT;
    }
    history[id].values[slot] = v;
    history[id].lines[slot] = line;
}

long btw_rt_hist_revert(long id, const char *name, long line) {
    long count = history[id].count;
    if (count < 2) {
        fflush(stdout);
        fprintf(stderr, "fatal: bad revision '%s~1'\n", name);
        exit(128);
    }
    long previous = nth(id, count - 2);
    btw_rt_hist_commit(id, previous, line);
    return previous;
}

static void print_commit(long v, long is_bool) { /* `* VALUE`, no newline */
    if (is_bool) {
        printf("* %s", v ? "LGTM" : "404");
    } else {
        printf("* %ld", v);
    }
}

void btw_rt_hist_log(long id, const char *name, long is_bool) {
    for (long k = history[id].count - 1; k >= 0; k--) {
        print_commit(nth(id, k), is_bool);
        if (k == history[id].count - 1) {
            printf(" (HEAD -> %s)", name);
        }
        putchar('\n');
    }
}

void btw_rt_hist_blame(long id, long is_bool) {
    for (long k = history[id].count - 1; k >= 0; k--) {
        print_commit(nth(id, k), is_bool);
        printf(" (line %ld)\n", nth_line(id, k));
    }
}
