# Contributing to Gmail Bookmark Service

Thank you for your interest in contributing to the Gmail Bookmark Service! This document provides guidelines for contributors.

## Getting Started

### Prerequisites

- Python 3.9+
- Git
- Gmail API access (for testing)
- GCP Project (for testing Pub/Sub)

### Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/your-username/gmail-bookmark-service.git
   cd gmail-bookmark-service
   ```

3. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

5. Copy environment configuration:
   ```bash
   cp .env.example .env
   # Edit .env with your test configuration
   ```

## Code Style

We use the following tools to maintain code quality:

- **Black**: Code formatting
- **Ruff**: Linting and code analysis
- **MyPy**: Type checking

### Running the Tools

```bash
# Format code
black src/ tests/

# Lint code
ruff check src/ tests/

# Type checking
mypy src/
```

### Pre-commit Hooks

We recommend using pre-commit hooks:

```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Run hooks manually
pre-commit run --all-files
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=gmail_bookmark_service --cov-report=html

# Run specific test file
pytest tests/test_auth.py

# Run with verbose output
pytest -v
```

### Writing Tests

- Write tests for all new functionality
- Use descriptive test names
- Test both success and failure cases
- Mock external dependencies (Gmail API, Pub/Sub)

### Test Structure

```
tests/
├── conftest.py          # Shared test fixtures
├── test_auth.py         # Authentication tests
├── test_database.py     # Database tests
├── test_processing.py   # Message processing tests
├── test_api.py          # API endpoint tests
└── test_utils.py        # Utility function tests
```

## Development Workflow

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**:
   - Write code following the style guidelines
   - Add tests for new functionality
   - Update documentation as needed

3. **Run tests and linting**:
   ```bash
   pytest
   black src/ tests/
   ruff check src/ tests/
   mypy src/
   ```

4. **Commit your changes**:
   ```bash
   git add .
   git commit -m "feat: add new feature description"
   ```

   Use conventional commit messages:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `docs:` for documentation changes
   - `style:` for code style changes
   - `refactor:` for refactoring
   - `test:` for test changes
   - `chore:` for maintenance tasks

5. **Push and create a pull request**:
   ```bash
   git push origin feature/your-feature-name
   ```

## Pull Request Process

### PR Requirements

- All tests must pass
- Code must be formatted with Black
- No linting errors from Ruff
- Type checking must pass with MyPy
- Documentation updated if needed
- PR description should clearly describe the changes

### PR Template

```markdown
## Description
Brief description of the changes made.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] All tests pass
- [ ] New tests added for new functionality
- [ ] Manual testing performed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No breaking changes (or clearly documented)
```

## Code Review Process

1. All PRs require at least one approval
2. Address all review comments
3. Keep PRs focused and reasonably sized
4. Update PR description based on review feedback

## Reporting Issues

### Bug Reports

Use the issue tracker with the following template:

```markdown
## Bug Description
Clear and concise description of the bug.

## Steps to Reproduce
1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

## Expected Behavior
What you expected to happen.

## Actual Behavior
What actually happened.

## Environment
- OS: [e.g. Ubuntu 20.04]
- Python version: [e.g. 3.9.0]
- Service version: [e.g. 1.0.0]

## Additional Context
Any other context about the problem.
```

### Feature Requests

```markdown
## Feature Description
Clear and concise description of the feature.

## Use Case
Why would this feature be useful?

## Proposed Solution
How you envision the feature working.

## Alternatives Considered
Other approaches you've thought about.
```

## Development Guidelines

### Code Organization

- Follow the existing package structure
- Use type hints for all functions and methods
- Keep functions small and focused
- Use descriptive variable and function names

### Documentation

- Update README.md for user-facing changes
- Update API documentation for endpoint changes
- Add docstrings for all public functions
- Include examples in documentation

### Security

- Never commit secrets or credentials
- Follow secure coding practices
- Validate all inputs
- Handle errors gracefully

### Performance

- Use async/await for I/O operations
- Consider memory usage with large attachments
- Optimize database queries
- Profile performance-critical code

## Release Process

Releases are handled by maintainers using semantic versioning:

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create a git tag
4. Build and publish to PyPI (if applicable)

## Getting Help

- Check existing issues and documentation
- Ask questions in GitHub Discussions
- Reach out to maintainers for guidance

Thank you for contributing!