"""``python -m trellis_tui`` — same entry as the ``trellis`` console script."""

import sys

from .app import main

sys.exit(main())
