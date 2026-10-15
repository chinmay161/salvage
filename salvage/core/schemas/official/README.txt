Put the organizers' schema files here.

Expected names (change them in SCHEMA_FILES in salvage/core/validate.py):
  output.schema.json   schema for each per-file output
  report.schema.json   schema for report.json

When a file is present it replaces the matching provisional schema in
salvage/core/schemas/. Check it with:  python -m salvage.core.validate
A schema keyword the validator does not support is reported at once.
