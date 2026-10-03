# SquareUp: Local Roommate Expense Settler

SquareUp is a local Streamlit prototype for logging shared rent, utility bills, and one-off roommate adjustments. It calculates roommate shares, shows action steps, visualizes spending, and supports CSV ledger export/import.

## Requirements

- Python 3.10 or later
- Internet connection for the initial package installation

## Setup and run

1. Open this project folder in VS Code.
2. Open a new terminal.
3. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

4. Install required packages:

```bash
python3 -m pip install -r requirements.txt
```

5. Start the prototype:

```bash
python3 -m streamlit run app.py
```

6. Open the Local URL shown in the terminal, usually:

```text
http://localhost:8501
```

To stop the app, return to the terminal and press `Control + C`.

## Prototype scope

This is a local prototype. It does not use sign-in, a cloud database, rent portals, utility-provider integrations, or payment verification.

Ledger entries are held in the active browser session. Use the sidebar’s Import / Export section to export a CSV backup before closing or refreshing the app. Attached receipt PDFs are available during the active session but are not included in CSV exports.

## Sample inputs

### Normal case

Household: Lana, Dylan, Bob

1. Set Months owed to `3` and Your share to `$600`, then select Add Rent to Ledger.
2. Add a utility bill:
   - Label: `April Electric`
   - Category: `Electric`
   - Amount: `$90`
   - Paid by: `Lana`
3. Add an adjustment:
   - Reason: `Shared bike repair`
   - Amount: `$64`
   - Months: `1`
   - Direction: `This roommate owes me`
   - Roommate: `Bob`

### Custom-split case

Household: Lana, Dylan, Bob

1. Open Log Utility Bill.
2. Select Custom split percentages.
3. Add:
   - Label: `May Internet`
   - Category: `Internet`
   - Amount: `$80`
   - Paid by: `Dylan`
   - Lana: `50%`
   - Dylan: `50%`
   - Bob: `0%`

This simulates Bob being away for the full billing period.

### Invalid-split case

Use the same $80 internet bill, but enter:

- Lana: `20%`
- Dylan: `30%`
- Bob: `0%`

The prototype should reject the bill because the split total is 50%, not 100%.