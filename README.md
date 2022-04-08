AsyncGetCallTrace2 Tester
=========================

A tool to compare the current JDK (with the current async-profiler)
with the modified JDK (with the modified async-profiler using
the new AsyncGetCallTrace call) regarding

- errors that result in an `hs_err` file
- percentage of valid frames

by profiling a set of open source benchmarks.

Use the [jdk-profiling-tester](https://github.com/parttimenerd/jdk-profiling-tester)
for just testing the stability (absence of `hs_err` files).

Usage
-----
Compile the JDKs (be sure to use `images`) and
run `./setup` to build the async-profiler versions and
the benchmarks:

```sh
for x in "cur" "mod"; do
  (cd $x/jdk; bash configure > /dev/null && make images > /dev/null)
  echo $x/jdk/**/*release/images/jdk
done
```

Run the script:

```sh
./main.py CURRENT_JDK_FOLDER MODIFIED_JDK_FOLDER TIMES
```
e.g. `./main.py cur/jdk/build/macosx-aarch64-server-release/images/jdk mod/jdk/build/macosx-aarch64-server-release/images/jdk 1`

License
-------
GPLv3