#ifndef CINDER_RUNTIME_H
#define CINDER_RUNTIME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

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

typedef int (*CinderCompareFn)(const void *left, const void *right);

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
uint64_t cinder_hash_u64(uint64_t value);
uint64_t cinder_hash_string(const char *text);
bool cinder_string_equal(const char *left, const char *right);
char *cinder_clone_string(const char *text);
char *cinder_input(const char *prompt);
bool cinder_parse_i32(const char *text, int32_t *out, CinderParseError *error);
bool cinder_parse_i64(const char *text, int64_t *out, CinderParseError *error);
bool cinder_parse_u32(const char *text, uint32_t *out, CinderParseError *error);
bool cinder_parse_u64(const char *text, uint64_t *out, CinderParseError *error);
bool cinder_parse_isize(const char *text, ptrdiff_t *out, CinderParseError *error);
bool cinder_parse_usize(const char *text, size_t *out, CinderParseError *error);
bool cinder_parse_f32(const char *text, float *out, CinderParseError *error);
bool cinder_parse_f64(const char *text, double *out, CinderParseError *error);
bool cinder_parse_bool(const char *text, bool *out, CinderParseError *error);
char *cinder_i8_to_string(int8_t value);
char *cinder_i16_to_string(int16_t value);
char *cinder_i32_to_string(int32_t value);
char *cinder_i64_to_string(int64_t value);
char *cinder_u8_to_string(uint8_t value);
char *cinder_u16_to_string(uint16_t value);
char *cinder_u32_to_string(uint32_t value);
char *cinder_u64_to_string(uint64_t value);
char *cinder_isize_to_string(ptrdiff_t value);
char *cinder_usize_to_string(size_t value);
char *cinder_f32_to_string(float value);
char *cinder_f64_to_string(double value);
char *cinder_bool_to_string(bool value);
char *cinder_char_to_string(char value);
void cinder_print_repr_char(char value);
void cinder_print_repr_string(const char *text);
double cinder_wall_time(void);
void cinder_sort(
    void *base,
    size_t count,
    size_t element_size,
    CinderCompareFn compare
);

#ifdef __cplusplus
}
#endif

#endif
