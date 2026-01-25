# Concierge Unit Tests

Disclaimer: These are all AI generated, and I have not spent much time reviewing them.

### Run all tests

```bash
# from the parent directory
python -m unittest discover -s tests -p "test_*.py" -v
```

### Run specific test

```bash
python -m unittest tests.test_utils.TestReplacePlaceholders.test_replace_hostname_only -v
```

### Coverage Report

```bash
pip install coverage
coverage run -m unittest discover -s tests -p "test_*.py"
coverage report -m
coverage html
```

### Continuous Integration - GitHub Actions workflow

```yaml
- name: Run unit tests
  run: |
    python -m unittest discover -s tests -p "test_*.py" -v
    
- name: Check coverage
  run: |
    pip install coverage
    coverage run -m unittest discover -s tests -p "test_*.py"
    coverage report --fail-under=80
```