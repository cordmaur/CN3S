# Fix editable install

1. Inspect the packaging metadata and devcontainer install command.
2. Enable Hatchling's explicitly required direct-reference metadata setting.
3. Validate editable installation with the repository's package manager command.
4. Review the diff to confirm the change is limited to packaging configuration.

Method-call examples:

- `pip install -e . --ignore-installed --break-system-packages`
- `git diff -- pyproject.toml`
