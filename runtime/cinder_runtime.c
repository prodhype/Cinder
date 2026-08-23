#include "cinder_runtime.h"

#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if !defined(_WIN32)
#include <sys/select.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

CINDER_NORETURN void cinder_panic(const char *message)
{
    const char *text = message != NULL ? message : "Cinder panic";
    (void)fprintf(stderr, "panic: %s\n", text);
    abort();
}

void cinder_lock_acquire(CinderLock lock)
{
    if (lock == NULL) {
        cinder_panic("lock is null");
    }
    while (atomic_flag_test_and_set_explicit(&lock->held, memory_order_acquire)) {
    }
}

void cinder_lock_release(CinderLock lock)
{
    if (lock == NULL) {
        cinder_panic("lock is null");
    }
    atomic_flag_clear_explicit(&lock->held, memory_order_release);
}

int cinder_lock_compare(CinderLock left, CinderLock right)
{
    if (left == NULL || right == NULL) {
        cinder_panic("lock collection contains null");
    }
    return (left->order_key > right->order_key) - (left->order_key < right->order_key);
}

double cinder_wall_time(void)
{
    struct timespec timestamp;
    if (timespec_get(&timestamp, TIME_UTC) != TIME_UTC) {
        cinder_panic("wall clock read failed");
    }
    return (double)timestamp.tv_sec + (double)timestamp.tv_nsec / 1000000000.0;
}

void *cinder_alloc(size_t count, size_t element_size)
{
    if (element_size != 0 && count > SIZE_MAX / element_size) {
        cinder_panic("allocation size overflow");
    }

    const size_t size = count * element_size;
    if (size == 0) {
        return NULL;
    }

    void *memory = malloc(size);
    if (memory == NULL) {
        cinder_panic("out of memory");
    }
    return memory;
}

void *cinder_grow_array(
    void *data,
    size_t *capacity,
    size_t minimum_capacity,
    size_t element_size
)
{
    if (capacity == NULL || element_size == 0) {
        cinder_panic("invalid array growth arguments");
    }
    if (*capacity >= minimum_capacity) {
        return data;
    }

    size_t next_capacity = *capacity == 0 ? 4 : *capacity;
    while (next_capacity < minimum_capacity) {
        if (next_capacity > SIZE_MAX / 2) {
            next_capacity = minimum_capacity;
            break;
        }
        next_capacity *= 2;
    }
    if (next_capacity < minimum_capacity || next_capacity > SIZE_MAX / element_size) {
        cinder_panic("array capacity overflow");
    }

    void *grown = realloc(data, next_capacity * element_size);
    if (grown == NULL) {
        cinder_panic("out of memory");
    }
    *capacity = next_capacity;
    return grown;
}

uint64_t cinder_hash_u64(uint64_t value)
{
    value += UINT64_C(0x9e3779b97f4a7c15);
    value = (value ^ (value >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)) * UINT64_C(0x94d049bb133111eb);
    return value ^ (value >> 31);
}

uint64_t cinder_hash_string(const char *text)
{
    if (text == NULL) {
        return cinder_hash_u64(UINT64_C(0x6e756c6c));
    }

    uint64_t hash = UINT64_C(14695981039346656037);
    const unsigned char *cursor = (const unsigned char *)text;
    while (*cursor != 0) {
        hash ^= (uint64_t)*cursor;
        hash *= UINT64_C(1099511628211);
        cursor += 1;
    }
    return cinder_hash_u64(hash);
}

bool cinder_string_equal(const char *left, const char *right)
{
    if (left == right) {
        return true;
    }
    if (left == NULL || right == NULL) {
        return false;
    }
    return strcmp(left, right) == 0;
}

char *cinder_clone_string(const char *text)
{
    if (text == NULL) {
        return NULL;
    }
    const size_t length = strlen(text);
    if (length == SIZE_MAX) {
        cinder_panic("string length overflow");
    }
    char *copy = cinder_alloc(length + 1, sizeof(char));
    (void)memcpy(copy, text, length + 1);
    return copy;
}

static CinderString cinder_empty_string(void)
{
    CinderString string = {NULL, 0, 0};
    return string;
}

/*
 * Half-open Unicode 16.0 intervals. Zero-width entries are Mn, Me, and Cf
 * scalars plus conjoining Hangul jamo and emoji modifiers. Wide entries are
 * assigned East_Asian_Width W/F scalars. Ambiguous-width scalars stay narrow
 * so diagnostics are deterministic across host locales.
 */
