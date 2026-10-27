---
name: m3-reader-release
description: Build, verify, and synchronize M3 Reader Windows and Ubuntu executables and minimal install packs after a versioned source change. Use for release packaging, cross-platform rebuilds, or syncing Ubuntu CI artifacts into installpacks.
---

# M3 Reader release

Use the repository's [release script](../../../scripts/release.py) for repeatable package work. Run it from the repository root with Python 3.10+.

1. Confirm the requested code change, version in prts_tool/__init__.py and pyproject.toml, changelog, and relevant tests. Keep resources/ and workspace/ content out of Git and install packs.
2. On Windows, run python scripts/release.py build to build both executables, the Windows setup, and the Ubuntu source archive. On Ubuntu, the same command builds its executables, source/portable archives, and .deb. Use build --package-only only after binaries for the current version have already been built.
3. Run python scripts/release.py verify. Review the Git diff and commit/push source changes when the user has authorized remote maintenance. The script itself never commits or pushes.
4. Obtain the successful GitHub Actions run ID for the commit. Run python scripts/release.py ci-status --run-id ID; both windows and ubuntu must report success. Download that run's m3-reader-ubuntu artifact ZIP using an authenticated browser or GitHub CLI.
5. Run python scripts/release.py sync-ubuntu --run-id ID --artifact-zip PATH. It checks the GitHub artifact digest and each inner SHA-256, updates installpacks/debian/, bin/ubuntu/, and the combined checksum file. Then run python scripts/release.py verify --complete.
6. Update installpacks/README.md and docs/KNOWN_INFO.md with the verified result. Commit and push those records when remote maintenance is in scope. Report package paths and the CI run.

Stop on a failed CI job, missing ZIP, version mismatch, checksum error, or unexpected ZIP member. Do not build Linux packages from stale bin/ubuntu files on Windows. Do not copy collected resources or local documents into release archives.
