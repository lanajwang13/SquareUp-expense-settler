import pandas as pd
import base64
import json
import io

LEDGER_COLS = [
    "Label", "Category", "Payer", "Recipient", "Qty",
    "Total Amount", "My Share", "File_Name", "File_Object",
    "Date", "Notes", "Custom Splits"
]

def empty_ledger():
    """Return an empty ledger with all required columns."""
    return pd.DataFrame(columns=LEDGER_COLS)

def ledger_to_csv(ledger_df):
    """Export rows and split percentages, excluding receipt files."""
    export = ledger_df.reindex(columns=LEDGER_COLS).drop(columns=["File_Object"]).copy()
    if "Custom Splits" in export.columns:
        export["Custom Splits"] = export["Custom Splits"].apply(
            lambda x: json.dumps(x) if isinstance(x, dict) else ""
        )
    return export.to_csv(index=False).encode("utf-8")

def ledger_from_csv(uploaded):
    """Restore an exported ledger, including old CSVs with an index column."""
    incoming = pd.read_csv(uploaded)
    incoming = incoming.loc[:, ~incoming.columns.str.startswith("Unnamed:")]
    required = {"Label", "Category", "Payer", "Recipient", "Total Amount"}
    missing = required - set(incoming.columns)
    if missing:
        raise ValueError("Missing CSV columns: " + ", ".join(sorted(missing)))
    for col in LEDGER_COLS:
        if col not in incoming.columns:
            incoming[col] = None
    incoming = incoming.reindex(columns=LEDGER_COLS)
    def parse_splits(value):
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    incoming["Custom Splits"] = incoming["Custom Splits"].apply(parse_splits)
    for col in ("Total Amount", "My Share", "Qty"):
        incoming[col] = pd.to_numeric(incoming[col], errors="coerce").fillna(1 if col == "Qty" else 0)
    for col in ("Label", "Category", "Payer", "Recipient", "File_Name", "Date", "Notes"):
        incoming[col] = incoming[col].fillna("").astype(str)
    incoming["File_Object"] = None
    return incoming.reset_index(drop=True)


def display_pdf(file_obj):
    if file_obj is None:
        return ""
    bytes_data = file_obj if isinstance(file_obj, bytes) else file_obj.getvalue()
    base64_pdf = base64.b64encode(bytes_data).decode("utf-8")
    return f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600"></iframe>'

def get_user_share(row, user, roomie_list):
    """Return this user's share of a bill row, respecting custom splits."""
    splits = row.get("Custom Splits")
    if splits and isinstance(splits, dict) and user in splits:
        return row["Total Amount"] * (splits[user] / 100.0)
    return row["Total Amount"] / max(len(roomie_list), 1)

def calculate_settlement(ledger_df, perspective_user=None, roomie_list=None):
    """
    Returns (rent_total, utils_credit, adj_impact, final_owed).

    - rent_total    : total of all Rent entries in the ledger
    - utils_credit  : net of all non-Rent, non-Adjustment (for perspective_user if given)
    - adj_impact    : sum of Adjustments for perspective_user if given
    - final_owed    : what you still need to pay after credits/adjustments

    If perspective_user and roomie_list are provided, utils_credit and adj_impact
    are computed for that user (for "View as [roommate]"). Otherwise uses ledger
    My Share sums (original behavior).
    """
    if ledger_df.empty:
        return 0.0, 0.0, 0.0, 0.0

    rent_rows = ledger_df[ledger_df['Category'] == "🏠 Rent"]
    rent_total = abs(rent_rows["My Share"].sum()) if not rent_rows.empty else 0.0

    if perspective_user is not None and roomie_list is not None:
        n = max(len(roomie_list), 1)
        # Rent rows record the named roommate's share; do not split again.
        rent_total = sum(float(row["Total Amount"]) for _, row in rent_rows.iterrows()
                         if row["Payer"] == perspective_user)
        utils_credit = 0.0
        adj_impact = 0.0
        for _, row in ledger_df.iterrows():
            cat = row["Category"]
            if cat == "🏠 Rent":
                continue
            if cat == "⚖️ Adjustment":
                if row["Payer"] == perspective_user or row["Recipient"] == perspective_user:
                    if row["Recipient"] == perspective_user:
                        adj_impact += abs(float(row["Total Amount"]))
                    else:
                        adj_impact -= abs(float(row["Total Amount"]))
                continue
            share = get_user_share(row, perspective_user, roomie_list)
            if row["Payer"] == perspective_user:
                utils_credit += (float(row["Total Amount"]) - share)
            else:
                utils_credit -= share
        final_owed = rent_total - utils_credit - adj_impact
        return rent_total, utils_credit, adj_impact, final_owed

    utils_credit = ledger_df[
        (~ledger_df['Category'].isin(["⚖️ Adjustment", "🏠 Rent"]))
    ]["My Share"].sum()
    adj_impact = ledger_df[ledger_df['Category'] == "⚖️ Adjustment"]["My Share"].sum()
    final_owed = rent_total - utils_credit - adj_impact
    return rent_total, utils_credit, adj_impact, final_owed