static const uint32_t cinder_zero_width_boundaries[] = {
    0x0, 0x1, 0xad, 0xae, 0x300, 0x370, 0x483, 0x48a,
    0x591, 0x5be, 0x5bf, 0x5c0, 0x5c1, 0x5c3, 0x5c4, 0x5c6,
    0x5c7, 0x5c8, 0x600, 0x606, 0x610, 0x61b, 0x61c, 0x61d,
    0x64b, 0x660, 0x670, 0x671, 0x6d6, 0x6de, 0x6df, 0x6e5,
    0x6e7, 0x6e9, 0x6ea, 0x6ee, 0x70f, 0x710, 0x711, 0x712,
    0x730, 0x74b, 0x7a6, 0x7b1, 0x7eb, 0x7f4, 0x7fd, 0x7fe,
    0x816, 0x81a, 0x81b, 0x824, 0x825, 0x828, 0x829, 0x82e,
    0x859, 0x85c, 0x890, 0x892, 0x897, 0x8a0, 0x8ca, 0x903,
    0x93a, 0x93b, 0x93c, 0x93d, 0x941, 0x949, 0x94d, 0x94e,
    0x951, 0x958, 0x962, 0x964, 0x981, 0x982, 0x9bc, 0x9bd,
    0x9c1, 0x9c5, 0x9cd, 0x9ce, 0x9e2, 0x9e4, 0x9fe, 0x9ff,
    0xa01, 0xa03, 0xa3c, 0xa3d, 0xa41, 0xa43, 0xa47, 0xa49,
    0xa4b, 0xa4e, 0xa51, 0xa52, 0xa70, 0xa72, 0xa75, 0xa76,
    0xa81, 0xa83, 0xabc, 0xabd, 0xac1, 0xac6, 0xac7, 0xac9,
    0xacd, 0xace, 0xae2, 0xae4, 0xafa, 0xb00, 0xb01, 0xb02,
    0xb3c, 0xb3d, 0xb3f, 0xb40, 0xb41, 0xb45, 0xb4d, 0xb4e,
    0xb55, 0xb57, 0xb62, 0xb64, 0xb82, 0xb83, 0xbc0, 0xbc1,
    0xbcd, 0xbce, 0xc00, 0xc01, 0xc04, 0xc05, 0xc3c, 0xc3d,
    0xc3e, 0xc41, 0xc46, 0xc49, 0xc4a, 0xc4e, 0xc55, 0xc57,
    0xc62, 0xc64, 0xc81, 0xc82, 0xcbc, 0xcbd, 0xcbf, 0xcc0,
    0xcc6, 0xcc7, 0xccc, 0xcce, 0xce2, 0xce4, 0xd00, 0xd02,
    0xd3b, 0xd3d, 0xd41, 0xd45, 0xd4d, 0xd4e, 0xd62, 0xd64,
    0xd81, 0xd82, 0xdca, 0xdcb, 0xdd2, 0xdd5, 0xdd6, 0xdd7,
    0xe31, 0xe32, 0xe34, 0xe3b, 0xe47, 0xe4f, 0xeb1, 0xeb2,
    0xeb4, 0xebd, 0xec8, 0xecf, 0xf18, 0xf1a, 0xf35, 0xf36,
    0xf37, 0xf38, 0xf39, 0xf3a, 0xf71, 0xf7f, 0xf80, 0xf85,
    0xf86, 0xf88, 0xf8d, 0xf98, 0xf99, 0xfbd, 0xfc6, 0xfc7,
    0x102d, 0x1031, 0x1032, 0x1038, 0x1039, 0x103b, 0x103d, 0x103f,
    0x1058, 0x105a, 0x105e, 0x1061, 0x1071, 0x1075, 0x1082, 0x1083,
    0x1085, 0x1087, 0x108d, 0x108e, 0x109d, 0x109e, 0x1160, 0x1200,
    0x135d, 0x1360, 0x1712, 0x1715, 0x1732, 0x1734, 0x1752, 0x1754,
    0x1772, 0x1774, 0x17b4, 0x17b6, 0x17b7, 0x17be, 0x17c6, 0x17c7,
    0x17c9, 0x17d4, 0x17dd, 0x17de, 0x180b, 0x1810, 0x1885, 0x1887,
    0x18a9, 0x18aa, 0x1920, 0x1923, 0x1927, 0x1929, 0x1932, 0x1933,
    0x1939, 0x193c, 0x1a17, 0x1a19, 0x1a1b, 0x1a1c, 0x1a56, 0x1a57,
    0x1a58, 0x1a5f, 0x1a60, 0x1a61, 0x1a62, 0x1a63, 0x1a65, 0x1a6d,
    0x1a73, 0x1a7d, 0x1a7f, 0x1a80, 0x1ab0, 0x1acf, 0x1b00, 0x1b04,
    0x1b34, 0x1b35, 0x1b36, 0x1b3b, 0x1b3c, 0x1b3d, 0x1b42, 0x1b43,
    0x1b6b, 0x1b74, 0x1b80, 0x1b82, 0x1ba2, 0x1ba6, 0x1ba8, 0x1baa,
    0x1bab, 0x1bae, 0x1be6, 0x1be7, 0x1be8, 0x1bea, 0x1bed, 0x1bee,
    0x1bef, 0x1bf2, 0x1c2c, 0x1c34, 0x1c36, 0x1c38, 0x1cd0, 0x1cd3,
    0x1cd4, 0x1ce1, 0x1ce2, 0x1ce9, 0x1ced, 0x1cee, 0x1cf4, 0x1cf5,
    0x1cf8, 0x1cfa, 0x1dc0, 0x1e00, 0x200b, 0x2010, 0x202a, 0x202f,
    0x2060, 0x2065, 0x2066, 0x2070, 0x20d0, 0x20f1, 0x2cef, 0x2cf2,
    0x2d7f, 0x2d80, 0x2de0, 0x2e00, 0x302a, 0x302e, 0x3099, 0x309b,
    0xa66f, 0xa673, 0xa674, 0xa67e, 0xa69e, 0xa6a0, 0xa6f0, 0xa6f2,
    0xa802, 0xa803, 0xa806, 0xa807, 0xa80b, 0xa80c, 0xa825, 0xa827,
    0xa82c, 0xa82d, 0xa8c4, 0xa8c6, 0xa8e0, 0xa8f2, 0xa8ff, 0xa900,
    0xa926, 0xa92e, 0xa947, 0xa952, 0xa980, 0xa983, 0xa9b3, 0xa9b4,
    0xa9b6, 0xa9ba, 0xa9bc, 0xa9be, 0xa9e5, 0xa9e6, 0xaa29, 0xaa2f,
    0xaa31, 0xaa33, 0xaa35, 0xaa37, 0xaa43, 0xaa44, 0xaa4c, 0xaa4d,
    0xaa7c, 0xaa7d, 0xaab0, 0xaab1, 0xaab2, 0xaab5, 0xaab7, 0xaab9,
    0xaabe, 0xaac0, 0xaac1, 0xaac2, 0xaaec, 0xaaee, 0xaaf6, 0xaaf7,
    0xabe5, 0xabe6, 0xabe8, 0xabe9, 0xabed, 0xabee, 0xfb1e, 0xfb1f,
    0xfe00, 0xfe10, 0xfe20, 0xfe30, 0xfeff, 0xff00, 0xfff9, 0xfffc,
    0x101fd, 0x101fe, 0x102e0, 0x102e1, 0x10376, 0x1037b, 0x10a01, 0x10a04,
    0x10a05, 0x10a07, 0x10a0c, 0x10a10, 0x10a38, 0x10a3b, 0x10a3f, 0x10a40,
    0x10ae5, 0x10ae7, 0x10d24, 0x10d28, 0x10d69, 0x10d6e, 0x10eab, 0x10ead,
    0x10efc, 0x10f00, 0x10f46, 0x10f51, 0x10f82, 0x10f86, 0x11001, 0x11002,
    0x11038, 0x11047, 0x11070, 0x11071, 0x11073, 0x11075, 0x1107f, 0x11082,
    0x110b3, 0x110b7, 0x110b9, 0x110bb, 0x110bd, 0x110be, 0x110c2, 0x110c3,
    0x110cd, 0x110ce, 0x11100, 0x11103, 0x11127, 0x1112c, 0x1112d, 0x11135,
    0x11173, 0x11174, 0x11180, 0x11182, 0x111b6, 0x111bf, 0x111c9, 0x111cd,
    0x111cf, 0x111d0, 0x1122f, 0x11232, 0x11234, 0x11235, 0x11236, 0x11238,
    0x1123e, 0x1123f, 0x11241, 0x11242, 0x112df, 0x112e0, 0x112e3, 0x112eb,
    0x11300, 0x11302, 0x1133b, 0x1133d, 0x11340, 0x11341, 0x11366, 0x1136d,
    0x11370, 0x11375, 0x113bb, 0x113c1, 0x113ce, 0x113cf, 0x113d0, 0x113d1,
    0x113d2, 0x113d3, 0x113e1, 0x113e3, 0x11438, 0x11440, 0x11442, 0x11445,
    0x11446, 0x11447, 0x1145e, 0x1145f, 0x114b3, 0x114b9, 0x114ba, 0x114bb,
    0x114bf, 0x114c1, 0x114c2, 0x114c4, 0x115b2, 0x115b6, 0x115bc, 0x115be,
    0x115bf, 0x115c1, 0x115dc, 0x115de, 0x11633, 0x1163b, 0x1163d, 0x1163e,
    0x1163f, 0x11641, 0x116ab, 0x116ac, 0x116ad, 0x116ae, 0x116b0, 0x116b6,
    0x116b7, 0x116b8, 0x1171d, 0x1171e, 0x1171f, 0x11720, 0x11722, 0x11726,
    0x11727, 0x1172c, 0x1182f, 0x11838, 0x11839, 0x1183b, 0x1193b, 0x1193d,
    0x1193e, 0x1193f, 0x11943, 0x11944, 0x119d4, 0x119d8, 0x119da, 0x119dc,
    0x119e0, 0x119e1, 0x11a01, 0x11a0b, 0x11a33, 0x11a39, 0x11a3b, 0x11a3f,
    0x11a47, 0x11a48, 0x11a51, 0x11a57, 0x11a59, 0x11a5c, 0x11a8a, 0x11a97,
    0x11a98, 0x11a9a, 0x11c30, 0x11c37, 0x11c38, 0x11c3e, 0x11c3f, 0x11c40,
    0x11c92, 0x11ca8, 0x11caa, 0x11cb1, 0x11cb2, 0x11cb4, 0x11cb5, 0x11cb7,
    0x11d31, 0x11d37, 0x11d3a, 0x11d3b, 0x11d3c, 0x11d3e, 0x11d3f, 0x11d46,
    0x11d47, 0x11d48, 0x11d90, 0x11d92, 0x11d95, 0x11d96, 0x11d97, 0x11d98,
    0x11ef3, 0x11ef5, 0x11f00, 0x11f02, 0x11f36, 0x11f3b, 0x11f40, 0x11f41,
    0x11f42, 0x11f43, 0x11f5a, 0x11f5b, 0x13430, 0x13441, 0x13447, 0x13456,
    0x1611e, 0x1612a, 0x1612d, 0x16130, 0x16af0, 0x16af5, 0x16b30, 0x16b37,
    0x16f4f, 0x16f50, 0x16f8f, 0x16f93, 0x16fe4, 0x16fe5, 0x1bc9d, 0x1bc9f,
    0x1bca0, 0x1bca4, 0x1cf00, 0x1cf2e, 0x1cf30, 0x1cf47, 0x1d167, 0x1d16a,
    0x1d173, 0x1d183, 0x1d185, 0x1d18c, 0x1d1aa, 0x1d1ae, 0x1d242, 0x1d245,
    0x1da00, 0x1da37, 0x1da3b, 0x1da6d, 0x1da75, 0x1da76, 0x1da84, 0x1da85,
    0x1da9b, 0x1daa0, 0x1daa1, 0x1dab0, 0x1e000, 0x1e007, 0x1e008, 0x1e019,
    0x1e01b, 0x1e022, 0x1e023, 0x1e025, 0x1e026, 0x1e02b, 0x1e08f, 0x1e090,
    0x1e130, 0x1e137, 0x1e2ae, 0x1e2af, 0x1e2ec, 0x1e2f0, 0x1e4ec, 0x1e4f0,
    0x1e5ee, 0x1e5f0, 0x1e8d0, 0x1e8d7, 0x1e944, 0x1e94b, 0x1f3fb, 0x1f400,
    0xe0001, 0xe0002, 0xe0020, 0xe0080, 0xe0100, 0xe01f0,
};

