"""Run the real CLI with another decoder package (tests only).

    python -m tests.fixtures.cli_with_package PACKAGE [CLI arguments...]

Wraps ``salvagekit.core.pipeline.run`` so the CLI uses PACKAGE instead of
salvagekit.formats; everything else is the unchanged ``salvagekit.cli.main``.
"""

import functools
import sys

from salvagekit import cli
from salvagekit.core import pipeline


def main() -> None:
    package = sys.argv[1]
    pipeline.run = functools.partial(pipeline.run, decoder_package=package)
    cli.main(sys.argv[2:])
    sys.stdout.flush()
    sys.stderr.flush()


if __name__ == "__main__":
    main()
