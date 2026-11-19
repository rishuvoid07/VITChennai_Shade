Historical: superseded by RESULTS_STAGE4.md; parameters differ

# Stage 1 – File-by-File Explanation

## src/main.cpp

The main (and only) C++ source file.  It reads an IMU CSV file line by line
and writes a trajectory file in TUM format.  It does three things: (1) parses
comma-separated IMU data, (2) estimates orientation by integrating the gyro
using quaternion math, and (3) estimates position by rotating the
accelerometer into the world frame, subtracting gravity, and
double-integrating.  This is called "strapdown integration" and it drifts
badly — that's expected; it's our baseline.

## CMakeLists.txt

Tells CMake how to build the project: use C++17, compile `src/main.cpp`
into an executable called `pathfinder`, and enable compiler warnings.
Three lines of real content — the simplest possible CMake setup.

## build.bat

A single-command fallback if you don't want to use CMake.  It calls g++
directly with C++17, optimization, and warnings.

## tools/generate_synthetic.py

Creates a tiny fake IMU file (200 samples, 1 second, sensor sitting still)
and a matching ground-truth file.  This is clearly labeled as OUR synthetic
data — not the official EuRoC dataset.  Its only purpose is to test that
the parser, writer, and validators work correctly before we have real data.

## tools/validate_output.py

Reads the output trajectory and checks it against the spec: exactly 8 columns
per row, monotonically increasing timestamps, unit-norm quaternions, no NaN
or infinity, correct row count, and that the timestamps match the integer-to-
decimal conversion from the input.  If any check fails, it prints what went
wrong and exits with code 1.

## tools/eval.py

Takes our estimated trajectory and a EuRoC ground-truth file, converts the
ground truth to TUM format, then calls the `evo` tool to compute ATE (absolute
trajectory error) and RPE (relative pose error) with and without alignment.
This tells us how far off we are from the truth, in meters.

## tools/measure.py

Runs the pathfinder binary and measures (1) how much RAM it used (peak working
set via psutil), (2) how long it took, and (3) how many milliseconds of compute
per 1 second of IMU data.  The budget is ≤ 8 MB RAM and ≤ 20 ms per second of
data.

## docs/ASSUMPTIONS.md

Lists every unknown or ambiguous point in the problem statement, what we
assumed, and how the code can be changed if the assumption turns out wrong.

## PROGRESS.md

A running log with three sections: Done, Pending, and Failed/Blocked.
Updated after every major step.

## .gitignore

Tells git to ignore build outputs, the data/ directory (EuRoC datasets are
large), Python caches, and editor files.

## README.md

Top-level instructions: what the project is, how to build, run, validate,
evaluate, and measure.  Also shows the directory layout and constraints.