static const uint32_t cinder_wide_boundaries[] = {
    0x1100, 0x1160, 0x231a, 0x231c, 0x2329, 0x232b, 0x23e9, 0x23ed,
    0x23f0, 0x23f1, 0x23f3, 0x23f4, 0x25fd, 0x25ff, 0x2614, 0x2616,
    0x2630, 0x2638, 0x2648, 0x2654, 0x267f, 0x2680, 0x268a, 0x2690,
    0x2693, 0x2694, 0x26a1, 0x26a2, 0x26aa, 0x26ac, 0x26bd, 0x26bf,
    0x26c4, 0x26c6, 0x26ce, 0x26cf, 0x26d4, 0x26d5, 0x26ea, 0x26eb,
    0x26f2, 0x26f4, 0x26f5, 0x26f6, 0x26fa, 0x26fb, 0x26fd, 0x26fe,
    0x2705, 0x2706, 0x270a, 0x270c, 0x2728, 0x2729, 0x274c, 0x274d,
    0x274e, 0x274f, 0x2753, 0x2756, 0x2757, 0x2758, 0x2795, 0x2798,
    0x27b0, 0x27b1, 0x27bf, 0x27c0, 0x2b1b, 0x2b1d, 0x2b50, 0x2b51,
    0x2b55, 0x2b56, 0x2e80, 0x2e9a, 0x2e9b, 0x2ef4, 0x2f00, 0x2fd6,
    0x2ff0, 0x302a, 0x302e, 0x303f, 0x3041, 0x3097, 0x309b, 0x3100,
    0x3105, 0x3130, 0x3131, 0x318f, 0x3190, 0x31e6, 0x31ef, 0x321f,
    0x3220, 0x3248, 0x3250, 0xa48d, 0xa490, 0xa4c7, 0xa960, 0xa97d,
    0xac00, 0xd7a4, 0xf900, 0xfa6e, 0xfa70, 0xfada, 0xfe10, 0xfe1a,
    0xfe30, 0xfe53, 0xfe54, 0xfe67, 0xfe68, 0xfe6c, 0xff01, 0xff61,
    0xffe0, 0xffe7, 0x16fe0, 0x16fe4, 0x16ff0, 0x16ff2, 0x17000, 0x187f8,
    0x18800, 0x18cd6, 0x18cff, 0x18d09, 0x1aff0, 0x1aff4, 0x1aff5, 0x1affc,
    0x1affd, 0x1afff, 0x1b000, 0x1b123, 0x1b132, 0x1b133, 0x1b150, 0x1b153,
    0x1b155, 0x1b156, 0x1b164, 0x1b168, 0x1b170, 0x1b2fc, 0x1d300, 0x1d357,
    0x1d360, 0x1d377, 0x1f004, 0x1f005, 0x1f0cf, 0x1f0d0, 0x1f18e, 0x1f18f,
    0x1f191, 0x1f19b, 0x1f200, 0x1f203, 0x1f210, 0x1f23c, 0x1f240, 0x1f249,
    0x1f250, 0x1f252, 0x1f260, 0x1f266, 0x1f300, 0x1f321, 0x1f32d, 0x1f336,
    0x1f337, 0x1f37d, 0x1f37e, 0x1f394, 0x1f3a0, 0x1f3cb, 0x1f3cf, 0x1f3d4,
    0x1f3e0, 0x1f3f1, 0x1f3f4, 0x1f3f5, 0x1f3f8, 0x1f3fb, 0x1f400, 0x1f43f,
    0x1f440, 0x1f441, 0x1f442, 0x1f4fd, 0x1f4ff, 0x1f53e, 0x1f54b, 0x1f54f,
    0x1f550, 0x1f568, 0x1f57a, 0x1f57b, 0x1f595, 0x1f597, 0x1f5a4, 0x1f5a5,
    0x1f5fb, 0x1f650, 0x1f680, 0x1f6c6, 0x1f6cc, 0x1f6cd, 0x1f6d0, 0x1f6d3,
    0x1f6d5, 0x1f6d8, 0x1f6dc, 0x1f6e0, 0x1f6eb, 0x1f6ed, 0x1f6f4, 0x1f6fd,
    0x1f7e0, 0x1f7ec, 0x1f7f0, 0x1f7f1, 0x1f90c, 0x1f93b, 0x1f93c, 0x1f946,
    0x1f947, 0x1fa00, 0x1fa70, 0x1fa7d, 0x1fa80, 0x1fa8a, 0x1fa8f, 0x1fac7,
    0x1face, 0x1fadd, 0x1fadf, 0x1faea, 0x1faf0, 0x1faf9, 0x20000, 0x2a6e0,
    0x2a700, 0x2b73a, 0x2b740, 0x2b81e, 0x2b820, 0x2cea2, 0x2ceb0, 0x2ebe1,
    0x2ebf0, 0x2ee5e, 0x2f800, 0x2fa1e, 0x30000, 0x3134b, 0x31350, 0x323b0,
};

static bool cinder_unicode_contains(
    const uint32_t *boundaries,
    size_t boundary_count,
    uint32_t scalar
)
{
    size_t low = 0;
    size_t high = boundary_count;
    while (low < high) {
        const size_t middle = low + (high - low) / 2;
        if (boundaries[middle] <= scalar) {
            low = middle + 1;
        } else {
            high = middle;
        }
    }
    return low % 2 != 0;
}

int32_t cinder_unicode_display_width(uint32_t scalar)
{
    if (scalar > UINT32_C(0x10ffff) ||
        (scalar >= UINT32_C(0xd800) && scalar <= UINT32_C(0xdfff))) {
        return 1;
    }
    if (cinder_unicode_contains(
            cinder_zero_width_boundaries,
            CINDER_ARRAY_LEN(cinder_zero_width_boundaries),
            scalar)) {
        return 0;
    }
    if (cinder_unicode_contains(
            cinder_wide_boundaries,
            CINDER_ARRAY_LEN(cinder_wide_boundaries),
            scalar)) {
        return 2;
    }
    return 1;
}

static bool cinder_utf8_is_valid(const char *data, size_t length)
{
    if (data == NULL) {
        return length == 0;
    }

    size_t index = 0;
    while (index < length) {
        const unsigned char first = (unsigned char)data[index];
        /* Owned text must remain losslessly borrowable as a C string. */
        if (first == 0) {
            return false;
        }
        if (first <= UINT8_C(0x7f)) {
            index += 1;
            continue;
        }

        if (first >= UINT8_C(0xc2) && first <= UINT8_C(0xdf)) {
            if (index + 1 >= length) {
                return false;
            }
            const unsigned char second = (unsigned char)data[index + 1];
            if (second < UINT8_C(0x80) || second > UINT8_C(0xbf)) {
                return false;
            }
            index += 2;
            continue;
        }

        if (first >= UINT8_C(0xe0) && first <= UINT8_C(0xef)) {
            if (index + 2 >= length) {
                return false;
            }
            const unsigned char second = (unsigned char)data[index + 1];
            const unsigned char third = (unsigned char)data[index + 2];
            const bool valid_second =
                (first == UINT8_C(0xe0) && second >= UINT8_C(0xa0) &&
                 second <= UINT8_C(0xbf)) ||
                (first >= UINT8_C(0xe1) && first <= UINT8_C(0xec) &&
                 second >= UINT8_C(0x80) && second <= UINT8_C(0xbf)) ||
                (first == UINT8_C(0xed) && second >= UINT8_C(0x80) &&
                 second <= UINT8_C(0x9f)) ||
                (first >= UINT8_C(0xee) && first <= UINT8_C(0xef) &&
                 second >= UINT8_C(0x80) && second <= UINT8_C(0xbf));
            if (!valid_second || third < UINT8_C(0x80) ||
                third > UINT8_C(0xbf)) {
                return false;
            }
            index += 3;
            continue;
        }

        if (first >= UINT8_C(0xf0) && first <= UINT8_C(0xf4)) {
            if (index + 3 >= length) {
                return false;
            }
            const unsigned char second = (unsigned char)data[index + 1];
            const unsigned char third = (unsigned char)data[index + 2];
            const unsigned char fourth = (unsigned char)data[index + 3];
            const bool valid_second =
                (first == UINT8_C(0xf0) && second >= UINT8_C(0x90) &&
                 second <= UINT8_C(0xbf)) ||
                (first >= UINT8_C(0xf1) && first <= UINT8_C(0xf3) &&
                 second >= UINT8_C(0x80) && second <= UINT8_C(0xbf)) ||
                (first == UINT8_C(0xf4) && second >= UINT8_C(0x80) &&
                 second <= UINT8_C(0x8f));
            if (!valid_second || third < UINT8_C(0x80) ||
                third > UINT8_C(0xbf) || fourth < UINT8_C(0x80) ||
                fourth > UINT8_C(0xbf)) {
                return false;
            }
            index += 4;
            continue;
        }

        return false;
    }
    return true;
}

