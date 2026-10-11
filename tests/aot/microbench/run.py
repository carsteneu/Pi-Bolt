#!/usr/bin/env python3
"""AOT microbenchmarks: build each program with the Pi-Bolt ahead-of-time engine and
measure its CPU time, against a recorded baseline.

Usage:
    tests/aot/microbench/run.py [--record] [--bench NAME]... [--runs N]

Baselines are written to --baseline (default tests/aot/microbench/baseline.json) and
keyed by the engine commit and the runtime's hash. A baseline from another engine is
never compared silently: the run stops and says so, unless --allow-other-engine is
given. --record stores this run as the baseline.

Each program is built into an ahead-of-time image and timed by the CPU its own process
tree uses, with the checked output compared between runs and against the baseline: a
build that stops using compiled code, or that changes what the program prints, cannot
pass. Baselines for more than one engine are kept as separate files.
"""

import argparse
import hashlib
import json
import os
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PI_BOLT = HERE.parent.parent.parent  # the checkout this file is in
HOME = Path(os.path.expanduser("~"))

# The toolchain the runtime and its build were made with (scripts/build-runtime.sh).
ICU = HOME / "projects/pi-bolt/.toolchain/icu70/usr/lib/x86_64-linux-gnu"
RUNTIME = HOME / "projects/pi-bolt/.work/runtime/bun"
WEBKIT = HOME / "projects/pi-bolt/.work/webkit"
RUN_TIMEOUT = 600  # seconds; a benchmark that hangs must not wedge the harness

# The build of an ahead-of-time image, as scripts/build-pi.sh sets it.
AOT_BUILD_ENV = {
    "BUN_JSC_useJIT": "0",
    "BUN_AOT": "1",
    "BUN_AOT_JIT": "0",
    "BUN_STATIC_HEAP": "1",
    "BUN_JSC_omitBytecodeFromStaticHeap": "1",
    "BUN_JSC_useAOTLoopSplitting": "1",
    "BUN_JSC_aotLoopSplittingPolicy": "5",
    "BUN_JSC_useImmutableIntrinsics": "1",
}

BENCHES = ["prop-mono", "prop-poly", "prop-index", "call-heavy", "typed-field"]


def env_with_libraries(extra=None):
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = str(ICU) + (
        ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
    )
    if extra:
        env.update(extra)
    return env


