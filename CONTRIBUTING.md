# Contributing to Graph-Based Fraud Intelligence

Thank you for your interest in contributing to **Graph-Based Fraud Intelligence**! This guide outlines how to get started, our development workflow, and the standards we maintain.

---

## Code of Conduct

We are committed to providing a friendly, safe, and welcoming environment for everyone, regardless of background or experience level. Please be respectful and constructive in all issues, pull requests, and discussions.

---

## Getting Started

### 1. Prerequisites
- **Python**: Version 3.10+ (tested on Python 3.13)
- **Git**: Installed and configured on your system
- **Virtual Environment**: `venv` or `conda`

### 2. Fork and Clone
```bash
git clone https://github.com/RUCHITHA-M-DEV/Graph-Based-Fraud-Intelligence.git
cd Graph-Based-Fraud-Intelligence
```

### 3. Setup Virtual Environment
On Windows (PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

On Linux / macOS:
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Development Workflow

### 1. Branch Naming Convention
Create a branch for your feature or bug fix:
- `feature/<feature-name>` (e.g. `feature/gnn-anomaly-detection`)
- `fix/<bug-description>` (e.g. `fix/sqlite-concurrent-writes`)
- `docs/<documentation-topic>` (e.g. `docs/api-guide-update`)

```bash
git checkout -b feature/your-feature-name
```

### 2. Running Tests
Ensure all existing tests pass before writing new code:
```bash
python -m pytest tests/ -v
```

Run test suite with code coverage:
```bash
python -m pytest --cov=src --cov-report=term-missing
```

### 3. Pipeline Execution
To regenerate synthetic datasets and execute detection pipelines locally:
```bash
# 1. Generate synthetic dataset
python -m src.generator --accounts 150 --transactions 2500

# 2. Run fraud detection and ML pipeline
python -m src.detector

# 3. Launch Flask interactive dashboard
python -m src.app
```

---

## Code Quality Standards

1. **Clean Code & Typing**: Use clear variable names and Python type annotations where practical.
2. **Deterministic ML**: Maintain reproducible random seeds (`RANDOM_SEED=42`) across models.
3. **No Leakage**: Never use ground-truth fraud labels as input features for preprocessing, graph metrics, or feature engineering.
4. **Graph Complexity**: For graph cycle analysis, always use bounded depth traversals to prevent combinatorial blowups on dense topologies.
5. **Security**: Never hardcode credentials, API tokens, or secrets. Ensure `.env` is ignored by git.
6. **Documentation**: Document public functions with docstrings explaining parameters, returns, and algorithmic complexity where applicable.

---

## Submitting Pull Requests

1. **Commit Messages**: Write clear, imperative commit messages:
   - `Add Louvain modularity metric to graph community API`
   - `Fix foreign key constraint on account deletion`
2. **Push your branch**:
   ```bash
   git push origin feature/your-feature-name
   ```
3. **Open a PR**: Open a pull request against the `main` branch. Provide a clear summary of the changes, problem solved, and test results.

---

## Questions and Support

Feel free to open an issue on GitHub or reach out to the project maintainer:
- GitHub: [@RUCHITHA-M-DEV](https://github.com/RUCHITHA-M-DEV)
- Email: `pes2ug23cs497@pesu.pes.edu`
