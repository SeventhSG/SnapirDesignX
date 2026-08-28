# Snapir Design X

Leica iCON room surveys to solid bodies. Interior volumes, STEP out, no mesh
anywhere in the chain.

## Status

Working end to end on real survey data: parse, classify, fit planes, build the
shell, export STEP. 21 of 28 rooms in the reference job build with no human
input. Desktop frontend in progress.

## Try the parser

```bash
python tools/scan.py "C:/path/to/survey/folder"
```

Prints a per-room report: outline points, floor area, ceiling height, openings
found, and anything that needs an operator decision.

## Build the solids

```bash
python tools/build.py "C:/path/to/survey/folder" out
```

Writes one STEP body per room.

## Requirements

```bash
pip install -r requirements.txt
```

Python 3.11 or newer. The parser and geometry layer need nothing but the
standard library.

See [SPEC.md](SPEC.md) for the data format and the classification rules.