static void cinder_validate_string_structure(const CinderString *string)
{
    if (string == NULL) {
        cinder_panic("invalid string argument");
    }
    if (string->data == NULL) {
        if (string->length != 0 || string->capacity != 0) {
            cinder_panic("invalid string state");
        }
        return;
    }
    if (string->capacity != 0 && string->length >= string->capacity) {
        cinder_panic("invalid string state");
    }
    if (string->data[string->length] != '\0') {
        cinder_panic("string is not NUL-terminated");
    }
}

static void cinder_validate_string(const CinderString *string)
{
    cinder_validate_string_structure(string);
    if (string->data != NULL &&
        !cinder_utf8_is_valid(string->data, string->length)) {
        cinder_panic("invalid UTF-8 string");
    }
}

static void cinder_write_string(FILE *stream, const CinderString *text)
{
    cinder_validate_string(text);
    if (text->length == 0) {
        return;
    }
    if (fwrite(text->data, 1, text->length, stream) != text->length) {
        cinder_panic("failed to write text");
    }
}

void cinder_write_stdout(const CinderString *text)
{
    cinder_write_string(stdout, text);
}

void cinder_write_stderr(const CinderString *text)
{
    cinder_write_string(stderr, text);
}

static void cinder_validate_builder_structure(
    const CinderStringBuilder *builder
)
{
    if (builder == NULL) {
        cinder_panic("invalid string builder argument");
    }
    if (builder->data == NULL) {
        if (builder->length != 0 || builder->capacity != 0) {
            cinder_panic("invalid string builder state");
        }
        return;
    }
    if (builder->capacity == 0 || builder->length >= builder->capacity) {
        cinder_panic("invalid string builder state");
    }
    if (builder->data[builder->length] != '\0') {
        cinder_panic("string builder is not NUL-terminated");
    }
}

static void cinder_validate_builder(const CinderStringBuilder *builder)
{
    cinder_validate_builder_structure(builder);
    if (builder->data != NULL &&
        !cinder_utf8_is_valid(builder->data, builder->length)) {
        cinder_panic("invalid UTF-8 string builder");
    }
}

static size_t cinder_grown_string_capacity(
    size_t current_capacity,
    size_t required_capacity
)
{
    size_t next_capacity = current_capacity == 0 ? 16 : current_capacity;
    while (next_capacity < required_capacity) {
        if (next_capacity > SIZE_MAX / 2) {
            next_capacity = required_capacity;
            break;
        }
        next_capacity *= 2;
    }
    if (next_capacity < required_capacity) {
        cinder_panic("string capacity overflow");
    }
    return next_capacity;
}

static CinderString cinder_allocate_string(size_t length)
{
    if (length == SIZE_MAX) {
        cinder_panic("string length overflow");
    }
    CinderString string;
    string.data = cinder_alloc(length + 1, sizeof(char));
    string.length = length;
    string.capacity = length + 1;
    string.data[length] = '\0';
    return string;
}

CinderString cinder_string_from_bytes(const char *data, size_t length)
{
    if (data == NULL && length != 0) {
        cinder_panic("invalid string bytes");
    }
    if (!cinder_utf8_is_valid(data, length)) {
        cinder_panic("invalid UTF-8 string");
    }

    CinderString string = cinder_allocate_string(length);
    if (length != 0) {
        (void)memcpy(string.data, data, length);
    }
    return string;
}

CinderString cinder_string_from_cstr(const char *text)
{
    if (text == NULL) {
        cinder_panic("invalid C string");
    }
    return cinder_string_from_bytes(text, strlen(text));
}

typedef struct CinderProcessBuffer {
    char *data;
    size_t length;
    size_t capacity;
} CinderProcessBuffer;

static void cinder_process_buffer_drop(CinderProcessBuffer *buffer)
{
    if (buffer == NULL) {
        return;
    }
    free(buffer->data);
    buffer->data = NULL;
    buffer->length = 0;
    buffer->capacity = 0;
}

static void cinder_process_buffer_append(
    CinderProcessBuffer *buffer,
    const char *data,
    size_t length
)
{
    if (buffer == NULL || (data == NULL && length != 0)) {
        cinder_panic("invalid process output buffer");
    }
    if (length == 0) {
        return;
    }
    if (buffer->length > SIZE_MAX - length) {
        cinder_panic("process output length overflow");
    }
    buffer->data = (char *)cinder_grow_array(
        buffer->data,
        &buffer->capacity,
        buffer->length + length,
        sizeof(*buffer->data)
    );
    (void)memcpy(buffer->data + buffer->length, data, length);
    buffer->length += length;
}

static CinderString cinder_process_buffer_to_string(CinderProcessBuffer *buffer)
{
    CinderString result = cinder_string_from_bytes(buffer->data, buffer->length);
    cinder_process_buffer_drop(buffer);
    return result;
}

void CinderProcessResult__drop(CinderProcessResult *self)
{
    if (self == NULL) {
        return;
    }
    cinder_string_drop(&self->stderr);
    cinder_string_drop(&self->stdout);
}

void cinder_process_result_drop_raw(void *self)
{
    CinderProcessResult__drop((CinderProcessResult *)self);
}

#if defined(_WIN32)
CinderProcessResult cinder_process_run_argv(
    size_t argc,
    const char *const *argv
)
{
    (void)argc;
    (void)argv;
    CinderProcessResult result = {
        -1,
        {NULL, 0, 0},
        cinder_string_from_cstr("process.run is not implemented on Windows")
    };
    return result;
}
#else
static void cinder_close_fd(int *fd)
{
    if (fd == NULL || *fd < 0) {
        return;
    }
    while (close(*fd) != 0) {
        if (errno != EINTR) {
            break;
        }
    }
    *fd = -1;
}

static void cinder_process_read_once(
    int fd,
    CinderProcessBuffer *buffer,
    bool *open
)
{
    char chunk[4096];
    ssize_t count = read(fd, chunk, sizeof(chunk));
    if (count > 0) {
        cinder_process_buffer_append(buffer, chunk, (size_t)count);
        return;
    }
    if (count == 0) {
        *open = false;
        return;
    }
    if (errno == EINTR) {
        return;
    }
    cinder_panic("process output read failed");
}

static int cinder_process_wait(pid_t pid)
{
    int status = 0;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno != EINTR) {
            cinder_panic("process wait failed");
        }
    }
    if (WIFEXITED(status)) {
        return WEXITSTATUS(status);
    }
    if (WIFSIGNALED(status)) {
        return 128 + WTERMSIG(status);
    }
    return -1;
}

static void cinder_process_capture_output(
    int stdout_fd,
    int stderr_fd,
    CinderProcessBuffer *stdout_buffer,
    CinderProcessBuffer *stderr_buffer
)
{
    bool stdout_open = true;
    bool stderr_open = true;
    while (stdout_open || stderr_open) {
        fd_set read_fds;
        FD_ZERO(&read_fds);
        int max_fd = -1;
        if (stdout_open) {
            FD_SET(stdout_fd, &read_fds);
            max_fd = stdout_fd > max_fd ? stdout_fd : max_fd;
        }
        if (stderr_open) {
            FD_SET(stderr_fd, &read_fds);
            max_fd = stderr_fd > max_fd ? stderr_fd : max_fd;
        }

        int ready = select(max_fd + 1, &read_fds, NULL, NULL, NULL);
        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            cinder_panic("process output wait failed");
        }
        if (stdout_open && FD_ISSET(stdout_fd, &read_fds)) {
            cinder_process_read_once(stdout_fd, stdout_buffer, &stdout_open);
        }
        if (stderr_open && FD_ISSET(stderr_fd, &read_fds)) {
            cinder_process_read_once(stderr_fd, stderr_buffer, &stderr_open);
        }
    }
}

