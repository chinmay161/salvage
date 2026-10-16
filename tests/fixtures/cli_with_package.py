"""Run the real CLI with another decoder package (tests only).

    python -m tests.fixtures.cli_with_package PACKAGE [CLI arguments...]

Wraps ``salvage.core.pipeline.run`` so the CLI uses PACKAGE instead of
salvage.formats; everything else is the unchanged ``salvage.cli.main``.
"""

import functools
import sys

from salvage import cli
from salvage.core import pipeline


def main() -> None:
    package = sys.argv[1]
    pipeline.run = functools.partial(pipeline.run, decoder_package=package)
    cli.main(sys.argv[2:])
    sys.stdout.flush()
    sys.stderr.flush()


if __name__ == "__main__":
    main()
