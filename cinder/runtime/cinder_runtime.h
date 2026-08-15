#ifndef CINDER_RUNTIME_H
#define CINDER_RUNTIME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#if !defined(__cplusplus)
#include <stdatomic.h>
#endif

#if defined(__cplusplus)
#define CINDER_NORETURN [[noreturn]]
#define CINDER_MAYBE_UNUSED
#define CINDER_ALIGNOF(type) alignof(type)
#define CINDER_STATIC_ASSERT(condition, message) static_assert((condition), message)
#elif defined(_MSC_VER)
#define CINDER_NORETURN __declspec(noreturn)
#define CINDER_MAYBE_UNUSED
#define CINDER_ALIGNOF(type) __alignof(type)
#define CINDER_STATIC_ASSERT(condition, message) _Static_assert((condition), message)
#elif defined(__GNUC__) || defined(__clang__)
#define CINDER_NORETURN _Noreturn
#define CINDER_MAYBE_UNUSED __attribute__((unused))
#define CINDER_ALIGNOF(type) _Alignof(type)
#define CINDER_STATIC_ASSERT(condition, message) _Static_assert((condition), message)
#else
#define CINDER_NORETURN _Noreturn
#define CINDER_MAYBE_UNUSED
#define CINDER_ALIGNOF(type) _Alignof(type)
#define CINDER_STATIC_ASSERT(condition, message) _Static_assert((condition), message)
#endif

#define CINDER_ARRAY_LEN(array) (sizeof(array) / sizeof((array)[0]))
#define CINDER_PI 3.14159265358979323846264338327950288

typedef enum CinderTypeKind {
    CINDER_TYPE_PRIMITIVE = 0,
    CINDER_TYPE_STRUCT = 1,
    CINDER_TYPE_CLASS = 2,
    CINDER_TYPE_ENUM = 3,
    CINDER_TYPE_UNION = 4,
    CINDER_TYPE_VARIANT = 5
} CinderTypeKind;

typedef struct CinderFieldInfo {
    const char *name;
    const char *type_name;
    size_t offset;
    size_t size;
    size_t alignment;
    bool is_private;
} CinderFieldInfo;

typedef struct CinderMethodInfo {
    const char *name;
    const char *signature;
    const char *return_type_name;
    size_t parameter_count;
    bool is_abstract;
    bool is_override;
} CinderMethodInfo;

typedef struct CinderTypeInfo {
    const char *name;
    CinderTypeKind kind;
    size_t size;
    size_t alignment;
    const CinderFieldInfo *fields;
    size_t field_count;
    const CinderMethodInfo *methods;
    size_t method_count;
} CinderTypeInfo;

typedef struct CinderString {
    char *data;
    size_t length;
    size_t capacity;
} CinderString;

typedef struct CinderStringBuilder {
    char *data;
    size_t length;
    size_t capacity;
} CinderStringBuilder;

typedef struct CinderProcessResult {
    int32_t exit_code;
    CinderString stdout;
    CinderString stderr;
} CinderProcessResult;

typedef int (*CinderCompareFn)(const void *left, const void *right);

typedef struct CinderLockState CinderLockState;
typedef CinderLockState *CinderLock;

#if !defined(__cplusplus)
struct CinderLockState {
    atomic_flag held;
    size_t order_key;
};
#define CINDER_LOCK_STATE_INIT(key) { ATOMIC_FLAG_INIT, (key) }
#endif

typedef enum CinderParseError {
    CinderParseError_empty = 0,
    CinderParseError_invalid = 1,
    CinderParseError_overflow = 2
} CinderParseError;

