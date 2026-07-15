# PACS offline demo

Run from the repository root:

```bash
bash demo/pacs_demo/run_demo.sh
```

The fixture exposes `demo-core` 2.0 and 1.0 while `demo-plugin` requires
`demo-core<2`. PACS first preflights the newer incompatible model, records the
real pip conflict, resolves again, installs the compatible model, runs
`pip check` and imports, writes a lock/report, and removes failed environments.
