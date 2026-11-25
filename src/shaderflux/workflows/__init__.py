"""End-to-end workflows: what a command does, without any command-line concerns.

Each workflow takes a plain request object and returns a plain outcome object. They print
nothing and know nothing about Typer, so they can be used as a Python API and tested
directly. The ``cli`` package only turns options into a request and an outcome into output.
"""