CinderProcessResult cinder_process_run_argv(
    size_t argc,
    const char *const *argv
)
{
    if (argc == 0 || argv == NULL || argv[0] == NULL) {
        cinder_panic("process.run requires a non-empty command");
    }
    if (argc == SIZE_MAX) {
        cinder_panic("process command length overflow");
    }

    char **child_argv = cinder_alloc(argc + 1, sizeof(*child_argv));
    for (size_t index = 0; index < argc; ++index) {
        if (argv[index] == NULL) {
            free(child_argv);
            cinder_panic("process command contains null argument");
        }
        child_argv[index] = (char *)argv[index];
    }
    child_argv[argc] = NULL;

    int stdout_pipe[2] = {-1, -1};
    int stderr_pipe[2] = {-1, -1};
    if (pipe(stdout_pipe) != 0 || pipe(stderr_pipe) != 0) {
        cinder_close_fd(&stdout_pipe[0]);
        cinder_close_fd(&stdout_pipe[1]);
        cinder_close_fd(&stderr_pipe[0]);
        cinder_close_fd(&stderr_pipe[1]);
        free(child_argv);
        cinder_panic("process pipe creation failed");
    }

    pid_t pid = fork();
    if (pid < 0) {
        cinder_close_fd(&stdout_pipe[0]);
        cinder_close_fd(&stdout_pipe[1]);
        cinder_close_fd(&stderr_pipe[0]);
        cinder_close_fd(&stderr_pipe[1]);
        free(child_argv);
        cinder_panic("process spawn failed");
    }

    if (pid == 0) {
        cinder_close_fd(&stdout_pipe[0]);
        cinder_close_fd(&stderr_pipe[0]);
        if (
            dup2(stdout_pipe[1], STDOUT_FILENO) < 0 ||
            dup2(stderr_pipe[1], STDERR_FILENO) < 0
        ) {
            _exit(127);
        }
        cinder_close_fd(&stdout_pipe[1]);
        cinder_close_fd(&stderr_pipe[1]);
        execvp(child_argv[0], child_argv);
        (void)fprintf(stderr, "exec failed: %s\n", strerror(errno));
        _exit(127);
    }

    free(child_argv);
    cinder_close_fd(&stdout_pipe[1]);
    cinder_close_fd(&stderr_pipe[1]);

    CinderProcessBuffer stdout_buffer = {NULL, 0, 0};
    CinderProcessBuffer stderr_buffer = {NULL, 0, 0};
    cinder_process_capture_output(
        stdout_pipe[0],
        stderr_pipe[0],
        &stdout_buffer,
        &stderr_buffer
    );
    cinder_close_fd(&stdout_pipe[0]);
    cinder_close_fd(&stderr_pipe[0]);

    CinderProcessResult result;
    result.exit_code = cinder_process_wait(pid);
    result.stdout = cinder_process_buffer_to_string(&stdout_buffer);
    result.stderr = cinder_process_buffer_to_string(&stderr_buffer);
    return result;
}
#endif

static size_t cinder_path_validated_length(const char *path)
{
    if (path == NULL) {
        cinder_panic("path is null");
    }
    const size_t length = strlen(path);
    if (!cinder_utf8_is_valid(path, length)) {
        cinder_panic("path is not valid UTF-8");
    }
    return length;
}

static size_t cinder_path_trimmed_end(const char *path, size_t length)
{
    size_t end = length;
    while (end > 1 && path[end - 1] == '/') {
        end -= 1;
    }
    return end;
}

static size_t cinder_path_component_start(const char *path, size_t end)
{
    size_t start = end;
    while (start > 0 && path[start - 1] != '/') {
        start -= 1;
    }
    return start;
}

static size_t cinder_path_suffix_start(
    const char *path,
    size_t component_start,
    size_t end)
{
    size_t search_start = component_start;
    while (search_start < end && path[search_start] == '.') {
        search_start += 1;
    }
    for (size_t index = end; index > search_start; --index) {
        if (path[index - 1] == '.') {
            return index - 1;
        }
    }
    return end;
}

CinderString cinder_path_parent(const char *path)
{
    const size_t length = cinder_path_validated_length(path);
    const size_t end = cinder_path_trimmed_end(path, length);
    if (end == 0) {
        return cinder_string_from_cstr(".");
    }
    if (end == 1 && path[0] == '/') {
        return cinder_string_from_cstr("/");
    }

    const size_t component_start = cinder_path_component_start(path, end);
    if (component_start == 0) {
        return cinder_string_from_cstr(".");
    }

    size_t parent_end = component_start - 1;
    while (parent_end > 1 && path[parent_end - 1] == '/') {
        parent_end -= 1;
    }
    if (parent_end == 0) {
        return cinder_string_from_cstr("/");
    }
    return cinder_string_from_bytes(path, parent_end);
}

CinderString cinder_path_name(const char *path)
{
    const size_t length = cinder_path_validated_length(path);
    const size_t end = cinder_path_trimmed_end(path, length);
    const size_t start = cinder_path_component_start(path, end);
    return cinder_string_from_bytes(path + start, end - start);
}

CinderString cinder_path_stem(const char *path)
{
    const size_t length = cinder_path_validated_length(path);
    const size_t end = cinder_path_trimmed_end(path, length);
    const size_t start = cinder_path_component_start(path, end);
    const size_t stem_end = cinder_path_suffix_start(path, start, end);
    return cinder_string_from_bytes(path + start, stem_end - start);
}

CinderString cinder_path_join(const char *left, const char *right)
{
    const size_t left_length = cinder_path_validated_length(left);
    const size_t right_length = cinder_path_validated_length(right);
    if (right_length > 0 && right[0] == '/') {
        return cinder_string_from_bytes(right, right_length);
    }
    if (left_length == 0 || (left_length == 1 && left[0] == '.')) {
        return cinder_string_from_bytes(right, right_length);
    }
    if (right_length == 0) {
        return cinder_string_from_bytes(left, left_length);
    }

    const bool needs_separator = left[left_length - 1] != '/';
    const size_t separator_length = needs_separator ? 1 : 0;
    if (left_length > SIZE_MAX - separator_length ||
        left_length + separator_length > SIZE_MAX - right_length) {
        cinder_panic("joined path length overflow");
    }
    CinderString result =
        cinder_allocate_string(left_length + separator_length + right_length);
    (void)memcpy(result.data, left, left_length);
    size_t offset = left_length;
    if (needs_separator) {
        result.data[offset] = '/';
        offset += 1;
    }
    (void)memcpy(result.data + offset, right, right_length);
    return result;
}

CinderString cinder_path_with_suffix(const char *path, const char *suffix)
{
    const size_t length = cinder_path_validated_length(path);
    const size_t suffix_length = cinder_path_validated_length(suffix);
    if (suffix_length > 0 && suffix[0] != '.') {
        cinder_panic("path suffix must be empty or begin with '.'");
    }
    for (size_t index = 0; index < suffix_length; ++index) {
        if (suffix[index] == '/') {
            cinder_panic("path suffix cannot contain '/'");
        }
    }

    const size_t end = cinder_path_trimmed_end(path, length);
    const size_t start = cinder_path_component_start(path, end);
    if (start == end) {
        cinder_panic("cannot set suffix on a path without a name");
    }

    const size_t prefix_end = cinder_path_suffix_start(path, start, end);
    if (prefix_end > SIZE_MAX - suffix_length) {
        cinder_panic("suffixed path length overflow");
    }
    CinderString result = cinder_allocate_string(prefix_end + suffix_length);
    (void)memcpy(result.data, path, prefix_end);
    (void)memcpy(result.data + prefix_end, suffix, suffix_length);
    return result;
}

#if defined(_WIN32)
static CINDER_NORETURN void cinder_path_unsupported(void)
{
    cinder_panic("std.path filesystem operations are not implemented on Windows");
}

bool cinder_path_exists(const char *path)
{
    (void)path;
    cinder_path_unsupported();
}

bool cinder_path_is_file(const char *path)
{
    (void)path;
    cinder_path_unsupported();
}

bool cinder_path_is_dir(const char *path)
{
    (void)path;
    cinder_path_unsupported();
}

void cinder_path_create_dir(const char *path)
{
    (void)path;
    cinder_path_unsupported();
}

void cinder_path_create_dir_all(const char *path)
{
    (void)path;
    cinder_path_unsupported();
}

void cinder_path_remove_file(const char *path)
{
    (void)path;
    cinder_path_unsupported();
}

void cinder_path_rename(const char *source, const char *destination)
{
    (void)source;
    (void)destination;
    cinder_path_unsupported();
}
#else
static CINDER_NORETURN void cinder_path_panic_errno(
    const char *operation,
    const char *path
)
{
    const int error = errno;
    char message[512];
    (void)snprintf(
        message,
        sizeof(message),
        "%s '%s': %s",
        operation,
        path,
        strerror(error)
    );
    cinder_panic(message);
}

static void cinder_path_create_dir_component(const char *path)
{
    if (mkdir(path, 0777) == 0) {
        return;
    }
    if (errno == EEXIST) {
        struct stat status;
        if (stat(path, &status) == 0 && S_ISDIR(status.st_mode)) {
            return;
        }
    }
    cinder_path_panic_errno("failed to create directory", path);
}

