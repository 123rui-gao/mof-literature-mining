# MOF Literature Mining Pipeline

A 3-phase pipeline for automated MOF (Metal-Organic Framework) literature extraction: CSD structure lookup, PDF download, and LLM-based data extraction.

## Overview

```
Phase 1 (CSD API)          Phase 2 (Download)         Phase 3 (LLM)
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│ RefCode / name   │ ────→ │ DOI list         │ ────→ │ PDF text         │
│      ↓           │       │      ↓           │       │      ↓           │
│ CSD lookup       │       │ scansci-pdf      │       │ PyMuPDF extract  │
│ SI→DOI construct │       │ Chrome+HTTP (SI) │       │ Keyword filter   │
│      ↓           │       │      ↓           │       │      ↓           │
│ DOI + a,b,c      │       │ Main PDF + SI    │       │ DeepSeek API     │
└─────────────────┘       └─────────────────┘       │      ↓           │
                                                     │ BET, Synthesis,  │
                                                     │ Crystal match    │
                                                     └─────────────────┘
```

**Input:** CSV with compound names and predictions (predicted_log1p, predicted_mol_kg)

**Output:** Excel with extracted Paper_structure_name, Lattice_match_evidence, BET, BET_evidence, Synthesis, Synthesis_evidence

## Requirements

- Python 3.10+
- **Phase 1:** CCDC CSD Python API (requires CCDC license; only runs in licensed environments)
- **Phase 2:** Chrome browser (for ACS/Wiley/Elsevier SI downloads), scansci-pdf
- **Phase 3:** DeepSeek API key

## Installation

```bash
git clone <repo-url>
cd mof_literature_pipeline
pip install -r requirements.txt
```

### Chrome Setup (Phase 2)

Phase 2 uses Chrome at `C:\Program Files\Google\Chrome\Application\chrome.exe` for Cloudflare bypass. Update `CHROME_BIN` in `si_download/batch_downloader.py` if your Chrome is installed elsewhere.

### scansci-pdf Setup (Phase 2)

Verify the scansci-pdf environment after installation:

```bash
pip install scansci-pdf
scansci-pdf check
```

Sci-Hub, WebVPN, and proxy settings are configured via MCP tools (`scansci_pdf_config_set`) or in `~/.scansci-pdf/`.

### CSD API Setup (Phase 1)

Phase 1 requires the CCDC CSD Python API, which is only installable on machines with a valid CCDC license. Run Phase 1 on a licensed VM or skip it if your input CSV already has DOI and unit cell columns.

## Configuration

Copy `.env.example` to `.env` and fill in your API key:

```bash
cp .env.example .env
```

Required settings:

| Variable | Description | Default |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key (Phase 3) | *(required)* |
| `DEEPSEEK_BASE_URL` | API endpoint | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | Model name | `deepseek-v4-flash` |

The `.env` file is gitignored — never commit API keys.

## Usage

### Unified CLI (`run_pipeline.py`)

```bash
# Run all 3 phases
python run_pipeline.py --all -i compounds.csv --final output.xlsx

# Run individual phases
python run_pipeline.py --phase1 -i compounds.csv -o phase1_out.csv
python run_pipeline.py --phase2 -i phase1_out.csv -o phase2_out.csv
python run_pipeline.py --phase3 -i phase2_out.csv -o final.xlsx
```

### Phase 1: CSD Lookup

```bash
python phase1_csd.py -i input.csv -o phase1_output.csv
```

**Input columns:** name, predicted_log1p, predicted_mol_kg

**Output adds:** matched_identifier, doi, a, b, c, alpha, beta, gamma, status

**Strategies (tried in order):**
1. 6-letter CSD refcode lookup (e.g., AVEQID → CSD entry → DOI)
2. 6-letter + digits (e.g., FIRNAX01)
3. SI filename → article DOI construction:
   - ACS: `ja9b12924_si_002_2` → `10.1021/ja9b12924`
   - RSC: `c5sc03494a2` → `10.1039/C5SC03494A`
4. Article DOI → CSD search by DOI

### Phase 2: Paper Download

```bash
# Full download (main PDF + SI)
python phase2_download.py -i phase1_output.csv -o phase2_output.csv

# Main PDF only
python phase2_download.py -i phase1_output.csv --main-only

# SI only
python phase2_download.py -i phase1_output.csv --si-only

# Limit to N DOIs
python phase2_download.py -i phase1_output.csv --limit 10
```

**Main PDF:** Uses scansci-pdf with Sci-Hub / OA / publisher sources.

**SI download by publisher:**

