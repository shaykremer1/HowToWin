import os
import pandas as pd
import streamlit as st
import psycopg2

st.set_page_config(page_title="איך לנצח - MVP", layout="centered")

# ---------- DB ----------
def get_conn():
    # אופציה א: לשים פה ידנית
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5433"),
        dbname=os.getenv("PGDATABASE", "Basketball"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "331754461"),
    )

def run_query(sql: str, params=None) -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)

# ---------- SQL: recommendation with fallback ----------
RECO_SQL = """
WITH input AS (
  SELECT ARRAY(SELECT x FROM unnest(ARRAY[%s,%s,%s,%s,%s]) x ORDER BY x) AS in_arr
),
bkeys AS (
  SELECT DISTINCT
    b_key,
    string_to_array(b_key, '-')::int[] AS b_arr
  FROM matchup_summary
),
scored AS (
  SELECT
    bk.b_key,
    (SELECT COUNT(*)
     FROM unnest(bk.b_arr) x
     JOIN unnest(i.in_arr) y ON x = y
    ) AS overlap,
    (SELECT SUM(total_seconds) FROM matchup_summary ms WHERE ms.b_key = bk.b_key) AS seconds_total
  FROM bkeys bk
  CROSS JOIN input i
),
chosen AS (
  -- בוחר את הכי דומה: קודם overlap (5->0), ואז הכי הרבה זמן דאטה
  SELECT b_key, overlap, seconds_total
  FROM scored
  ORDER BY overlap DESC, seconds_total DESC
  LIMIT 1
),
filtered AS (
  SELECT
    ms.*,
    c.overlap AS chosen_overlap
  FROM matchup_summary ms
  JOIN chosen c ON ms.b_key = c.b_key
  WHERE ms.total_seconds >= %s
),
greens AS (
  SELECT 'GREEN' AS flag, b_key, a_key, total_seconds, total_diff, diff_per_min, chosen_overlap
  FROM filtered
  ORDER BY diff_per_min DESC
  LIMIT 3
),
reds AS (
  SELECT 'RED' AS flag, b_key, a_key, total_seconds, total_diff, diff_per_min, chosen_overlap
  FROM filtered
  ORDER BY diff_per_min ASC
  LIMIT 1
)
SELECT * FROM greens
UNION ALL
SELECT * FROM reds
ORDER BY flag DESC, diff_per_min DESC;
"""

# ---------- UI ----------
st.title("איך לנצח — MVP (Matchup Engine)")

st.write("מכניסים חמישייה שלהם (מספרי שחקנים) → מקבלים 3 ירוק + 1 אדום. אם אין חמישייה זהה, המערכת מתעלמת מהשחקנים שלא היו ומוצאת את הכי דומה (4/5, 3/5...).")

col1, col2, col3, col4, col5 = st.columns(5)
with col1: b1 = st.number_input("B1", min_value=0, step=1, value=6)
with col2: b2 = st.number_input("B2", min_value=0, step=1, value=7)
with col3: b3 = st.number_input("B3", min_value=0, step=1, value=10)
with col4: b4 = st.number_input("B4", min_value=0, step=1, value=55)
with col5: b5 = st.number_input("B5", min_value=0, step=1, value=77)

min_seconds = st.slider("סף מינימום זמן (שניות)", min_value=0, max_value=300, value=90, step=15)

if st.button("תן המלצה"):
    # ולידציה קצרה: שלא יהיו כפולים/אפסים
    vals = [int(b1), int(b2), int(b3), int(b4), int(b5)]
    vals = [v for v in vals if v != 0]
    if len(vals) != 5:
        st.error("צריך 5 מספרים (לא 0).")
        st.stop()
    if len(set(vals)) != 5:
        st.error("יש כפילויות בחמישייה. תתקן.")
        st.stop()

    df = run_query(RECO_SQL, params=(vals[0], vals[1], vals[2], vals[3], vals[4], int(min_seconds)))

    if df.empty:
        st.warning("אין מספיק דאטה שעובר את הסף שבחרת. נסה להוריד את הסף.")
        st.stop()

    chosen_bkey = df["b_key"].iloc[0]
    overlap = int(df["chosen_overlap"].iloc[0])

    if overlap < 5:
        st.warning(f"⚠ אין חמישייה זהה בדאטה. השתמשתי בחמישייה הכי דומה: {chosen_bkey} (חפיפה {overlap}/5).")
    else:
        st.success(f"✅ נמצאה חמישייה זהה בדאטה: {chosen_bkey}")

    # הצגה יפה
    show = df[["flag", "a_key", "total_seconds", "total_diff", "diff_per_min"]].copy()
    show["minutes"] = (show["total_seconds"] / 60).round(2)
    show = show.drop(columns=["total_seconds"])
    show = show.rename(columns={
        "a_key": "Our Lineup (A_KEY)",
        "total_diff": "Diff",
        "diff_per_min": "Diff / min",
        "minutes": "Minutes"
    })

    st.dataframe(show, use_container_width=True)

    # טקסט לוואטסאפ/מאמן
    greens = show[show["flag"] == "GREEN"].head(3)
    reds = show[show["flag"] == "RED"].head(1)

    msg_lines = []
    msg_lines.append(f"מול {chosen_bkey} (חפיפה {overlap}/5):")
    msg_lines.append("🟢 מומלץ:")
    for _, r in greens.iterrows():
        msg_lines.append(f"- {r['Our Lineup (A_KEY)']} | {r['Minutes']} דק׳ | {int(r['Diff'])} | {r['Diff / min']:.2f}/דק")
    if len(reds) > 0:
        r = reds.iloc[0]
        msg_lines.append("🔴 לא מומלץ:")
        msg_lines.append(f"- {r['Our Lineup (A_KEY)']} | {r['Minutes']} דק׳ | {int(r['Diff'])} | {r['Diff / min']:.2f}/דק")

    st.text_area("הודעה מוכנה לשליחה", "\n".join(msg_lines), height=200)