bool cinder_path_exists(const char *path)
{
    (void)cinder_path_validated_length(path);
    struct stat status;
    return stat(path, &status) == 0;
}

bool cinder_path_is_file(const char *path)
{
    (void)cinder_path_validated_length(path);
    struct stat status;
    return stat(path, &status) == 0 && S_ISREG(status.st_mode);
}

bool cinder_path_is_dir(const char *path)
{
    (void)cinder_path_validated_length(path);
    struct stat status;
    return stat(path, &status) == 0 && S_ISDIR(status.st_mode);
}

void cinder_path_create_dir(const char *path)
{
    (void)cinder_path_validated_length(path);
    if (mkdir(path, 0777) != 0) {
        cinder_path_panic_errno("failed to create directory", path);
    }
}

void cinder_path_create_dir_all(const char *path)
{
    size_t length = cinder_path_validated_length(path);
    if (length == 0) {
        return;
    }

    char *copy = cinder_alloc(length + 1, sizeof(*copy));
    (void)memcpy(copy, path, length + 1);
    while (length > 1 && copy[length - 1] == '/') {
        copy[length - 1] = '\0';
        length -= 1;
    }
    if (length == 1 && copy[0] == '/') {
        free(copy);
        return;
    }

    for (size_t index = 1; index < length; ++index) {
        if (copy[index] != '/') {
            continue;
        }
        copy[index] = '\0';
        cinder_path_create_dir_component(copy);
        copy[index] = '/';
    }
    cinder_path_create_dir_component(copy);
    free(copy);
}

void cinder_path_remove_file(const char *path)
{
    (void)cinder_path_validated_length(path);
    if (unlink(path) != 0) {
        cinder_path_panic_errno("failed to remove file", path);
    }
}

void cinder_path_rename(const char *source, const char *destination)
{
    (void)cinder_path_validated_length(source);
    (void)cinder_path_validated_length(destination);
    if (rename(source, destination) != 0) {
        cinder_path_panic_errno("failed to rename path", source);
    }
}
#endif

CinderString cinder_string_clone(const CinderString *string)
{
    cinder_validate_string(string);
    return cinder_string_from_bytes(string->data, string->length);
}

void cinder_string_drop(CinderString *string)
{
    cinder_validate_string(string);
    if (string->capacity != 0) {
        free(string->data);
    }
    string->data = NULL;
    string->length = 0;
    string->capacity = 0;
}

void cinder_string_reserve(CinderString *string, size_t minimum_capacity)
{
    cinder_validate_string(string);
    if (minimum_capacity == SIZE_MAX) {
        cinder_panic("string capacity overflow");
    }

    size_t content_capacity = minimum_capacity;
    if (content_capacity < string->length) {
        content_capacity = string->length;
    }
    const size_t required_capacity = content_capacity + 1;

    if (string->capacity == 0) {
        if (string->data == NULL && minimum_capacity == 0) {
            return;
        }
        const size_t next_capacity =
            cinder_grown_string_capacity(0, required_capacity);
        char *owned = cinder_alloc(next_capacity, sizeof(char));
        if (string->length != 0) {
            (void)memcpy(owned, string->data, string->length);
        }
        owned[string->length] = '\0';
        string->data = owned;
        string->capacity = next_capacity;
        return;
    }

    if (string->capacity >= required_capacity) {
        return;
    }
    const size_t next_capacity =
        cinder_grown_string_capacity(string->capacity, required_capacity);
    char *grown = realloc(string->data, next_capacity);
    if (grown == NULL) {
        cinder_panic("out of memory");
    }
    string->data = grown;
    string->capacity = next_capacity;
}

void cinder_string_clear(CinderString *string)
{
    cinder_validate_string(string);
    if (string->data == NULL) {
        return;
    }
    if (string->capacity == 0) {
        cinder_string_reserve(string, 0);
    }
    string->length = 0;
    string->data[0] = '\0';
}

void cinder_string_append(
    CinderString *string,
    const CinderString *suffix
)
{
    cinder_validate_string(string);
    cinder_validate_string(suffix);
    if (suffix->length == 0) {
        return;
    }
    if (string->length > SIZE_MAX - suffix->length) {
        cinder_panic("string length overflow");
    }

    const size_t original_length = string->length;
    const size_t suffix_length = suffix->length;
    const bool append_self = string == suffix;
    const char *suffix_data = suffix->data;
    cinder_string_reserve(string, original_length + suffix_length);
    if (append_self) {
        suffix_data = string->data;
    }
    (void)memmove(
        string->data + original_length,
        suffix_data,
        suffix_length
    );
    string->length = original_length + suffix_length;
    string->data[string->length] = '\0';
}

void cinder_string_append_char(CinderString *string, char value)
{
    cinder_validate_string(string);
    if (value == '\0' || (unsigned char)value > UINT8_C(0x7f)) {
        cinder_panic("string character must be non-NUL ASCII");
    }
    if (string->length == SIZE_MAX) {
        cinder_panic("string length overflow");
    }

    const size_t original_length = string->length;
    cinder_string_reserve(string, original_length + 1);
    string->data[original_length] = value;
    string->length = original_length + 1;
    string->data[string->length] = '\0';
}

CinderString cinder_string_concat(
    const CinderString *left,
    const CinderString *right
)
{
    cinder_validate_string(left);
    cinder_validate_string(right);
    if (left->length > SIZE_MAX - right->length) {
        cinder_panic("string length overflow");
    }

    CinderString result =
        cinder_allocate_string(left->length + right->length);
    if (left->length != 0) {
        (void)memcpy(result.data, left->data, left->length);
    }
    if (right->length != 0) {
        (void)memcpy(
            result.data + left->length,
            right->data,
            right->length
        );
    }
    return result;
}

uint8_t cinder_string_byte_at(const CinderString *string, size_t index)
{
    cinder_validate_string_structure(string);
    if (index >= string->length) {
        cinder_panic("string byte index out of bounds");
    }
    return (uint8_t)(unsigned char)string->data[index];
}

static bool cinder_string_is_utf8_boundary(
    const CinderString *string,
    size_t index
)
{
    if (index == 0 || index == string->length) {
        return true;
    }
    const unsigned char value = (unsigned char)string->data[index];
    return value < UINT8_C(0x80) || value > UINT8_C(0xbf);
}

CinderString cinder_string_slice(
    const CinderString *string,
    size_t start,
    size_t end
)
{
    cinder_validate_string_structure(string);
    if (start > end || end > string->length) {
        cinder_panic("string slice bounds are invalid");
    }
    if (!cinder_string_is_utf8_boundary(string, start) ||
        !cinder_string_is_utf8_boundary(string, end)) {
        cinder_panic("string slice bound is not a UTF-8 boundary");
    }
    return cinder_string_from_bytes(
        string->data == NULL ? NULL : string->data + start,
        end - start
    );
}

uint64_t cinder_string_hash_value(const CinderString *string)
{
    cinder_validate_string(string);
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t index = 0; index < string->length; ++index) {
        hash ^= (uint64_t)(unsigned char)string->data[index];
        hash *= UINT64_C(1099511628211);
    }
    return cinder_hash_u64(hash);
}

bool cinder_string_equal_value(
    const CinderString *left,
    const CinderString *right
)
{
    cinder_validate_string(left);
    cinder_validate_string(right);
    if (left->length != right->length) {
        return false;
    }
    return left->length == 0 ||
        memcmp(left->data, right->data, left->length) == 0;
}

int cinder_string_compare_value(
    const CinderString *left,
    const CinderString *right
)
{
    cinder_validate_string(left);
    cinder_validate_string(right);
    const size_t shared_length =
        left->length < right->length ? left->length : right->length;
    if (shared_length != 0) {
        const int compared = memcmp(left->data, right->data, shared_length);
        if (compared < 0) {
            return -1;
        }
        if (compared > 0) {
            return 1;
        }
    }
    if (left->length < right->length) {
        return -1;
    }
    if (left->length > right->length) {
        return 1;
    }
    return 0;
}

const char *cinder_string_cstr(const CinderString *string)
{
    if (string == NULL || string->data == NULL) {
        return "";
    }
    cinder_validate_string(string);
    return string->data;
}

void cinder_string_builder_init(CinderStringBuilder *builder)
{
    if (builder == NULL) {
        cinder_panic("invalid string builder argument");
    }
    builder->data = NULL;
    builder->length = 0;
    builder->capacity = 0;
}

