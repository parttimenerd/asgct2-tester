#! python3
import enum
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Callable, Optional


class Version(enum.Enum):
    CUR = "cur"
    MOD = "mod"

    def __str__(self):
        return self.value


versions = [Version.MOD, Version.CUR]


def base(version: Version = None) -> Path:
    b = Path(__file__).parent
    if version:
        return b / str(version)
    return b


@dataclass
class Result:
    failure_rate: List[Optional[float]]
    error_files: List[Optional[Path]]

    def append(self, other: 'Result'):
        self.failure_rate.extend(other.failure_rate)
        self.error_files.extend(other.error_files)


@dataclass
class Conf:

    jdk_folders: Dict[Version, str]
    interval: float = "100us"


class Benchmark:

    def __init__(self, name: str, java_args: List[str]):
        self.name = name
        self.java_args = java_args

    def __str__(self):
        return self.name

    def run(self, conf: Conf) -> Dict[Version, Result]:
        return {v: self._run(conf, v) for v in versions}

    def _run(self, conf: Conf, version: Version) -> Result:
        env = self._env(conf.jdk_folders[version])
        folder = base() / "results" / self.name / str(version) / str(time.time())
        os.makedirs(folder, exist_ok=True)
        cmd = ["java", f"-agentpath:{base(version)}/async-profiler/build/libasyncProfiler.so=start,flat=100,interval={conf.interval},traces=1,event=cpu",
               "-XX:+UnlockDiagnosticVMOptions", "-XX:+DebugNonSafepoints", "-XX:ErrorFile=hs_err.log"] + self.java_args
        try:
            out = subprocess.check_output(cmd, env=env, cwd=folder, stderr=subprocess.PIPE).decode()
            return Result([Benchmark._parse_failure_rate(out)], [None])
        except subprocess.CalledProcessError as x:
            if "Digest validation failed" in x.stdout.decode() or "java.lang.reflect.InvocationTargetException" in x.stderr.decode():
                return Result([Benchmark._parse_failure_rate(x.stdout.decode())], [None])
            hs_err = folder / "hs_err.log"
            if hs_err.exists():
                print(f"hs_err file: {hs_err}")
                print("------")
                print("".join(hs_err.open().readlines()[:20]))
            print("Error: " + "".join(x.stderr.decode().split()[:20]))
            with (folder / "out.log").open("w") as f:
                f.write(x.stdout.decode())
            with (folder / "err.log").open("w") as f:
                f.write(x.stderr.decode())
            return Result([None], [hs_err])

    @staticmethod
    def _parse_failure_rate(output: str) -> Optional[float]:
        found_header = False
        rate = 0.0
        for line in output.split("\n"):
            if not found_header and "--- Execution profile ---" in line:
                found_header = True
                continue
            if found_header:
                if not line.strip():
                    break
                if line.startswith("unknown_Java") or line.startswith("not_walkable_Java"):
                    rate += float(line.split("%")[0].split("(")[1]) / 100.0
        return rate if found_header else None

    def _env(self, jdk_folder) -> Dict[str, str]:
        env = os.environ.copy()
        env["JAVA_HOME"] = jdk_folder
        env["PATH"] = f"{jdk_folder}/bin:{env['PATH']}"
        return env


BENCHMARKS: List[Benchmark] = [
    Benchmark(f"ap ThreadsTarget", ["-cp", str(base() / "cur" / "async-profiler" / "test"), "ThreadsTarget"])
] + [
    Benchmark(f"dacapo {x}", ["-jar", str(base() / "benchmarks" / "dacapo.jar"), x])
        for x in ["avrora", "fop", "h2", "jython", "lusearch", "lusearch-fix", "pmd", "sunflow", "tomcat", "xalan"]
] + [
    Benchmark(f"ren {x}", ["-jar", str(base() / "benchmarks" / "renaissance.jar"), x, "--run-seconds", "30"])
        for x in ['scrabble', 'page-rank', 'future-genetic', 'akka-uct', 'movie-lens', 'scala-doku', 'chi-square',
                  'fj-kmeans', 'rx-scrabble', 'finagle-http', 'reactors', 'dec-tree', 'scala-stm-bench7',
                  'naive-bayes', 'als', 'par-mnemonics', 'scala-kmeans',
                  'philosophers', 'log-regression', 'gauss-mix', 'mnemonics', 'dotty', 'finagle-chirper']
]


def pad_left(s: str, count: int) -> str:
    return " " * (count - len(s)) + s


class Results:

    def __init__(self, benchmarks: List[Benchmark]):
        self.benchmarks = benchmarks
        self.results: Dict[Benchmark, Dict[Version, Result]] = {}

    def add(self, benchmark: Benchmark, result: Dict[Version, Result]):
        if benchmark not in self.results:
            self.results[benchmark] = {v: Result([], []) for v in versions}
        for v in versions:
            self.results[benchmark][v].append(result[v])

    def _table(self, column_title: str, func: Callable[[Result], float]) -> str:
        lines: List[str] = []
        lines.append("".join([" " * 30, " " * 5 + "count"] +
                             [pad_left(f"{v} {column_title}", 25) for v in versions] + ["best"]))

        best_versions: List[Optional[Version]] = []
        for benchmark in self.benchmarks:
            if benchmark not in self.results:
                continue
            res = self.results[benchmark]
            min_rate = min(func(res[v]) for v in versions)
            best_version = None if min_rate == 0 else [v for v in versions if func(res[v]) == min_rate][0]
            lines.append("".join([pad_left(benchmark.name, 25), pad_left(str(len(res[versions[0]].failure_rate)), 10)] +
                         [pad_left(f"{func(res[v]):10.5f}", 20) for v in versions] + [pad_left(best_version.value if best_version else "", 10)]))
            best_versions.append(best_version)
        lines.append("")
        for v in versions:
            lines.append(f"{v}: {best_versions.count(v)}")

        return "\n".join(lines)

    def failure_rate_table(self) -> str:
        return self._table("fdrop rate", lambda f: math.fsum(r for r in f.failure_rate if r is not None) / len(f.failure_rate))

    def error_rate_table(self) -> str:
        return self._table("error rate", lambda f: len([1 for e in f.error_files if e]) / float(len(f.failure_rate)))


def run(cur_jdk_images: str, mod_jdk_images: str, iterations: int):
    subprocess.check_call([f"{cur_jdk_images}/bin/java", "-version"])
    subprocess.check_call([f"{mod_jdk_images}/bin/java", "-version"])
    res = Results(BENCHMARKS)
    conf = Conf({Version.CUR: cur_jdk_images, Version.MOD: mod_jdk_images})
    for i in range(iterations):
        for benchmark in BENCHMARKS:
            res.add(benchmark, benchmark.run(conf))
            print(res.error_rate_table())
            print(res.failure_rate_table())


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    run(str(Path(sys.argv[1]).absolute()), str(Path(sys.argv[2]).absolute()), int(sys.argv[3]))
