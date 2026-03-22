"""
setup.py — compatibility shim for older pip versions.
The real configuration is in pyproject.toml.
"""
from setuptools import setup, find_packages

setup(
    name="contextcore",
    version="0.1.0",
    packages=find_packages(include=["cli*", "core*"]),
    entry_points={
        "console_scripts": [
            "contextcore=cli.main:main",
        ],
    },
    install_requires=[
        "typer",
        "rich",
        "questionary",
        "fastapi",
        "uvicorn",
        "requests",
        "annoy",
    ],
    python_requires=">=3.10",
)