void cinder_string_builder_drop(CinderStringBuilder *builder)
{
    cinder_validate_builder(builder);
    free(builder->data);
    builder->data = NULL;
    builder->length = 0;
    builder->capacity = 0;
}

static void cinder_string_builder_reserve_raw(
    CinderStringBuilder *builder,
    size_t minimum_capacity
)
{
    cinder_validate_builder_structure(builder);
    if (minimum_capacity == SIZE_MAX) {
        cinder_panic("string builder capacity overflow");
    }
    const size_t required_capacity = minimum_capacity + 1;
    if (builder->capacity >= required_capacity) {
        return;
    }

    const size_t next_capacity =
        cinder_grown_string_capacity(builder->capacity, required_capacity);
    char *grown = realloc(builder->data, next_capacity);
    if (grown == NULL) {
        cinder_panic("out of memory");
    }
    builder->data = grown;
    builder->capacity = next_capacity;
    builder->data[builder->length] = '\0';
}

void cinder_string_builder_reserve(
    CinderStringBuilder *builder,
    size_t minimum_capacity
)
{
    cinder_validate_builder(builder);
    cinder_string_builder_reserve_raw(builder, minimum_capacity);
}

static void cinder_string_builder_append_raw(
    CinderStringBuilder *builder,
    const char *data,
    size_t length
)
{
    cinder_validate_builder_structure(builder);
    if (data == NULL && length != 0) {
        cinder_panic("invalid string builder bytes");
    }
    if (builder->length > SIZE_MAX - length) {
        cinder_panic("string builder length overflow");
    }

    const size_t original_length = builder->length;
    cinder_string_builder_reserve_raw(builder, original_length + length);
    if (length != 0) {
        (void)memmove(builder->data + original_length, data, length);
    }
    builder->length = original_length + length;
    if (builder->data != NULL) {
        builder->data[builder->length] = '\0';
    }
}

void cinder_string_builder_append(
    CinderStringBuilder *builder,
    const CinderString *string
)
{
    cinder_validate_builder_structure(builder);
    cinder_validate_string_structure(string);
    cinder_string_builder_append_raw(builder, string->data, string->length);
}

void cinder_string_builder_append_char(
    CinderStringBuilder *builder,
    char value
)
{
    cinder_validate_builder_structure(builder);
    if (value == '\0' || (unsigned char)value > UINT8_C(0x7f)) {
        cinder_panic("string character must be non-NUL ASCII");
    }
    cinder_string_builder_append_raw(builder, &value, 1);
}

CinderString cinder_string_builder_finish(CinderStringBuilder *builder)
{
    cinder_validate_builder(builder);
    CinderString string;
    string.data = builder->data;
    string.length = builder->length;
    string.capacity = builder->capacity;
    builder->data = NULL;
    builder->length = 0;
    builder->capacity = 0;
    return string;
}

static void cinder_print_repr_byte(unsigned char value, bool escape_non_ascii)
{
    switch (value) {
        case '\'':
            (void)fputs("\\'", stdout);
            break;
        case '\\':
            (void)fputs("\\\\", stdout);
            break;
        case '\n':
            (void)fputs("\\n", stdout);
            break;
        case '\r':
            (void)fputs("\\r", stdout);
            break;
        case '\t':
            (void)fputs("\\t", stdout);
            break;
        case '\0':
            (void)fputs("\\0", stdout);
            break;
        default:
            if (value < 32 || (escape_non_ascii && value >= 127)) {
                (void)printf("\\x%02x", value);
            } else {
                (void)putchar((int)value);
            }
            break;
    }
}

void cinder_print_repr_char(char value)
{
    (void)putchar('\'');
    cinder_print_repr_byte((unsigned char)value, true);
    (void)putchar('\'');
}

void cinder_print_repr_string(const char *text)
{
    (void)putchar('\'');
    if (text != NULL) {
        for (const unsigned char *cursor = (const unsigned char *)text; *cursor != '\0'; ++cursor) {
            cinder_print_repr_byte(*cursor, false);
        }
    }
    (void)putchar('\'');
}

bool cinder_read_line(FILE *stream, CinderString *out)
{
    if (stream == NULL || out == NULL) {
        cinder_panic("invalid read line arguments");
    }
    *out = cinder_empty_string();

    CinderStringBuilder builder;
    cinder_string_builder_init(&builder);
    bool read_anything = false;

    for (;;) {
        const int character = fgetc(stream);
        if (character == EOF) {
            if (ferror(stream)) {
                cinder_string_builder_drop(&builder);
                cinder_panic("input read failed");
            }
            if (!read_anything) {
                cinder_string_builder_drop(&builder);
                return false;
            }
            break;
        }

        read_anything = true;
        if (character == '\n') {
            if (builder.length != 0 &&
                builder.data[builder.length - 1] == '\r') {
                builder.length -= 1;
                builder.data[builder.length] = '\0';
            }
            break;
        }

        const char byte = (char)(unsigned char)character;
        cinder_string_builder_append_raw(&builder, &byte, 1);
    }

    *out = cinder_string_builder_finish(&builder);
    return true;
}

CinderString cinder_read_all_text(FILE *stream)
{
    if (stream == NULL) {
        cinder_panic("invalid text stream");
    }

    CinderStringBuilder builder;
    cinder_string_builder_init(&builder);
    char buffer[4096];
    for (;;) {
        const size_t count = fread(buffer, sizeof(char), sizeof(buffer), stream);
        if (count != 0) {
            cinder_string_builder_append_raw(&builder, buffer, count);
        }
        if (count < sizeof(buffer)) {
            if (ferror(stream)) {
                cinder_string_builder_drop(&builder);
                cinder_panic("input read failed");
            }
            break;
        }
    }
    return cinder_string_builder_finish(&builder);
}

CinderString cinder_input(const char *prompt)
{
    if (prompt != NULL) {
        if (fputs(prompt, stdout) == EOF || fflush(stdout) == EOF) {
            cinder_panic("input prompt write failed");
        }
    }

    CinderString input;
    if (!cinder_read_line(stdin, &input)) {
        cinder_panic("input reached EOF");
    }
    return input;
}

static const char *cinder_skip_whitespace(const char *text)
{
    while (text != NULL && *text != '\0' && isspace((unsigned char)*text)) {
        text += 1;
    }
    return text;
}

static bool cinder_finish_parse(char *end, CinderParseError *error)
{
    if (end == NULL) {
        if (error != NULL) {
            *error = CinderParseError_invalid;
        }
        return false;
    }
    end = (char *)cinder_skip_whitespace(end);
    if (*end != '\0') {
        if (error != NULL) {
            *error = CinderParseError_invalid;
        }
        return false;
    }
    return true;
}

static bool cinder_prepare_parse(const char **text, CinderParseError *error)
{
    if (text == NULL || *text == NULL) {
        if (error != NULL) {
            *error = CinderParseError_empty;
        }
        return false;
    }
    *text = cinder_skip_whitespace(*text);
    if (**text == '\0') {
        if (error != NULL) {
            *error = CinderParseError_empty;
        }
        return false;
    }
    return true;
}

bool cinder_parse_i64(const char *text, int64_t *out, CinderParseError *error)
{
    if (!cinder_prepare_parse(&text, error)) {
        return false;
    }

    errno = 0;
    char *end = NULL;
    const long long value = strtoll(text, &end, 10);
    if (end == text) {
        if (error != NULL) {
            *error = CinderParseError_invalid;
        }
        return false;
    }
    if (!cinder_finish_parse(end, error)) {
        return false;
    }
    if (errno == ERANGE || value < INT64_MIN || value > INT64_MAX) {
        if (error != NULL) {
            *error = CinderParseError_overflow;
        }
        return false;
    }
    if (out != NULL) {
        *out = (int64_t)value;
    }
    return true;
}

bool cinder_parse_i32(const char *text, int32_t *out, CinderParseError *error)
{
    int64_t value = 0;
    if (!cinder_parse_i64(text, &value, error)) {
        return false;
    }
    if (value < INT32_MIN || value > INT32_MAX) {
        if (error != NULL) {
            *error = CinderParseError_overflow;
        }
        return false;
    }
    if (out != NULL) {
        *out = (int32_t)value;
    }
    return true;
}

bool cinder_parse_u64(const char *text, uint64_t *out, CinderParseError *error)
{
    if (!cinder_prepare_parse(&text, error)) {
        return false;
    }
    if (*text == '-') {
        if (error != NULL) {
            *error = CinderParseError_overflow;
        }
        return false;
    }

    errno = 0;
    char *end = NULL;
    const unsigned long long value = strtoull(text, &end, 10);
    if (end == text) {
        if (error != NULL) {
            *error = CinderParseError_invalid;
        }
        return false;
    }
    if (!cinder_finish_parse(end, error)) {
        return false;
    }
    if (errno == ERANGE || value > UINT64_MAX) {
        if (error != NULL) {
            *error = CinderParseError_overflow;
        }
        return false;
    }
    if (out != NULL) {
        *out = (uint64_t)value;
    }
    return true;
}

