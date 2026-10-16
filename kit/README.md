# PS 02 – Salvage: participant kit

```
samples/            30 legacy-format sample files + HINTS.md + a subfolder
expected_outputs/   reference JSON for 7 of the samples (to calibrate your output). The rest are unlabeled on purpose.
OUTPUT-CONTRACT.md  the output schema: file naming, status values, damage vocabulary, record fields per format
```

## Rules recap
* `./salvage <input_dir> <output_dir>` – offline, no network, **no LLM/AI calls at runtime**, single build command + Dockerfile, exit code 0 always.
* One JSON per input (`<input name>.json`) + `report.json`, following OUTPUT-CONTRACT.md. Unknown or hostile files must not crash the tool.
* Deliver FORMAT-SPEC.md, FIELD-LOG.md (include failed hypotheses), README with the build command, your own tests, Dockerfile.