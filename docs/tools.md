---
title: Tools
---

# Tools

Atomsh carries two sets of tools in one schema. The model does not need to know
which side a tool lives on.

## Code tools

Run locally, in your workspace.

| Tool | What it does |
|------|--------------|
| `read_file` | Read a file with line numbers, optionally a range |
| `write_file` | Create a file or overwrite one |
| `edit_file` | Replace exact text. The match must be unique unless `replace_all` is set |
| `list_dir` | List a directory |
| `glob_files` | Find files by pattern, newest first |
| `grep_files` | Search file contents by regular expression |
| `bash` | Run a shell command in the workspace |

`edit_file` refuses an ambiguous match rather than guessing, and refuses text
it cannot find. Both refusals are returned to the model as readable errors, so
it re-reads the file and retries rather than corrupting it.

Directories like `.git`, `node_modules`, `__pycache__` and `.venv` are skipped
by the search tools.

## Materials tools

Loaded by default, from the AtomGPT tool server, authenticated with the same
credential. Six dispatchers, each reaching a family of AtomGPT apps.

| Tool | Covers |
|------|--------|
| `explore` | JARVIS-DFT queries, materials search, literature |
| `build` | Supercells, surfaces, vacancies, substitutions, interfaces |
| `predict` | ALIGNN properties, force-field relaxation, MD, phonons, transport |
| `characterize` | XRD generation, analysis and refinement, Raman, spectra |
| `apply` | Batteries, superconductors, solar, catalysis, MOFs |
| `validate` | Reference and hallucination checks |

Each is self-describing. Called with no arguments it lists the apps in its
category; with `app="/path"` it reports that app's parameters; with arguments
it runs the app.

```text
› bandgap of silicon JVASP-1002 from JARVIS-DFT
  · explore(app=/jarvis_dft/query, params={"jid": "JVASP-1002"})
OptB88vdW 0.731 eV, mBJ 1.277 eV, HSE 1.22 eV
```

`--no-materials` leaves them out. Worth doing for pure coding work, where a
narrower tool surface is easier for the model to aim.

!!! note "Long-running calculations"
    A relaxation or band structure can take a minute or more. Atomsh waits, but
    very large cells may exceed the server's request timeout. Start small.

## Caching

The materials tool list is cached in `~/.local/share/atomsh/` and refreshed
daily, and the connection to the tool server is opened on first use, so
carrying these tools costs nothing at startup. Delete the cache file to force a
refresh after new apps are added.
