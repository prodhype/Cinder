#include "cinder_runtime.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

CINDER_NORETURN void cinder_panic(const char *message)
{
    const char *text = message != NULL ? message : "Cinder panic";
    (void)fprintf(stderr, "panic: %s\n", text);
    abort();
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

char *cinder_input(const char *prompt)
{
    if (prompt != NULL) {
        if (fputs(prompt, stdout) == EOF || fflush(stdout) == EOF) {
            cinder_panic("input prompt write failed");
        }
    }

    size_t capacity = 64;
    size_t length = 0;
    char *buffer = cinder_alloc(capacity, sizeof(char));

    for (;;) {
        int character = fgetc(stdin);
        if (character == EOF) {
            if (ferror(stdin)) {
                free(buffer);
                cinder_panic("input read failed");
            }
            if (length == 0) {
                free(buffer);
                cinder_panic("input reached EOF");
            }
            break;
        }
        if (character == '\n') {
            break;
        }

        if (length + 1 >= capacity) {
            if (capacity > SIZE_MAX / 2) {
                free(buffer);
                cinder_panic("input line is too long");
            }
            size_t next_capacity = capacity * 2;
            char *grown = realloc(buffer, next_capacity);
            if (grown == NULL) {
                free(buffer);
                cinder_panic("out of memory");
            }
            buffer = grown;
            capacity = next_capacity;
        }
        buffer[length] = (char)character;
        length += 1;
    }

    if (length > 0 && buffer[length - 1] == '\r') {
        length -= 1;
    }
    buffer[length] = '\0';
    return buffer;
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
