param(
    [ValidateSet("pypi", "testpypi")]
    [string]$Repository = "pypi",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

function Assert-Command($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $name"
    }
}

Assert-Command python

if (-not $SkipBuild) {
    python -m build --no-isolation
}

python -m twine check dist/*

if ($Repository -eq "testpypi") {
    python -m twine upload --repository testpypi dist/*
} else {
    python -m twine upload dist/*
}