def run_and_measure(argv, env, cwd):
    """Run argv, return (exit code, stdout, stderr, user+sys CPU seconds)."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    proc = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True,
                          timeout=RUN_TIMEOUT)
    elapsed = time.monotonic() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    return proc.returncode, proc.stdout, proc.stderr, cpu


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def engine_of(runtime):
    """What a baseline belongs to. The commit alone is not enough: a runtime built
    from an uncommitted tree would otherwise claim to be the commit it sits on."""
    try:
        head = subprocess.run(["git", "-C", str(WEBKIT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True, timeout=60).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(WEBKIT), "status", "--porcelain"],
                               capture_output=True, text=True, check=True, timeout=60).stdout.strip()
    except Exception:
        head, dirty = "unknown", ""
    return {"webkit": head + ("-uncommitted" if dirty else ""), "runtime_sha256": sha256_of(runtime)}


class Bench:
    def __init__(self, name, work, runtime):
        self.name = name
        self.source = HERE / f"{name}.mjs"
        self.work = work
        self.runtime = runtime
        self.order = work / f"{name}.order"
        self.bytecode_binary = work / f"{name}-bytecode"
        self.aot_binary = work / f"{name}-aot"

    def train_order(self):
        """The AOT compiler lays code out by the order functions are first called in,
        which a plain bytecode build run once records."""
        code, out, err, _ = run_and_measure(
            [str(self.runtime), "build", "--compile", "--bytecode", "--format=esm",
             "--target=bun-linux-x64", str(self.source), "--outfile", str(self.bytecode_binary)],
            env_with_libraries(), self.work,
        )
        if code != 0:
            return f"bytecode build failed ({code}): {(out + err)[-400:]}"
        code, out, err, _ = run_and_measure(
            [str(self.bytecode_binary)], env_with_libraries({"BUN_BYTECODE_ORDER_OUT": str(self.order)}), self.work,
        )
        if code != 0:
            return f"order training run failed ({code}): {(out + err)[-400:]}"
        if not self.order.exists():
            return "no order file was written"
        return None

    def build_aot(self, extra=None):
        env = dict(AOT_BUILD_ENV)
        if extra:
            env.update(extra)
        code, out, err, _ = run_and_measure(
            [str(self.runtime), "build", "--compile", "--bytecode", "--format=esm",
             "--target=bun-linux-x64", f"--bytecode-order={self.order}", str(self.source),
             "--outfile", str(self.aot_binary)],
            env_with_libraries(env), self.work,
        )
        if code != 0:
            return f"AOT build failed ({code}): {(out + err)[-800:]}"
        if "bigger than maximumAOTCandidateBytecodeSize" in out + err:
            return f"AOT build declined a function: {(out + err)[-800:]}"
        return None

    def run_aot(self, extra=None, verbose=False):
        env = env_with_libraries(extra)
        if verbose:
            env["BUN_STATIC_HEAP_VERBOSE"] = "1"
        return run_and_measure([str(self.aot_binary)], env, self.work)

    def measure(self, runs):
        # One run with the runtime's own report on, to see that it took the image at
        # all. It is not timed: the report goes to its stderr, but it is a different
        # run from the measured ones.
        code, out, err, _ = self.run_aot(verbose=True)
        if code != 0:
            return None, f"run failed ({code}): {(out + err)[-400:]}"
        if "image registered: true" not in err:
            return None, "the runtime did not register the image: this program ran without compiled code"
        user_cpus = []
        last = None
        for _ in range(runs):
            code, out, err, cpu = self.run_aot()
            if code != 0:
                return None, f"run failed ({code}): {(out + err)[-400:]}"
            line = out.strip().splitlines()[-1].strip() if out.strip() else ""
            if last is None:
                last = line
            elif line != last:
                return None, f"the output changed between runs: {last!r} then {line!r}"
            user_cpus.append(cpu)
        return {"output": last, "min_cpu": min(user_cpus), "median_cpu": statistics.median(user_cpus), "runs": user_cpus}, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true", help="store this run as the baseline")
    parser.add_argument("--bench", action="append", default=[], help="only this benchmark (repeatable)")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--runtime", default=str(RUNTIME))
    parser.add_argument("--baseline", default=str(HERE / "baseline.json"))
    parser.add_argument("--typed-fields", action="store_true",
                        help="also build with useAOTTypedFields (needs a type table)")
    parser.add_argument("--allow-other-engine", action="store_true",
                        help="compare against a baseline recorded for another engine (says so in the output)")
    args = parser.parse_args()

    names = args.bench or BENCHES
    runtime = Path(args.runtime)
    if not runtime.exists():
        sys.exit(f"no runtime at {runtime}: run scripts/build-runtime.sh")
    work = Path(os.environ.get("PIBOLT_WORK", PI_BOLT / ".work")) / "microbench"
    work.mkdir(parents=True, exist_ok=True)

    engine = engine_of(runtime)
    print(f"engine: webkit {engine['webkit'][:12]}  runtime {engine['runtime_sha256'][:16]}")
    print(f"runtime: {runtime} ({subprocess.run([str(runtime), '--version'], env=env_with_libraries(), capture_output=True, text=True).stdout.strip() if os.access(runtime, os.X_OK) else '?'})")

    baseline = {}
    baseline_path = Path(args.baseline)
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text())

    # A baseline is only about one engine. Comparing across engines would attribute
    # another build's code layout to this change.
    if baseline and baseline.get("engine") != engine and not (args.record or args.allow_other_engine):
        sys.exit(f"{baseline_path} is a baseline for {baseline.get('engine')}, not for the engine at "
                 f"{engine['webkit'][:12]}/{engine['runtime_sha256'][:16]}: pass --record to make a new one, "
                 f"or --allow-other-engine to compare anyway")
    if baseline and baseline.get("engine") != engine:
        print(f"note: comparing against a baseline for {baseline.get('engine', {}).get('webkit', 'unknown')[:12]}")

    results = {}
    failed = False
    for name in names:
        bench = Bench(name, work, runtime)
        extra = {"BUN_JSC_useAOTTypedFields": "1", "BUN_JSC_useAOTFunctionSplitting": "1"} if args.typed_fields else None
        print(f"\n== {name} ==")
        error = bench.train_order()
        if error:
            print(f"  FAIL {error}")
            failed = True
            continue
        error = bench.build_aot(extra)
        if error:
            print(f"  FAIL {error}")
            failed = True
            continue
        measured, error = bench.measure(args.runs)
        if error:
            print(f"  FAIL {error}")
            failed = True
            continue
        print(f"  output {measured['output']}  min {measured['min_cpu']:.3f}s  median {measured['median_cpu']:.3f}s"
              f"  runs {[round(c, 3) for c in measured['runs']]}")
        results[name] = measured

        previous = baseline.get("results", {}).get(name)
        if previous and not args.record:
            delta = measured["min_cpu"] - previous["min_cpu"]
            percent = 100 * delta / previous["min_cpu"] if previous["min_cpu"] else 0
            same_output = previous["output"] == measured["output"]
            print(f"  vs baseline: {delta:+.3f}s ({percent:+.1f}%)  [output {'same' if same_output else 'CHANGED'}]")
            if not same_output:
                print(f"  FAIL the output is not what the baseline's was: {previous['output']!r}")
                failed = True

    if args.record:
        merged = dict(baseline.get("results", {}))
        merged.update(results)
        baseline_path.write_text(json.dumps(
            {"engine": engine, "results": merged}, indent=2, sort_keys=True) + "\n")
        print(f"\nbaseline written: {baseline_path} ({len(merged)} benchmarks)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