| Publisher | Method | Why |
|---|---|---|
| ACS | Selenium + Chrome | Cloudflare bypass |
| Wiley | Selenium + Chrome | Cloudflare bypass |
| Elsevier | Chrome + HTTP HEAD | PII extraction, MMC CDN probing |
| RSC | Pure HTTP | No Cloudflare |

DOIs are **grouped by publisher** — one Chrome session per publisher type, avoiding repeated browser restarts.

**Output adds:** Main_PDF, SI_Path

### Phase 3: LLM Extraction

```bash
python phase3_llm.py -i phase2_output.csv -o final_output.xlsx

# Limit to first N PDF groups (for testing)
python phase3_llm.py -i phase2_output.csv -o final_output.xlsx --limit-groups 5

# Skip cache
python phase3_llm.py -i phase2_output.csv --skip-llm-cache
```

**Pipeline:**
1. Group rows by Main_PDF
2. Extract PDF text via PyMuPDF (PyMuPDF)
3. Filter by keywords (synthesis, BET, crystallography terms)
4. Call DeepSeek LLM with structured prompts
5. Parse JSON response
6. Post-hoc validation:
   - **Lattice self-check:** verify evidence text contains cell parameter values within 1% relative / 0.15 Angstrom absolute tolerance
   - **BET normalization:** extract pure numeric value from strings like "1532 m2/g"
7. Checkpoint save after each PDF group

**Output columns:** Paper_structure_name, Lattice_match_evidence, BET, BET_evidence, Synthesis, Synthesis_evidence

## Caching

The pipeline uses two-tier caching to avoid redundant work:

| Cache | Location | Key |
|---|---|---|
| PDF text | `cache/pdf/<sha256>.txt` | File paths + sizes + mtimes |
| LLM response | `cache/llm/<sha256>.txt` | Model + prompt version + literature hash + structure payload |

Cache is automatically created and reused. Use `--skip-pdf-cache` / `--skip-llm-cache` to bypass.

## Directory Structure

```
mof_literature_pipeline/
├── run_pipeline.py          # Unified CLI entry point
├── phase1_csd.py            # Phase 1: CSD lookup
├── phase2_download.py       # Phase 2: Paper download orchestrator
├── phase3_llm.py            # Phase 3: LLM extraction orchestrator
├── requirements.txt
├── .env.example
├── .gitignore
│
├── llm/                     # LLM extraction modules
│   ├── client.py            # DeepSeek API client (exponential backoff)
│   ├── prompts.py           # System/user prompt templates
│   ├── models.py            # Pydantic output models
│   ├── parser.py            # JSON response parser
│   └── validator.py         # Post-hoc BET/lattice validation
│
├── pdf_utils/               # PDF processing
│   ├── extractor.py         # PyMuPDF text extraction
│   └── filter.py            # Keyword-based paragraph filtering
│
├── si_download/             # SI download by publisher
│   ├── batch_downloader.py  # Core batch downloader (Chrome/HTTP sessions)
│   ├── acs.py               # ACS SI collector
│   ├── wiley.py             # Wiley SI collector
│   ├── elsevier.py          # Elsevier SI collector
│   └── rsc.py               # RSC SI collector
│
├── utils/                   # Shared utilities
│   ├── config.py            # Pydantic Settings (.env loader)
│   ├── cache.py             # Cache key generation
│   └── logging.py           # loguru setup
│
├── papers/                  # Downloaded PDFs (gitignored)
├── cache/                   # PDF/LLM cache (gitignored)
└── logs/                    # Log files (gitignored)
```

## Input Format

### Phase 1 Input (CSV)

| name | predicted_log1p | predicted_mol_kg |
|---|---|---|
| AVEQID | 0.5 | 200.0 |
| ja9b12924_si_002 | 0.3 | 150.0 |

### Phase 1 Output / Phase 2 Input (CSV)

Adds: matched_identifier, doi, a, b, c, alpha, beta, gamma, status

### Phase 2 Output / Phase 3 Input (CSV)

Adds: Main_PDF (absolute path), SI_Path (semicolon-separated paths)

### Phase 3 Output (Excel)

Adds: Paper_structure_name, Lattice_match_evidence, BET, BET_evidence, Synthesis, Synthesis_evidence

## Notes

- **CSD API:** Phase 1 requires a CCDC-licensed environment. If unavailable, prepare a CSV with doi/a/b/c columns manually and start from Phase 2.
- **SI CIF files:** The pipeline automatically filters out `.cif` files from SI downloads to save disk space and processing time.
- **Lattice self-check:** Enabled by default in Phase 3. When evidence text doesn't contain matching cell parameters, BET and Synthesis are cleared for that RefCode. Disable with `--disable-lattice-self-check`.
- **Prompt language:** The LLM system prompt is in Chinese for better extraction accuracy on Chinese-authored MOF papers.
