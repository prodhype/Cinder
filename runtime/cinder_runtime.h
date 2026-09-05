#ifndef CINDER_RUNTIME_H
#define CINDER_RUNTIME_H

#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#if !defined(_WIN32)
#include <poll.h>
#include <sys/socket.h>
#include <sys/types.h>
#endif

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

typedef enum CinderNetErrorKind {
    CinderNetErrorKind_would_block = 0,
    CinderNetErrorKind_interrupted = 1,
    CinderNetErrorKind_address_in_use = 2,
    CinderNetErrorKind_connection_refused = 3,
    CinderNetErrorKind_connection_reset = 4,
    CinderNetErrorKind_timed_out = 5,
    CinderNetErrorKind_not_connected = 6,
    CinderNetErrorKind_invalid_input = 7,
    CinderNetErrorKind_unsupported = 8,
    CinderNetErrorKind_system = 9
} CinderNetErrorKind;

typedef struct CinderNetError {
    CinderNetErrorKind kind;
    int32_t code;
} CinderNetError;

typedef struct CinderSocket {
    int32_t handle;
    int32_t family;
    int32_t type;
    int32_t protocol;
} CinderSocket;

#if defined(_WIN32)
typedef struct CinderPollFd {
    int32_t fd;
    int16_t events;
    int16_t revents;
} CinderPollFd;
#else
/* Exact alias: generated code can pass CinderPollFd arrays to poll(2). */
typedef struct pollfd CinderPollFd;
#endif

#define CINDER_NET_INVALID_SOCKET INT32_C(-1)

#if defined(_WIN32)
#define CINDER_NET_AF_INET INT32_C(2)
#define CINDER_NET_AF_INET6 INT32_C(23)
#define CINDER_NET_SOCK_STREAM INT32_C(1)
#define CINDER_NET_POLL_IN INT16_C(0x0001)
#define CINDER_NET_POLL_OUT INT16_C(0x0004)
#define CINDER_NET_POLL_ERROR INT16_C(0x0008)
#define CINDER_NET_POLL_HANGUP INT16_C(0x0010)
#define CINDER_NET_POLL_INVALID INT16_C(0x0020)
#else
#define CINDER_NET_AF_INET ((int32_t)AF_INET)
#define CINDER_NET_AF_INET6 ((int32_t)AF_INET6)
#define CINDER_NET_SOCK_STREAM ((int32_t)SOCK_STREAM)
#define CINDER_NET_POLL_IN ((int16_t)POLLIN)
#define CINDER_NET_POLL_OUT ((int16_t)POLLOUT)
#define CINDER_NET_POLL_ERROR ((int16_t)POLLERR)
#define CINDER_NET_POLL_HANGUP ((int16_t)POLLHUP)
#define CINDER_NET_POLL_INVALID ((int16_t)POLLNVAL)
#endif

#if !defined(_WIN32) && defined(MSG_NOSIGNAL)
#define CINDER_NET_SEND_FLAGS MSG_NOSIGNAL
#else
#define CINDER_NET_SEND_FLAGS 0
#endif

#define CINDER_NET_SOCKET_INIT(family_value, type_value, protocol_value) \
    { \
        CINDER_NET_INVALID_SOCKET, \
        (int32_t)(family_value), \
        (int32_t)(type_value), \
        (int32_t)(protocol_value) \
    }
#define CINDER_NET_POLL_FD_INIT(socket_value, events_value) \
    { (socket_value).handle, (int16_t)(events_value), INT16_C(0) }

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
int32_t cinder_unicode_display_width(uint32_t scalar);
int32_t cinder_unicode_display_column(
    const char *source,
    size_t source_length,
    size_t start,
    size_t end,
    int32_t initial_column
);
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
void cinder_process_result_drop_raw(void *self);
CinderProcessResult cinder_process_run_argv(
    size_t argc,
    const char *const *argv
);
CinderNetError cinder_net_error_from_code(int32_t code);
CinderNetError cinder_net_last_error(void);
bool cinder_net_socket(
    int32_t family,
    int32_t type,
    int32_t protocol,
    CinderSocket *out,
    CinderNetError *error
);
bool cinder_net_bind(
    CinderSocket *socket,
    const char *host,
    int32_t port,
    CinderNetError *error
);
bool cinder_net_connect(
    CinderSocket *socket,
    const char *host,
    int32_t port,
    CinderNetError *error
);
bool cinder_net_listen(
    CinderSocket *socket,
    int32_t backlog,
    CinderNetError *error
);
bool cinder_net_accept(
    CinderSocket *socket,
    CinderSocket *out,
    CinderNetError *error
);
bool cinder_net_set_blocking(
    CinderSocket *socket,
    bool blocking,
    CinderNetError *error
);
bool cinder_net_close(CinderSocket *socket, CinderNetError *error);
void cinder_net_socket_drop(CinderSocket *socket);
void CinderSocket__drop(CinderSocket *self);
bool cinder_net_socket_is_open(const CinderSocket *socket);
int32_t cinder_net_socket_fileno(const CinderSocket *socket);
CinderPollFd cinder_net_poll_fd(
    const CinderSocket *socket,
    int16_t events
);
bool cinder_path_exists(const char *path);
bool cinder_path_is_file(const char *path);
bool cinder_path_is_dir(const char *path);
CinderString cinder_path_parent(const char *path);
CinderString cinder_path_name(const char *path);
CinderString cinder_path_stem(const char *path);
CinderString cinder_path_join(const char *left, const char *right);
CinderString cinder_path_with_suffix(const char *path, const char *suffix);
void cinder_path_create_dir(const char *path);
void cinder_path_create_dir_all(const char *path);
void cinder_path_remove_file(const char *path);
void cinder_path_rename(const char *source, const char *destination);
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
uint64_t cinder_f64_snapshot_bits(double value);
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
