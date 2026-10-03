import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import html
from pathlib import Path
from datetime import date
import engine


def _append_ledger_row(ledger: pd.DataFrame, row: dict) -> pd.DataFrame:
    """Append a row to the ledger without triggering concat dtype warnings."""
    if "id" in row and "id" not in ledger.columns:
        ledger = ledger.assign(id=pd.NA)
    cols = list(ledger.columns)
    new_df = pd.DataFrame([row]).reindex(columns=cols, fill_value=pd.NA)
    if ledger.empty:
        return new_df.reset_index(drop=True)
    return pd.concat([ledger, new_df], ignore_index=True)


st.set_page_config(page_title="SquareUp 🏠", layout="wide", page_icon="🏠")

# Load the original visual theme from a separate CSS file.
st.markdown("<style>" + Path(__file__).with_name("styles.css").read_text(encoding="utf-8") + "</style>",
            unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# CHART HELPERS
# ─────────────────────────────────────────────────────────────────────────────
BG   = "rgba(0,0,0,0)"
FONT = dict(family="Plus Jakarta Sans", color="#3A2E22")
COLORS = [
    "#D4845A", "#C9A84C", "#C8BE5A", "#ACB090", "#6BA8A0",
    "#99ABA6", "#7AA8C8", "#8F88C0", "#B088B8", "#C08898",
]
C_GAIN = "#16A34A"
C_OWE  = "#DC2626"
C_ZERO = "#D8CCB0"

def donut(labels, values, colors, center):
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.62,
        marker=dict(colors=colors, line=dict(color="#F0EAD8", width=3)),
        textinfo="percent", textfont=dict(size=12, family="Plus Jakarta Sans", color="#fff"),
        hovertemplate="<b>%{label}</b><br>$%{value:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=BG, font=FONT, height=240,
        margin=dict(t=8, b=8, l=8, r=8),
        legend=dict(font=dict(family="Plus Jakarta Sans", size=12, color="#5E4B3B"), x=1.0, y=0.5, bgcolor=BG),
        annotations=[dict(text=f"<b>{center}</b>", x=0.5, y=0.5, showarrow=False,
                          font=dict(size=12, family="Plus Jakarta Sans", color="#5E4B3B"))]
    )
    return fig

def bar_balance(names, values):
    bar_colors = [C_GAIN if v > 0 else C_OWE if v < 0 else C_ZERO for v in values]
    fig = go.Figure(go.Bar(
        x=names, y=values, marker_color=bar_colors,
        marker_line_color=["#15803D" if v > 0 else "#B91C1C" if v < 0 else "#C4B89A" for v in values],
        marker_line_width=1.5,
        text=[f"${abs(v):,.0f}" for v in values], textposition="outside",
        textfont=dict(size=12, family="Plus Jakarta Sans", color="#3A2E22"),
        hovertemplate="<b>%{x}</b><br>$%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=BG, font=FONT, height=260,
        margin=dict(t=32, b=8, l=8, r=8), bargap=0.45,
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=13, family="Plus Jakarta Sans", color="#5E4B3B")),
        yaxis=dict(showgrid=True, gridcolor="#D8CCB0", zeroline=True, zerolinecolor="#5E4B3B", zerolinewidth=2,
                   tickprefix="$", tickfont=dict(size=11, family="Plus Jakarta Sans", color="#99ABA6")),
    )
    return fig

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
# Entries are session-only. Export CSV to keep a durable copy.
if "ledger" not in st.session_state:
    st.session_state.ledger = engine.empty_ledger()

