"""Show the exact versions of MISTER PLIS's own packages as installed here (what tool sources may not change):

    .venv/bin/python scripts/make_constraints.py [out.txt]

The server computes these itself whenever it installs a tool source's requirements (mister_plis/pins.py); this
script only prints or saves them, e.g. to compare two machines.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mister_plis.pins import installed_pins, write_constraints  # noqa: E402

if len(sys.argv) > 1:
    print(write_constraints(Path(sys.argv[1])))
else:
    for name, version in sorted(installed_pins().items()):
        print(f"{name}=={version}")
