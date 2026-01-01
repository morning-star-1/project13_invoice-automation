# Invoice Automation Demo

A small but realistic invoice processing pipeline that validates JSON invoices, flags exceptions, and writes a CSV output.

## Quickstart
### Prerequisites
- Python 3.11+

### Run locally
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python invoice_automation.py
```

Skip API posting (offline demo):
```bash
python invoice_automation.py --skip-api
```

Custom endpoint:
```bash
python invoice_automation.py --endpoint https://httpbin.org/post
```

## Inputs and outputs
- `invoices/` sample input JSON files
- `output/processed_invoices.csv` generated output
- `logs/invoice_automation.log` run logs

## Tests
```bash
python -m unittest discover -s tests
```