# Sidebar controls and forms mirror the original layout, without authentication.
with st.sidebar:
    st.markdown("<div class='sq-logo'>🏠 SquareUp</div>", unsafe_allow_html=True)
    st.markdown("<div class='sq-tagline'>Expense Settler · Local</div>", unsafe_allow_html=True)
    st.caption("No sign-in or database. Export CSV before closing or refreshing this tab.")
    c1, c2 = st.columns(2)
    with c1:
        print_mode = st.toggle("🖨️ Print", key="print_toggle")
    with c2:
        dark_mode = st.toggle("🌙 Dark Mode", key="dark_toggle")
    st.divider()
    st.markdown("<div class='sq-lbl'>Household</div>", unsafe_allow_html=True)
    names_raw = st.text_input("Roommates (comma-separated)", value="Lana, Dylan, Bob", key="roommates_input")
    roomie_list = list(dict.fromkeys(x.strip() for x in names_raw.split(",") if x.strip()))
    if not roomie_list:
        st.warning("Enter at least one roommate.")
        st.stop()
    if st.session_state.get("active_user_select") not in roomie_list:
        st.session_state.active_user_select = roomie_list[0]
    active_user = st.selectbox("Which roommate are you?", roomie_list, key="active_user_select")
    st.markdown("<div class='sq-lbl'>View dashboard as</div>", unsafe_allow_html=True)
    if st.session_state.get("view_as_select") not in roomie_list:
        st.session_state.view_as_select = active_user
    view_as = st.selectbox("Perspective (preview only)", roomie_list, key="view_as_select",
                           help="Preview another roommate without changing who enters items.")
    st.divider()
    st.markdown("<div class='sq-lbl'>Rent Period</div>", unsafe_allow_html=True)
    r1, r2 = st.columns(2)
    with r1:
        months_owed = st.number_input("Months owed", min_value=0, value=0, key="months_owed_input")
    with r2:
        rent_share = st.number_input("Your share ($/mo)", min_value=0.0, value=0.0, key="rent_share_input")
    if months_owed and rent_share:
        total = months_owed * rent_share
        if st.button(f"＋ Add ${total:,.0f} Rent to Ledger", width="stretch"):
            # Rent records this roommate's personal share, not a bill to split.
            row = {"Label": f"Rent ({months_owed}mo × ${rent_share:,.0f})",
                   "Category": "🏠 Rent", "Payer": active_user, "Recipient": "Landlord",
                   "Qty": months_owed, "Total Amount": total, "My Share": -total,
                   "File_Name": "Manual", "File_Object": None, "Date": str(date.today()),
                   "Notes": f"{months_owed} month(s) at ${rent_share:,.2f}/mo", "Custom Splits": None}
            st.session_state.ledger = _append_ledger_row(st.session_state.ledger, row)
            st.rerun()
    st.divider()
    with st.expander("＋ Log Utility Bill"):
        # The checkbox must sit outside st.form: changing a form widget does not rerun the app.
        use_custom = st.checkbox("⚖️ Custom split percentages?", key="use_custom_splits")
        with st.form("bill_form", clear_on_submit=True):
            label = st.text_input("Label", placeholder="e.g. April Electric")
            category = st.selectbox("Category", ["⚡ Electric", "🔥 Gas", "💧 Water",
                "🌐 Internet", "🗑️ Conservice", "🎁 Other"])
            amount = st.number_input("Total Amount ($)", min_value=0.0, value=0.0)
            payer = st.selectbox("Paid by", roomie_list)
            bill_date = st.date_input("Date", value=date.today(), key="bill_date")
            notes = st.text_area("Notes (optional)", height=68)
            receipt = st.file_uploader("Receipt PDF (this session only)", type="pdf")
            splits = None
            if use_custom:
                splits = {}
                st.caption("Use 0% for a roommate who was away; percentages must total 100%.")
                for name in roomie_list:
                    splits[name] = st.number_input(f"{name} %", min_value=0.0, max_value=100.0,
                        value=0.0, step=1.0, key=f"bill_split_{name}")
            if st.form_submit_button("Add Bill", width="stretch"):
                if amount <= 0:
                    st.error("Enter an amount greater than zero.")
                elif use_custom and abs(sum(splits.values()) - 100) > 0.01:
                    st.error(f"Percentages total {sum(splits.values()):.2f}%, not 100%.")
                else:
                    # The engine recomputes each perspective from amount, payer and split.
                    share = amount * splits[active_user] / 100 if use_custom else amount / len(roomie_list)
                    row = {"Label": label.strip() or category, "Category": category,
                           "Payer": payer, "Recipient": "Service Provider", "Qty": 1,
                           "Total Amount": amount, "My Share": amount - share if payer == active_user else -share,
                           "File_Name": receipt.name if receipt else "Manual",
                           "File_Object": receipt.getvalue() if receipt else None,
                           "Date": str(bill_date), "Notes": notes, "Custom Splits": splits}
                    st.session_state.ledger = _append_ledger_row(st.session_state.ledger, row)
                    st.rerun()
    with st.expander("⚖️ Add Adjustment"):
        targets = [person for person in roomie_list if person != active_user]
        if not targets:
            st.info("Add another roommate first.")
        else:
            with st.form("adj_form", clear_on_submit=True):
                reason = st.text_input("Reason", placeholder="e.g. Parking credit")
                amount = st.number_input("Amount ($/month)", min_value=0.0, value=0.0, key="adj_amount")
                months = st.number_input("Months", min_value=1, value=1)
                direction = st.radio("Direction", ["I owe this roommate", "This roommate owes me"])
                target = st.selectbox("Roommate", targets)
                adj_date = st.date_input("Date", value=date.today(), key="adj_date")
                adj_notes = st.text_area("Notes (optional)", key="adj_notes")
                if st.form_submit_button("Add Adjustment", width="stretch"):
                    if amount <= 0:
                        st.error("Enter an amount greater than zero.")
                    else:
                        total = amount * months
                        impact = total if direction == "This roommate owes me" else -total
                        row = {"Label": reason.strip() or "Adjustment", "Category": "⚖️ Adjustment",
                               "Payer": active_user if impact < 0 else target,
                               "Recipient": target if impact < 0 else active_user,
                               "Qty": months, "Total Amount": total, "My Share": impact,
                               "File_Name": "Manual", "File_Object": None,
                               "Date": str(adj_date), "Notes": adj_notes, "Custom Splits": None}
                        st.session_state.ledger = _append_ledger_row(st.session_state.ledger, row)
                        st.rerun()
    st.divider()
    with st.expander("📂 Import / Export"):
        uploaded = st.file_uploader("Import CSV ledger", type="csv", key="csv_import")
        if uploaded is not None and st.button("Replace ledger with CSV", width="stretch"):
            try:
                st.session_state.ledger = engine.ledger_from_csv(uploaded)
                st.session_state.selected_entry = None
                st.rerun()
            except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
                st.error(f"Import failed: {exc}")
        st.download_button("⬇️ Export CSV", engine.ledger_to_csv(st.session_state.ledger),
                           "squareup_ledger.csv", "text/csv", width="stretch")
        st.caption("CSV does not include receipt PDFs or household settings.")

