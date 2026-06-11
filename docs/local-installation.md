# Local Installation and Upgrade

MVP v1 supports a trusted, single-user Linux or WSL2 installation from a local
source checkout or wheel. Python 3.11 or newer and `prlimit` are required. Node
and Docker/Podman are optional and only needed by providers that declare those
runtimes.

Development install:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pip check
```

Build and install a local wheel:

```bash
.venv/bin/pip wheel . --no-deps --no-build-isolation --wheel-dir dist
python3 -m pip install dist/canto_broker-*.whl
```

Upgrade from a newer trusted checkout or wheel with `pip install --upgrade`.
The upgrade preserves `~/.canto`, including SQLite state, installed capability
packages, and the encrypted credential vault. Back up that directory before a
release upgrade. CP-5003 documents migration from legacy Redis/filesystem
state.

Verify the complete local write workflow without network access:

```bash
./scripts/quickstart-mvp-v1.sh
```

The script uses an isolated temporary home, checks health, performs a managed
JSON dry run, approves its live promotion, verifies the write, approves
rollback, and verifies restoration. It does not alter the normal user registry.
