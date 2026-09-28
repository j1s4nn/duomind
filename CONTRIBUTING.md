# Contributing to DuoMind

Thank you for considering contributing to DuoMind!

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/duomind.git
   cd duomind
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install in development mode**:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Install pre-commit hooks** (optional but recommended):
   ```bash
   pip install pre-commit
   pre-commit install
   ```

## Running Tests

```bash
pytest
```

Run with coverage:
```bash
pytest --cov=duomind --cov-report=html
```

## Code Style

DuoMind uses **Ruff** for linting and formatting.

**Check code**:
```bash
ruff check src/ tests/
```

**Format code**:
```bash
ruff format src/ tests/
```

**Configuration**: See `pyproject.toml` for Ruff settings.

## Type Hints

- Use type hints for all public functions
- Use `from typing import ...` for complex types
- Run `mypy` (optional): `mypy src/duomind`

## Pull Request Process

1. **Create a branch** for your feature or fix:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** with clear, focused commits

3. **Add tests** for new functionality

4. **Update documentation** if needed (README, docstrings)

5. **Run tests and linting**:
   ```bash
   pytest
   ruff check src/ tests/
   ```

6. **Push and create a PR**:
   ```bash
   git push origin feature/your-feature-name
   ```

7. **PR description should include**:
   - What problem does this solve?
   - How does it work?
   - Any breaking changes?
   - Tests added/modified

## Commit Messages

Use clear, descriptive commit messages:

```
feat: add model switching command
fix: circuit breaker not resetting on success
docs: update README with new commands
test: add tests for Jev caching
```

Prefixes: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`

## Adding New Models

To add a model to `models.json`:

1. Verify the model exists on Hugging Face
2. Check license compatibility (MIT, Apache 2.0, etc.)
3. Verify GGUF file size and quantization
4. Test download and inference
5. Add entry to `src/duomind/models.json` with all required fields

## Adding New Decision Points

To add a decision to the registry:

1. Edit `src/duomind/decisions.py`
2. Add entry to `DECISION_REGISTRY` with:
   - Unique name
   - Stage (PRE/MID/POST)
   - Kind (noul/choice/score)
   - Instructions and criteria
   - Threshold and fallback
3. Add corresponding logic in `LocalFallbackClassifier.classify()`
4. Add tests in `tests/test_decisions.py`

## Documentation

- **Docstrings**: Use Google-style docstrings
- **README**: Keep non-technical and beginner-friendly
- **Code comments**: Only when WHY is non-obvious (avoid WHAT)

## Issue Reporting

**Bug reports** should include:
- DuoMind version
- Python version
- OS and GPU info
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs

**Feature requests** should include:
- Use case description
- Why existing features don't solve it
- Proposed solution (optional)

## Code of Conduct

- Be respectful and constructive
- Focus on the code, not the person
- Help others learn and grow
- No harassment or discrimination

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Questions?

- **Bugs**: Open an issue
- **Features**: Open an issue for discussion first
- **General help**: Check README and docs first

Thank you for contributing! 🎉