def get_personal_audit_unique(ledger_df, active_user, roomie_list):
    """
    Returns a list of line-item dicts for the active user's own audit panel.
    Each item: {id, desc, sub, impact}
      impact > 0 : money coming TO you (credit)
      impact < 0 : money going FROM you (debit)
    """
    items = []
    if ledger_df.empty:
        return items

    for idx, row in ledger_df.iterrows():
        cat = row["Category"]

        if cat == "🏠 Rent":
            if row["Payer"] == active_user:
                impact = -abs(float(row["Total Amount"]))
                qty = max(float(row.get("Qty") or 1), 1)
                sub = f"{qty:g} month(s) × ${float(row['Total Amount']) / qty:,.0f}/mo → Landlord"
                items.append({"id": idx, "desc": row["Label"], "sub": sub, "impact": impact})

        elif cat == "⚖️ Adjustment":
            if row["Payer"] == active_user or row["Recipient"] == active_user:
                impact = float(row["Total Amount"]) if row["Recipient"] == active_user else -float(row["Total Amount"])
                direction = "you receive" if impact > 0 else "you pay"
                other = row["Recipient"] if row["Payer"] == active_user else row["Payer"]
                items.append({
                    "id":     idx,
                    "desc":   f"Adj: {row['Label']}",
                    "sub":    f"{direction} · other party: {other}",
                    "impact": impact
                })

        else:
            # Utility bill
            share = get_user_share(row, active_user, roomie_list)
            payer = row["Payer"]
            n     = len(roomie_list)
            splits = row.get("Custom Splits")
            if splits and isinstance(splits, dict):
                pct_str = f"{splits.get(active_user, round(100/n,1))}% of ${row['Total Amount']:,.2f}"
            else:
                pct_str = f"1/{n} of ${row['Total Amount']:,.2f}"

            if payer == active_user:
                # You paid — others owe you their shares
                others_share = row["Total Amount"] - share
                others = [r for r in roomie_list if r != active_user]
                sub = f"You paid ${row['Total Amount']:,.2f} · collecting from {', '.join(others)}"
                items.append({"id": idx, "desc": row["Label"], "sub": sub, "impact": others_share})
            else:
                # Someone else paid — you owe your share to them
                sub = f"{payer} paid ${row['Total Amount']:,.2f} · your share ({pct_str}) → {payer}"
                items.append({"id": idx, "desc": row["Label"], "sub": sub, "impact": -share})

    return items