#ifdef __cplusplus
extern "C" {
#endif

CINDER_NORETURN void cinder_panic(const char *message);
void *cinder_alloc(size_t count, size_t element_size);
void *cinder_grow_array(
    void *data,
    size_t *capacity,
    size_t minimum_capacity,
    size_t element_size
);
void cinder_write_stdout(const CinderString *text);
void cinder_write_stderr(const CinderString *text);
uint64_t cinder_hash_u64(uint64_t value);
uint64_t cinder_hash_string(const char *text);
bool cinder_string_equal(const char *left, const char *right);
char *cinder_clone_string(const char *text);
CinderString cinder_string_from_bytes(const char *data, size_t length);
CinderString cinder_string_from_cstr(const char *text);
CinderString cinder_string_clone(const CinderString *string);
void cinder_string_drop(CinderString *string);
void cinder_string_reserve(CinderString *string, size_t minimum_capacity);
void cinder_string_clear(CinderString *string);
void cinder_string_append(CinderString *string, const CinderString *suffix);
void cinder_string_append_char(CinderString *string, char value);
CinderString cinder_string_concat(
    const CinderString *left,
    const CinderString *right
);
uint8_t cinder_string_byte_at(const CinderString *string, size_t index);
CinderString cinder_string_slice(
    const CinderString *string,
    size_t start,
    size_t end
);
uint64_t cinder_string_hash_value(const CinderString *string);
bool cinder_string_equal_value(
    const CinderString *left,
    const CinderString *right
);
int cinder_string_compare_value(
    const CinderString *left,
    const CinderString *right
);
const char *cinder_string_cstr(const CinderString *string);
void cinder_string_builder_init(CinderStringBuilder *builder);
void cinder_string_builder_drop(CinderStringBuilder *builder);
void cinder_string_builder_reserve(
    CinderStringBuilder *builder,
    size_t minimum_capacity
);
void cinder_string_builder_append(
    CinderStringBuilder *builder,
    const CinderString *string
);
void cinder_string_builder_append_char(
    CinderStringBuilder *builder,
    char value
);
CinderString cinder_string_builder_finish(CinderStringBuilder *builder);
void CinderProcessResult__drop(CinderProcessResult *self);
CinderProcessResult cinder_process_run_argv(
    size_t argc,
    const char *const *argv
);
bool cinder_read_line(FILE *stream, CinderString *out);
CinderString cinder_read_all_text(FILE *stream);
CinderString cinder_input(const char *prompt);
bool cinder_parse_i32(const char *text, int32_t *out, CinderParseError *error);
bool cinder_parse_i64(const char *text, int64_t *out, CinderParseError *error);
bool cinder_parse_u32(const char *text, uint32_t *out, CinderParseError *error);
bool cinder_parse_u64(const char *text, uint64_t *out, CinderParseError *error);
bool cinder_parse_isize(const char *text, ptrdiff_t *out, CinderParseError *error);
bool cinder_parse_usize(const char *text, size_t *out, CinderParseError *error);
bool cinder_parse_f32(const char *text, float *out, CinderParseError *error);
bool cinder_parse_f64(const char *text, double *out, CinderParseError *error);
bool cinder_parse_bool(const char *text, bool *out, CinderParseError *error);
CinderString cinder_i8_to_string(int8_t value);
CinderString cinder_i16_to_string(int16_t value);
CinderString cinder_i32_to_string(int32_t value);
CinderString cinder_i64_to_string(int64_t value);
CinderString cinder_u8_to_string(uint8_t value);
CinderString cinder_u16_to_string(uint16_t value);
CinderString cinder_u32_to_string(uint32_t value);
CinderString cinder_u64_to_string(uint64_t value);
CinderString cinder_isize_to_string(ptrdiff_t value);
CinderString cinder_usize_to_string(size_t value);
CinderString cinder_f32_to_string(float value);
CinderString cinder_f64_to_string(double value);
CinderString cinder_bool_to_string(bool value);
CinderString cinder_char_to_string(char value);
void cinder_print_repr_char(char value);
void cinder_print_repr_string(const char *text);
double cinder_wall_time(void);
void cinder_sort(
    void *base,
    size_t count,
    size_t element_size,
    CinderCompareFn compare
);
void cinder_lock_acquire(CinderLock lock);
void cinder_lock_release(CinderLock lock);
int cinder_lock_compare(CinderLock left, CinderLock right);

#ifdef __cplusplus
}
#endif

#endif