# Calculate balance cards, line items, payment steps and graphs from session ledger.
rent, utils, adjs, final = engine.calculate_settlement(st.session_state.ledger, view_as, roomie_list)
breakdown = engine.get_roommate_breakdown(st.session_state.ledger, view_as, roomie_list)
p2p_steps = engine.get_p2p_instructions(breakdown, rent, final)
personal_audit = engine.get_personal_audit_unique(st.session_state.ledger, view_as, roomie_list)
bills_df = st.session_state.ledger[~st.session_state.ledger["Category"].isin(["⚖️ Adjustment", "🏠 Rent"])].copy()
bills_df["Total Amount"] = pd.to_numeric(bills_df["Total Amount"], errors="coerce").fillna(0)

# ─────────────────────────────────────────────────────────────────────────────
# DARK MODE
# ─────────────────────────────────────────────────────────────────────────────
if dark_mode:
    st.markdown("""
<style>
.stApp { background: #0E0D0B !important; }
[data-testid="stVerticalBlockBorderWrapper"] > div {
    background: #1A1713 !important; border-color: #332E27 !important; box-shadow: 0 4px 24px rgba(0,0,0,0.5) !important;
}
[data-testid="stSidebar"] { background: #28261A !important; border-right-color: #3A3620 !important; }
[data-testid="stSidebar"], [data-testid="stSidebar"] p, [data-testid="stSidebar"] span,
[data-testid="stSidebar"] div, [data-testid="stSidebar"] label { color: #C8BF98 !important; }
[data-testid="stSidebar"] .sq-lbl     { color: #7A7A50 !important; }
[data-testid="stSidebar"] .sq-tagline { color: #7A7A50 !important; }
[data-testid="stSidebar"] .sq-logo    { color: #E8DFD0 !important; }
[data-testid="stSidebar"] [data-baseweb="input"],
[data-testid="stSidebar"] [data-baseweb="base-input"],
[data-testid="stSidebar"] .stTextInput > div > div,
[data-testid="stSidebar"] .stNumberInput > div > div,
[data-testid="stSidebar"] [data-testid="stNumberInput"] > div,
[data-testid="stSidebar"] [data-testid="stNumberInput"] > div > div,
[data-testid="stSidebar"] .stDateInput > div > div,
[data-testid="stSidebar"] .stTextArea > div > div {
    background: #1E1C12 !important; border-color: #3A3620 !important; border-radius: 10px !important;
}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea { background: #1E1C12 !important; color: #C8BF98 !important; caret-color: #C8BF98 !important; border-radius: 8px !important; }
[data-testid="stSidebar"] input::placeholder { color: #5A5840 !important; }
[data-testid="stSidebar"] [data-baseweb="select"] > div { background: #1E1C12 !important; border-color: #3A3620 !important; color: #C8BF98 !important; }
[data-testid="stSidebar"] [data-testid="stExpander"] { background: #1E1C12 !important; border-color: #3A3620 !important; }
[data-testid="stSidebar"] [data-testid="stNumberInput"] button { background: #1E1C12 !important; border-color: #3A3620 !important; color: #C8BF98 !important; }
[data-testid="stSidebar"] .stButton > button { background: #4A4020 !important; color: #E8DFD0 !important; }
[data-testid="stSidebar"] hr { border-color: #3A3620 !important; }
h1, h2 { color: #E8DFD0 !important; }
h3     { color: #B8A880 !important; }
p      { color: #8A8070 !important; }
label, .stRadio label span { color: #7A7060 !important; }
.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stDateInput > div > div > input { background: #211F1A !important; border-color: #3A3528 !important; color: #D8CEB8 !important; }
.stSelectbox > div > div, .stMultiSelect > div > div { background: #211F1A !important; border-color: #3A3528 !important; }
.stTextArea textarea { background: #211F1A !important; border-color: #3A3528 !important; color: #D8CEB8 !important; }
[data-testid="stExpander"] { background: #161410 !important; border-color: #332E27 !important; }
[data-testid="stExpander"] summary { color: #7A7060 !important; }
.sq-lbl { color: #B8A880 !important; }
.sq-stat { background: #211F1A !important; border-color: #332E27 !important; }
.sq-stat-lbl { color: #5A5448 !important; }
.sq-stat-val { color: #D8CEB8 !important; }
.sq-step { background: #1E1C17 !important; border-color: #3A3528 !important; }
.sq-step-text { color: #B8AE98 !important; }
.sq-line { border-bottom-color: #2A2820 !important; }
.sq-line-desc { color: #7A7060 !important; }
.sq-card-stat { background: #211F1A !important; border-color: #332E27 !important; }
.sq-card-name { color: #E8DFD0 !important; }
.sq-card-stat-lbl { color: #5A5448 !important; }
.sq-hero-zero { color: #5A5448 !important; }
.sq-hero-owe  { color: #F87171 !important; }
.sq-hero-gain { color: #4ADE80 !important; }
.sq-pill-gray  { background: #2A2820 !important; color: #A89878 !important; }
.sq-pill-green { background: #0F2A18 !important; color: #4ADE80 !important; }
.sq-pill-red   { background: #2A0F0F !important; color: #F87171 !important; }
.sq-pill-blue  { background: #0F1E22 !important; color: #7AC8C0 !important; }
.sq-pos { color: #4ADE80 !important; }
.sq-neg { color: #F87171 !important; }
.sq-neu { color: #7A7060 !important; }
hr { border-color: #332E27 !important; }
[data-testid="stDataFrame"] { border-color: #332E27 !important; }
.stInfo    { background: #0F1E1C !important; border-color: #1E3C38 !important; color: #7AC8C0 !important; }
.stSuccess { background: #0A1F10 !important; border-color: #1A4020 !important; color: #4ADE80 !important; }
.stWarning { background: #1F1800 !important; border-color: #4A3800 !important; color: #FBBF24 !important; }
.stError   { background: #1F0A0A !important; border-color: #4A1A1A !important; color: #F87171 !important; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# PRINT MODE
# ─────────────────────────────────────────────────────────────────────────────
if print_mode:
    st.markdown("""
<style>
@media screen {
    .stApp { background: #ffffff !important; }
    [data-testid="stVerticalBlockBorderWrapper"] > div {
        background: #ffffff !important; border: 1px solid #ddd !important; box-shadow: none !important;
    }
    .sq-step { background: #f8f8f8 !important; border: 1px solid #ddd !important; }
    .sq-stat { background: #f8f8f8 !important; border: 1px solid #ddd !important; }
    h2 { font-size: 1.3rem !important; }
    h3 { font-size: 1.1rem !important; }
}
@media print {
    [data-testid="stSidebar"], .stAppDeployButton, #MainMenu, header, footer,
    .stButton, .stDownloadButton, [data-testid="stForm"], .sq-venmo,
    [data-testid="stExpander"] { display: none !important; }
    .stApp { background: #ffffff !important; }
    .main .block-container { padding-top: 0.5rem !important; max-width: 100% !important; }
    [data-testid="stVerticalBlockBorderWrapper"] > div { box-shadow: none !important; border: 1px solid #ccc !important; }
}
</style>
""", unsafe_allow_html=True)
    ec1, ec2, ec3 = st.columns([3, 1.4, 1])
    with ec1:
        st.info("🖨️ **Print-ready mode is on.** Use **File → Print** (Ctrl+P / Cmd+P) to print or save as PDF.")
    with ec2:
        st.markdown("<div style='padding-top:10px'></div>", unsafe_allow_html=True)
        if st.button("✖ Exit Print Mode", width="stretch"):
            st.session_state["print_toggle"] = False
            st.rerun()
    with ec3:
        st.markdown("")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE HEADER
# ─────────────────────────────────────────────────────────────────────────────
hc, tc = st.columns([5, 1])
with hc:
    if view_as != active_user:
        st.markdown(f"## 👁️ Preview: **{view_as}**'s view")
        st.markdown(f"<p style='color:#99ABA6;margin-top:-8px;font-weight:500'>You're viewing as {view_as}. You're still <b>{active_user}</b> for adding entries.</p>", unsafe_allow_html=True)
    else:
        st.markdown(f"## Hey, {active_user} 👋")
        st.markdown("<p style='color:#99ABA6;margin-top:-8px;font-weight:500'>Here's where things stand this period.</p>", unsafe_allow_html=True)
with tc:
    n = len(st.session_state.ledger)
    st.markdown(f"<div style='text-align:right;padding-top:16px'><span class='sq-pill sq-pill-gray'>{n} entr{'y' if n==1 else 'ies'}</span></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY CARD
# ─────────────────────────────────────────────────────────────────────────────
with st.container(border=True):
    lc, rc = st.columns([1, 1])
    with lc:
        balance_label = f"{view_as}'s Net Balance" if view_as != active_user else "Your Net Balance"
        st.markdown(f"<div class='sq-lbl'>{balance_label}</div>", unsafe_allow_html=True)
        if final > 0:
            sub_text = f"{view_as} owes this period" if view_as != active_user else "You owe this period"
            st.markdown(f"<div class='sq-hero-owe'>-${abs(final):,.2f}</div><div class='sq-hero-sub' style='color:#DC2626'>{sub_text}</div>", unsafe_allow_html=True)
        elif final < 0:
            sub_text = f"{view_as} is owed this period" if view_as != active_user else "You're owed this period"
            st.markdown(f"<div class='sq-hero-gain'>+${abs(final):,.2f}</div><div class='sq-hero-sub' style='color:#16A34A'>{sub_text}</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='sq-hero-zero'>$0.00</div><div class='sq-hero-sub' style='color:#99ABA6'>All square ✓</div>", unsafe_allow_html=True)

        u_col = "#16A34A" if utils >= 0 else "#DC2626"
        a_col = "#16A34A" if adjs  >= 0 else "#DC2626"
        rent_disp  = f"-${rent:,.2f}"  if rent  != 0 else "—"
        utils_disp = f"{'+'if utils>=0 else ''}${utils:,.2f}" if utils != 0 else "—"
        adjs_disp  = f"{'+'if adjs>=0 else ''}${adjs:,.2f}"  if adjs  != 0 else "—"
        st.markdown(f"""
        <div class='sq-stats'>
            <div class='sq-stat'>
                <div class='sq-stat-lbl'>Rent</div>
                <div class='sq-stat-val' style='color:{"#DC2626" if rent!=0 else "#99ABA6"}'>{rent_disp}</div>
            </div>
            <div class='sq-stat'>
                <div class='sq-stat-lbl'>Util Credits</div>
                <div class='sq-stat-val' style='color:{u_col if utils!=0 else "#99ABA6"}'>{utils_disp}</div>
            </div>
            <div class='sq-stat'>
                <div class='sq-stat-lbl'>Adjustments</div>
                <div class='sq-stat-val' style='color:{a_col if adjs!=0 else "#99ABA6"}'>{adjs_disp}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<div style='margin-top:14px'></div>", unsafe_allow_html=True)
        line_items_label = f"🔍 {view_as}'s line-items" if view_as != active_user else "🔍 Your line-items"
        with st.expander(line_items_label):
            if not personal_audit:
                st.markdown("<div style='color:#99ABA6;font-size:.88rem;padding:8px 0'>No entries yet — add bills or rent above.</div>", unsafe_allow_html=True)
            for item in personal_audit:
                cls  = "sq-pos" if item['impact'] > 0 else "sq-neg"
                sign = "+" if item['impact'] > 0 else "-"
                sub  = item.get('sub', '')
                st.markdown(f"""
                <div class='sq-line'>
                  <span class='sq-line-desc'>
                    <b>[{item['id']}] {item['desc']}</b>
                    {f"<br><span style='font-size:.78rem;color:#99ABA6'>{sub}</span>" if sub else ""}
                  </span>
                  <span class='sq-line-amount {cls}'>{sign}${abs(item['impact']):,.2f}</span>
                </div>""", unsafe_allow_html=True)

    with rc:
        steps_label = "Action Steps" if view_as == active_user else f"Action Steps ({view_as}'s view)"
        st.markdown(f"<div class='sq-lbl'>{steps_label}</div>", unsafe_allow_html=True)
        if not p2p_steps:
            st.markdown("<div class='sq-step'><span class='sq-step-icon'>✅</span><span class='sq-step-text'>No payments needed — you're all square!</span></div>", unsafe_allow_html=True)
        for step in p2p_steps:
            # Determine icon from emoji prefix
            if "📥" in step:
                icon = "📥"
                color = "#16A34A"
            elif "📤" in step:
                icon = "📤"
                color = "#DC2626"
            else:
                icon = "🏠"
                color = "#5E4B3B"

            # Convert **bold** markdown to HTML, strip emoji prefix
            import re
            clean = step.replace("📥 ", "").replace("📤 ", "").replace("🏠 ", "")
            clean_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', clean)

            # Add Venmo link for outgoing payments to a roommate
            venmo_html = ""
            if icon == "📤":
                for name, data in breakdown.items():
                    if name in step and data['net'] < 0:
                        venmo_html = f"<br><a href='https://venmo.com' target='_blank' class='sq-venmo'>💙 Pay {name} on Venmo</a>"
                        break

            st.markdown(
                f"<div class='sq-step'>"
                f"<span class='sq-step-icon'>{icon}</span>"
                f"<span class='sq-step-text' style='color:{color}'>{clean_html}{venmo_html}</span>"
                f"</div>",
                unsafe_allow_html=True
            )
        st.markdown("<div style='margin-top:14px'></div>", unsafe_allow_html=True)
        with st.popover("📊 Math breakdown", width="stretch"):
            st.markdown(f"**Rent owed:** ${rent:,.2f}")
            st.markdown(f"**Utility credits (net):** ${utils:,.2f}")
            st.markdown(f"**Adjustments:** ${adjs:,.2f}")
            st.divider()
            st.markdown(f"**Final = Rent − Util credits − Adjustments**")
            st.markdown(f"**= ${rent:,.2f} − ${utils:,.2f} − ${adjs:,.2f} = ${final:,.2f}**")
            if final > 0:
                st.error(f"You owe **${final:,.2f}**")
            elif final < 0:
                st.success(f"You are owed **${abs(final):,.2f}**")
            else:
                st.info("All square ✓")

# ─────────────────────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("### 📊 Spending Visuals")
with st.container(border=True):
    dc1, dc2 = st.columns(2)
    with dc1:
        st.markdown("<div class='sq-lbl'>Spending by Category</div>", unsafe_allow_html=True)
        if not bills_df.empty:
            ct = bills_df.groupby('Category')['Total Amount'].sum().reset_index()
            ct = ct[ct['Total Amount'] > 0]
            if not ct.empty:
                lbls = [c.split(" ",1)[1] if " " in c else c for c in ct['Category']]
                st.plotly_chart(donut(lbls, ct['Total Amount'].tolist(), COLORS[:len(lbls)], "Category"),
                                width="stretch", config={"displayModeBar": False})
            else:
                st.info("No amounts yet.")
        else:
            st.info("Add bills to see breakdown.")
    with dc2:
        st.markdown("<div class='sq-lbl'>Who Paid What</div>", unsafe_allow_html=True)
        if not bills_df.empty:
            pt = bills_df.groupby('Payer')['Total Amount'].sum().reset_index()
            pt = pt[pt['Total Amount'] > 0]
            if not pt.empty:
                st.plotly_chart(donut(pt['Payer'].tolist(), pt['Total Amount'].tolist(), COLORS[:len(pt)], "Payer"),
                                width="stretch", config={"displayModeBar": False})
            else:
                st.info("No bills yet.")
        else:
            st.info("Add bills to see payer split.")
    st.markdown("<hr style='margin:8px 0 12px;border-color:#D8CCB0'>", unsafe_allow_html=True)
    st.markdown("<div class='sq-lbl'>Net Balances — what each roommate owes you (or you owe them)</div>", unsafe_allow_html=True)
    if breakdown:
        names  = list(breakdown.keys())
        values = [breakdown[n]['net'] for n in names]
        if any(v != 0 for v in values):
            st.plotly_chart(bar_balance(names, values), width="stretch", config={"displayModeBar": False})
            st.markdown("<div style='font-size:.78rem;color:#99ABA6;text-align:center'>🟢 they owe you &nbsp;·&nbsp; 🔴 you owe them</div>", unsafe_allow_html=True)
        else:
            st.info("All balances are even — nothing to chart.")
    else:
        st.info("Add roommates to see balance chart.")

# ─────────────────────────────────────────────────────────────────────────────
# ROOMMATE CARDS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("### Roommate Breakdown")
roommate_names = list(breakdown.keys())
if not roommate_names:
    st.info("No roommates found. Add them in the sidebar.")
else:
    ncols = min(len(roommate_names), 3)
    cols  = st.columns(ncols)
    for i, name in enumerate(roommate_names):
        data = breakdown[name]
        with cols[i % ncols]:
            with st.container(border=True):
                net_pill = (f"<span class='sq-pill sq-pill-green'>Owes you ${abs(data['net']):.2f}</span>" if data['net'] > 0
                            else f"<span class='sq-pill sq-pill-red'>You owe ${abs(data['net']):.2f}</span>" if data['net'] < 0
                            else "<span class='sq-pill sq-pill-gray'>Even ✓</span>")
                st.markdown(f"<div class='sq-card-head'><div class='sq-card-name'>👤 {name}</div>{net_pill}</div>", unsafe_allow_html=True)
                uc = "sq-pos" if data['utils'] >= 0 else "sq-neg"
                ac = "sq-pos" if data['adj']   >= 0 else "sq-neg"
                nc = "sq-pos" if data['net']   >  0 else ("sq-neg" if data['net'] < 0 else "sq-neu")
                st.markdown(f"""
                <div class='sq-card-stats'>
                    <div class='sq-card-stat'><div class='sq-card-stat-lbl'>Utilities</div><div class='sq-card-stat-val {uc}'>${abs(data['utils']):,.2f}</div></div>
                    <div class='sq-card-stat'><div class='sq-card-stat-lbl'>Adjustments</div><div class='sq-card-stat-val {ac}'>${abs(data['adj']):,.2f}</div></div>
                    <div class='sq-card-stat'><div class='sq-card-stat-lbl'>Net</div><div class='sq-card-stat-val {nc}'>${abs(data['net']):,.2f}</div></div>
                </div>""", unsafe_allow_html=True)
                if data['net'] < 0:
                    st.markdown(f"<div style='margin-top:10px'><a href='https://venmo.com' target='_blank' class='sq-venmo'>💙 Pay {name} on Venmo</a></div>", unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)
                with st.expander("View line-items"):
                    for item in data['items']:
                        sub = item.get('sub', '')
                        if item['type'] == 'neutral':
                            st.markdown(f"""
                            <div class='sq-line'>
                              <span class='sq-line-desc'>
                                <b>[{item['id']}] {item['desc']}</b>
                                {f"<br><span style='font-size:.78rem;color:#99ABA6'>{sub}</span>" if sub else ""}
                              </span>
                              <span class='sq-line-amount sq-neu'>neutral</span>
                            </div>""", unsafe_allow_html=True)
                        else:
                            cls  = "sq-pos" if item['impact'] > 0 else "sq-neg"
                            sign = "+" if item['impact'] > 0 else "-"
                            st.markdown(f"""
                            <div class='sq-line'>
                              <span class='sq-line-desc'>
                                <b>[{item['id']}] {item['desc']}</b>
                                {f"<br><span style='font-size:.78rem;color:#99ABA6'>{sub}</span>" if sub else ""}
                              </span>
                              <span class='sq-line-amount {cls}'>{sign}${abs(item['impact']):,.2f}</span>
                            </div>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# FULL LEDGER
# ─────────────────────────────────────────────────────────────────────────────
if not st.session_state.ledger.empty:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### Full Ledger")
    st.markdown("<p style='color:#99ABA6;margin-top:-6px;font-size:.88rem'>Click <b>📄 View</b> on any row to see its receipt and details inline.</p>", unsafe_allow_html=True)
    if 'selected_entry' not in st.session_state:
        st.session_state.selected_entry = None
    if 'confirm_delete' not in st.session_state:
        st.session_state.confirm_delete = None

    h0,h1,h2,h3,h4,h5,h6 = st.columns([0.5,1,2,1.2,1,1,0.7])
    hs = "font-size:.72rem;font-weight:700;color:#99ABA6;text-transform:uppercase;letter-spacing:.08em;padding:4px 4px 6px 0"
    h0.markdown(f"<div style='{hs}'>#</div>",        unsafe_allow_html=True)
    h1.markdown(f"<div style='{hs}'>Date</div>",     unsafe_allow_html=True)
    h2.markdown(f"<div style='{hs}'>Label</div>",    unsafe_allow_html=True)
    h3.markdown(f"<div style='{hs}'>Payer</div>",    unsafe_allow_html=True)
    h4.markdown(f"<div style='{hs}'>Total</div>",    unsafe_allow_html=True)
    h5.markdown(f"<div style='{hs}'>My Share</div>", unsafe_allow_html=True)
    h6.markdown(f"<div style='{hs}'>Details</div>",  unsafe_allow_html=True)
    st.markdown("<hr style='margin:0 0 2px'>", unsafe_allow_html=True)

    for idx, row in st.session_state.ledger.iterrows():
        is_sel  = st.session_state.selected_entry == idx
        row_bg  = "background:#EDE8D8;border-radius:8px;" if is_sel else ""
        cell    = f"font-size:.88rem;font-weight:500;color:#3A2E22;padding:9px 4px 9px 0;{row_bg}"
        c0,c1,c2,c3,c4,c5,c6 = st.columns([0.5,1,2,1.2,1,1,0.7])
        c0.markdown(f"<div style='{cell}'>{idx}</div>", unsafe_allow_html=True)
        c1.markdown(f"<div style='{cell}'>{str(row.get('Date',''))[:10]}</div>", unsafe_allow_html=True)
        label_text = str(row.get('Label',''))
        cat_text   = str(row.get('Category',''))
        c2.markdown(f"<div style='{cell}'><b>{label_text}</b><br><span style='font-size:.75rem;color:#99ABA6'>{cat_text}</span></div>", unsafe_allow_html=True)
        c3.markdown(f"<div style='{cell}'>{row.get('Payer','')}</div>", unsafe_allow_html=True)
        c4.markdown(f"<div style='{cell}'>${float(row.get('Total Amount',0)):,.2f}</div>", unsafe_allow_html=True)
        share_val  = float(row.get('My Share',0))
        share_col  = "#16A34A" if share_val > 0 else "#DC2626" if share_val < 0 else "#99ABA6"
        share_sign = "+" if share_val > 0 else ""
        c5.markdown(f"<div style='{cell};color:{share_col};font-weight:700'>{share_sign}${share_val:,.2f}</div>", unsafe_allow_html=True)
        has_file  = bool(row.get('File_Object'))
        btn_label = "📄 View" if has_file else "☰ Details"
        with c6:
            if st.button(btn_label, key=f"row_{idx}", width="stretch"):
                st.session_state.selected_entry = idx if not is_sel else None
                st.session_state.confirm_delete = None
                st.rerun()

        if is_sel:
            with st.container(border=True):
                pc1, pc2 = st.columns([1, 2])
                with pc1:
                    st.markdown(f"<div class='sq-lbl'>Entry #{idx} · {label_text}</div>", unsafe_allow_html=True)
                    if row.get("Notes") and str(row["Notes"]).strip():
                        st.markdown(f"<div style='padding:10px 12px;background:#EDE8D8;border:1.5px solid #D8CCB0;border-radius:10px;font-size:.88rem;color:#5E4B3B;margin-bottom:8px'><b>Note:</b> {row['Notes']}</div>", unsafe_allow_html=True)
                    if isinstance(row.get("Custom Splits"), dict):
                        splits_str = " · ".join([f"{k}: {v}%" for k, v in row['Custom Splits'].items()])
                        st.markdown(f"<div style='padding:8px 12px;background:#E0EFED;border:1.5px solid #99ABA6;border-radius:10px;font-size:.82rem;color:#2D5A54;margin-bottom:8px'><b>Custom split:</b> {splits_str}</div>", unsafe_allow_html=True)
                    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)
                    if st.session_state.confirm_delete == idx:
                        st.warning(f"**Delete \"{label_text}\"?** This can't be undone.")
                        yes_col, no_col = st.columns(2)
                        with yes_col:
                            if st.button("✅ Yes, delete", key=f"confirm_yes_{idx}", width="stretch"):                        
                                st.session_state.ledger = st.session_state.ledger.drop(
                                    st.session_state.ledger.index[idx]).reset_index(drop=True)
                                st.session_state.selected_entry = None
                                st.session_state.confirm_delete = None
                                st.rerun()
                        with no_col:
                            if st.button("✖ Cancel", key=f"confirm_no_{idx}", width="stretch"):
                                st.session_state.confirm_delete = None
                                st.rerun()
                    else:
                        if st.button("🗑️ Delete entry", key=f"del_{idx}", width="stretch"):
                            st.session_state.confirm_delete = idx
                            st.rerun()
                with pc2:
                    if has_file:
                        st.markdown(engine.display_pdf(row['File_Object']), unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='padding:20px;background:#EDE8D8;border:1.5px solid #D8CCB0;border-radius:12px;color:#99ABA6;font-size:.88rem;text-align:center'>📎 No receipt attached to this entry.</div>", unsafe_allow_html=True)

        st.markdown("<hr style='margin:0;border-color:#D8CCB0'>", unsafe_allow_html=True)