def get_roommate_breakdown(ledger_df, active_user, roomie_list):
    """
    For each roommate (excluding active_user), calculates:
      net  > 0 : they owe YOU  (positive = you receive)
      net  < 0 : YOU owe them  (negative = you pay)
    Returns dict keyed by roommate name.
    """
    breakdown = {}
    for roomie in roomie_list:
        if roomie == active_user:
            continue

        utils_net  = 0.0
        adj_net    = 0.0
        items      = []

        if not ledger_df.empty:
            for idx, row in ledger_df.iterrows():
                cat   = row["Category"]
                payer = row["Payer"]

                if cat in ("🏠 Rent", "⚖️ Adjustment"):
                    # Rent is personal — doesn't affect roommate balance
                    # Adjustments: only count if this roomie is directly involved
                    if cat == "⚖️ Adjustment":
                        if row["Recipient"] == roomie and row["Payer"] == active_user:
                            # We gave them something — they owe us less (negative for us)
                            impact = -abs(float(row["Total Amount"]))
                            adj_net += impact
                            items.append({
                                "id": idx, "desc": f"Adj: {row['Label']}",
                                "sub": f"You paid {roomie} ${abs(impact):,.2f}",
                                "impact": impact, "type": "financial"
                            })
                        elif row["Payer"] == roomie and row["Recipient"] == active_user:
                            # They gave us something — they owe us more (positive for us)
                            impact = abs(float(row["Total Amount"]))
                            adj_net += impact
                            items.append({
                                "id": idx, "desc": f"Adj: {row['Label']}",
                                "sub": f"{roomie} paid you ${impact:,.2f}",
                                "impact": impact, "type": "financial"
                            })
                    continue

                # Utility bill — figure out what this roomie owes you or vice versa
                roomie_share = get_user_share(row, roomie, roomie_list)
                user_share   = get_user_share(row, active_user, roomie_list)
                n            = len(roomie_list)
                splits       = row.get("Custom Splits")

                def pct_label(person):
                    if splits and isinstance(splits, dict):
                        return f"{splits.get(person, round(100/n,1))}%"
                    return f"1/{n}"

                if payer == active_user:
                    # You paid — roomie owes you their share → positive (credit to you)
                    impact = roomie_share
                    utils_net += impact
                    items.append({
                        "id": idx, "desc": row["Label"],
                        "sub": f"You paid ${row['Total Amount']:,.2f} · {roomie} owes you {pct_label(roomie)} = ${roomie_share:,.2f}",
                        "impact": impact, "type": "financial"
                    })
                elif payer == roomie:
                    # Roomie paid — you owe them your share → negative (debit to you)
                    impact = -user_share
                    utils_net += impact
                    items.append({
                        "id": idx, "desc": row["Label"],
                        "sub": f"{roomie} paid ${row['Total Amount']:,.2f} · you owe {pct_label(active_user)} = ${user_share:,.2f}",
                        "impact": impact, "type": "financial"
                    })
                else:
                    # Third party paid — neutral between you and this roomie
                    items.append({
                        "id": idx, "desc": row["Label"],
                        "sub": f"Paid by {payer} · no balance between you and {roomie}",
                        "impact": 0.0, "type": "neutral"
                    })

        net = utils_net + adj_net
        breakdown[roomie] = {
            "utils": utils_net,
            "adj":   adj_net,
            "net":   net,
            "items": items
        }

    return breakdown

def get_p2p_instructions(breakdown, rent_total, final_owed):
    """
    Generate concrete action steps:
    - One step per roommate with a non-zero balance
    - One rent step if rent is owed
    Steps are sorted: receives first, then payments, then rent.
    """
    receives = []
    payments = []

    for name, data in breakdown.items():
        net = data["net"]
        if abs(net) < 0.005:
            continue
        if net > 0:
            receives.append(f"📥 Collect **${net:,.2f}** from **{name}**")
        else:
            payments.append(f"📤 Pay **${abs(net):,.2f}** to **{name}**")

    rent_steps = []
    if rent_total > 0:
        rent_steps.append(f"🏠 Pay **${rent_total:,.2f}** rent to **Landlord**")

    return receives + payments + rent_steps