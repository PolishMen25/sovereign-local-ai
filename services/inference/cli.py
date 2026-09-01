"""Path-free command-line parsing shared by public inference tools."""

from __future__ import annotations

import argparse


class CliArgumentError(ValueError):
    """A generic parser refusal that never embeds an argument value."""


class PathFreeArgumentParser(argparse.ArgumentParser):
    """Keep ``--help`` standard while replacing path-bearing parse errors."""

    def error(self, message: str) -> None:
        del message
        raise CliArgumentError("invalid command line")
