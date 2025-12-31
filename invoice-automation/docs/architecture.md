# Architecture

## Overview
- Single Python script orchestrates the pipeline
- Reads JSON invoices, validates, posts to API, writes CSV

## Data flow
invoices/ -> validation -> API POST -> output CSV + logs

## Key decisions
- Keep IO paths local for quick demos
- Use httpbin by default for a safe endpoint
