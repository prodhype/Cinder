package main

/*
#cgo CFLAGS: -I${SRCDIR}/../../../cinder/runtime -I${SRCDIR}/../generated
#cgo LDFLAGS: ${SRCDIR}/../build/lib.o ${SRCDIR}/../build/cinder_runtime.o
#include "cinder_gen/lib.cinder.h"
*/
import "C"
import "fmt"

func main() {
	fmt.Println(int32(C.cinder_eval_expr(20, 22, 1)))
	fmt.Println(int32(C.cinder_eval_div(10, 6, 2)))
	fmt.Println(int32(C.cinder_eval_div(1, 0, 0)))
}
