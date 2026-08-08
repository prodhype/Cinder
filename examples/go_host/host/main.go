package main

/*
#cgo CFLAGS: -I${SRCDIR}/../../../cinder/runtime -I${SRCDIR}/../generated
#cgo LDFLAGS: ${SRCDIR}/../build/lib.o ${SRCDIR}/../build/cinder_runtime.o
#include <stdio.h>
#include "cinder_gen/lib.cinder.h"
*/
import "C"
import (
	"fmt"
	"math"
	"os"
	"time"
)

const iterations int32 = 1_000_000_000

func goLeibniz(n int32) float64 {
	// Same series as cinder_leibniz / examples/leibniz_pi.ci.
	pi := 1.0
	rounds := n + 2
	for i := int32(2); i < rounds; i++ {
		x := -1.0 + 2.0*float64(i&1)
		pi += x / float64(2*i-1)
	}
	return pi * 4.0
}

func timeCall(label string, fn func() float64) (float64, time.Duration) {
	started := time.Now()
	value := fn()
	elapsed := time.Since(started)
	fmt.Printf("%s: π ≈ %.12f  (%.1f ms)\n", label, value, float64(elapsed.Seconds())*1000.0)
	return value, elapsed
}

func main() {
	fmt.Println(int32(C.cinder_eval_expr(20, 22, 1)))
	fmt.Println(int32(C.cinder_eval_div(10, 6, 2)))
	fmt.Println(int32(C.cinder_eval_div(1, 0, 0)))
	// Cinder's destructor Trace(...) lines write to libc stdout. When this
	// binary's stdout is redirected, that stream is fully buffered and Go
	// exits without flushing it, so the drop messages would be lost.
	C.fflush(C.stdout)

	fmt.Printf("Leibniz π with %d iterations\n", iterations)
	goValue, goElapsed := timeCall("go", func() float64 {
		return goLeibniz(iterations)
	})
	ciValue, ciElapsed := timeCall("cinder", func() float64 {
		return float64(C.cinder_leibniz(C.int32_t(iterations)))
	})
	if math.Abs(goValue-ciValue) > 1e-9 {
		fmt.Fprintf(os.Stderr, "error: results diverged: go=%v cinder=%v\n", goValue, ciValue)
		os.Exit(1)
	}
	if ciElapsed <= 0 {
		fmt.Fprintln(os.Stderr, "error: cinder timing was non-positive")
		os.Exit(1)
	}
	speedup := float64(goElapsed) / float64(ciElapsed)
	fmt.Printf("speedup: %.1fx (go / cinder)\n", speedup)
}
