#include "cinder_runtime.h"

#include <stdio.h>
#include <stdlib.h>

CINDER_NORETURN void cinder_panic(const char *message)
{
    const char *text = message != NULL ? message : "Cinder panic";
    (void)fprintf(stderr, "panic: %s\n", text);
    abort();
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