bool cinder_parse_u32(const char *text, uint32_t *out, CinderParseError *error)
{
    uint64_t value = 0;
    if (!cinder_parse_u64(text, &value, error)) {
        return false;
    }
    if (value > UINT32_MAX) {
        if (error != NULL) {
            *error = CinderParseError_overflow;
        }
        return false;
    }
    if (out != NULL) {
        *out = (uint32_t)value;
    }
    return true;
}

bool cinder_parse_isize(const char *text, ptrdiff_t *out, CinderParseError *error)
{
    int64_t value = 0;
    if (!cinder_parse_i64(text, &value, error)) {
        return false;
    }
#if PTRDIFF_MAX < INT64_MAX || PTRDIFF_MIN > INT64_MIN
    if (value < (int64_t)PTRDIFF_MIN || value > (int64_t)PTRDIFF_MAX) {
        if (error != NULL) {
            *error = CinderParseError_overflow;
        }
        return false;
    }
#endif
    if (out != NULL) {
        *out = (ptrdiff_t)value;
    }
    return true;
}

bool cinder_parse_usize(const char *text, size_t *out, CinderParseError *error)
{
    uint64_t value = 0;
    if (!cinder_parse_u64(text, &value, error)) {
        return false;
    }
#if SIZE_MAX < UINT64_MAX
    if (value > (uint64_t)SIZE_MAX) {
        if (error != NULL) {
            *error = CinderParseError_overflow;
        }
        return false;
    }
#endif
    if (out != NULL) {
        *out = (size_t)value;
    }
    return true;
}

bool cinder_parse_f64(const char *text, double *out, CinderParseError *error)
{
    if (!cinder_prepare_parse(&text, error)) {
        return false;
    }

    errno = 0;
    char *end = NULL;
    const double value = strtod(text, &end);
    if (end == text) {
        if (error != NULL) {
            *error = CinderParseError_invalid;
        }
        return false;
    }
    if (!cinder_finish_parse(end, error)) {
        return false;
    }
    if (errno == ERANGE && !isfinite(value)) {
        if (error != NULL) {
            *error = CinderParseError_overflow;
        }
        return false;
    }
    if (out != NULL) {
        *out = value;
    }
    return true;
}

uint64_t cinder_f64_snapshot_bits(double value)
{
    uint64_t bits = 0;
    _Static_assert(sizeof(bits) == sizeof(value), "f64 snapshot requires 64-bit double");
    (void)memcpy(&bits, &value, sizeof(bits));
    return bits;
}

bool cinder_parse_f32(const char *text, float *out, CinderParseError *error)
{
    if (!cinder_prepare_parse(&text, error)) {
        return false;
    }

    errno = 0;
    char *end = NULL;
    const float value = strtof(text, &end);
    if (end == text) {
        if (error != NULL) {
            *error = CinderParseError_invalid;
        }
        return false;
    }
    if (!cinder_finish_parse(end, error)) {
        return false;
    }
    if (errno == ERANGE && !isfinite(value)) {
        if (error != NULL) {
            *error = CinderParseError_overflow;
        }
        return false;
    }
    if (out != NULL) {
        *out = value;
    }
    return true;
}

bool cinder_parse_bool(const char *text, bool *out, CinderParseError *error)
{
    if (!cinder_prepare_parse(&text, error)) {
        return false;
    }

    bool value = false;
    const char *end = text;
    if (strncmp(text, "true", 4) == 0) {
        value = true;
        end = text + 4;
    } else if (strncmp(text, "false", 5) == 0) {
        value = false;
        end = text + 5;
    } else {
        if (error != NULL) {
            *error = CinderParseError_invalid;
        }
        return false;
    }
    if (!cinder_finish_parse((char *)end, error)) {
        return false;
    }
    if (out != NULL) {
        *out = value;
    }
    return true;
}

static CinderString cinder_format_string(const char *format, ...)
{
    if (format == NULL) {
        cinder_panic("invalid string format");
    }

    va_list arguments;
    va_start(arguments, format);
    va_list measured_arguments;
    va_copy(measured_arguments, arguments);
    const int written = vsnprintf(NULL, 0, format, measured_arguments);
    va_end(measured_arguments);
    if (written < 0) {
        va_end(arguments);
        cinder_panic("string formatting failed");
    }

    CinderString string = cinder_allocate_string((size_t)written);
    const int actual = vsnprintf(
        string.data,
        string.capacity,
        format,
        arguments
    );
    va_end(arguments);
    if (actual < 0 || actual != written) {
        free(string.data);
        cinder_panic("string formatting failed");
    }
    if (!cinder_utf8_is_valid(string.data, string.length)) {
        free(string.data);
        cinder_panic("invalid UTF-8 formatted string");
    }
    return string;
}

CinderString cinder_i8_to_string(int8_t value)
{
    return cinder_format_string("%" PRId8, value);
}

CinderString cinder_i16_to_string(int16_t value)
{
    return cinder_format_string("%" PRId16, value);
}

CinderString cinder_i32_to_string(int32_t value)
{
    return cinder_format_string("%" PRId32, value);
}

CinderString cinder_i64_to_string(int64_t value)
{
    return cinder_format_string("%" PRId64, value);
}

CinderString cinder_u8_to_string(uint8_t value)
{
    return cinder_format_string("%" PRIu8, value);
}

CinderString cinder_u16_to_string(uint16_t value)
{
    return cinder_format_string("%" PRIu16, value);
}

CinderString cinder_u32_to_string(uint32_t value)
{
    return cinder_format_string("%" PRIu32, value);
}

CinderString cinder_u64_to_string(uint64_t value)
{
    return cinder_format_string("%" PRIu64, value);
}

CinderString cinder_isize_to_string(ptrdiff_t value)
{
    return cinder_format_string("%td", value);
}

CinderString cinder_usize_to_string(size_t value)
{
    return cinder_format_string("%zu", value);
}

CinderString cinder_f32_to_string(float value)
{
    return cinder_format_string("%g", (double)value);
}

CinderString cinder_f64_to_string(double value)
{
    return cinder_format_string("%g", value);
}

CinderString cinder_bool_to_string(bool value)
{
    return cinder_string_from_cstr(value ? "true" : "false");
}

CinderString cinder_char_to_string(char value)
{
    return cinder_string_from_bytes(&value, 1);
}

static void cinder_merge_sort(
    unsigned char *base,
    unsigned char *buffer,
    size_t count,
    size_t element_size,
    CinderCompareFn compare
)
{
    if (count < 2) {
        return;
    }

    const size_t left_count = count / 2;
    const size_t right_count = count - left_count;
    unsigned char *right = base + left_count * element_size;
    unsigned char *right_buffer = buffer + left_count * element_size;

    cinder_merge_sort(base, buffer, left_count, element_size, compare);
    cinder_merge_sort(right, right_buffer, right_count, element_size, compare);

    size_t left_index = 0;
    size_t right_index = 0;
    size_t output_index = 0;
    while (left_index < left_count && right_index < right_count) {
        unsigned char *left_value = base + left_index * element_size;
        unsigned char *right_value = right + right_index * element_size;
        unsigned char *output = buffer + output_index * element_size;
        if (compare(left_value, right_value) <= 0) {
            (void)memcpy(output, left_value, element_size);
            left_index += 1;
        } else {
            (void)memcpy(output, right_value, element_size);
            right_index += 1;
        }
        output_index += 1;
    }

    if (left_index < left_count) {
        (void)memcpy(
            buffer + output_index * element_size,
            base + left_index * element_size,
            (left_count - left_index) * element_size
        );
    } else if (right_index < right_count) {
        (void)memcpy(
            buffer + output_index * element_size,
            right + right_index * element_size,
            (right_count - right_index) * element_size
        );
    }
    (void)memcpy(base, buffer, count * element_size);
}

void cinder_sort(
    void *base,
    size_t count,
    size_t element_size,
    CinderCompareFn compare
)
{
    if (count < 2) {
        return;
    }
    if (base == NULL || compare == NULL || element_size == 0) {
        cinder_panic("invalid sort arguments");
    }

    unsigned char *buffer = cinder_alloc(count, element_size);
    cinder_merge_sort(base, buffer, count, element_size, compare);
    free(buffer);
}
