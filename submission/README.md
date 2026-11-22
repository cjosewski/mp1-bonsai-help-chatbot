# Submission set

Apart from this README, the folder is empty on purpose: nothing has been generated
yet (milestone B0).

At milestone B10 it will hold the curated course submission, copied here by the
`export-submission` command with a hash manifest:

- baseline and corrected datasets (JSONL)
- the gate report
- the blind human labels
- the judge records
- per-item traces
- the five charts and their data tables
- the iteration log

Raw attempt logs and scratch runs stay outside Git. This folder is the only place
where run output is committed (open item O-5, decided November 21, 2026).

## License

The generated datasets (the baseline and corrected JSONL files) are licensed under
[Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/).
They will be derived in part from the Blender Manual (Blender Documentation Team,
CC BY-SA 4.0) and the Bonsai documentation (IfcOpenShell contributors,
GPL-3.0-or-later). Full source attribution arrives with the documentation
fixtures at milestone B1.

Verbatim text quoted from the Bonsai documentation or the Blender Manual, wherever
it appears in this folder (including inside the datasets, and cited sections inside
traces or judge records), keeps its source license: GPL-3.0-or-later for Bonsai, CC BY-SA 4.0 for
the Blender Manual. The license of the gate report, labels, charts, data tables and
iteration log is not yet decided by the owner (see `docs/DECISIONS.md`).
