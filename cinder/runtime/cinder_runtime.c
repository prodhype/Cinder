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

static void cinder_validate_string(const CinderString *string)
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
    if (!cinder_utf8_is_valid(string->data, string->length)) {
        cinder_panic("invalid UTF-8 string");
    }
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
    cinder_validate_string(string);
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
    cinder_validate_string(string);
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
    cinder_validate_builder(builder);
    cinder_validate_string(string);
    cinder_string_builder_append_raw(builder, string->data, string->length);
}

void cinder_string_builder_append_char(
    CinderStringBuilder *builder,
    char value
)
{
    cinder_validate_builder(builder);
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
