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
