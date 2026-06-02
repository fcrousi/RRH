import streamlit as st
import pandas as pd
import json
import gspread
import time
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
import bcrypt
import secrets
import hashlib

# =========================
# CONFIG
# =========================
st.set_page_config(
    page_title="CV IAs CMUDE",
    page_icon="🌋",
    layout="wide"
)

MAX_ROWS_DEFAULT = 10
MAX_ROWS_SPEAKING = 5
CURRENT_YEAR = datetime.utcnow().year
SELECT = "— Selecciona —"

FORMATOS = ["BP", "WSDC", "AP", "Otro"]
SI_NO = ["Sí", "No"]
RONDAS_JUEZA = ["Break", "Octavos", "Cuartos", "Semis", "Final", "Final Novata"]
RONDAS_ORADORA = ["Octavos", "Cuartos", "Semis", "Final", "Campeón"]
ROLES_JUEZA = ["Principal", "Panelista"]
ROLES_ADJCORE = ["Jefe", "Vice-Jefe", "Miembro", "Aprendiz"]

TIPOS_LOGRO = ["Debatiente", "Jueza", "Equipo de adjudicación"]

WS_SPEAKING = "speaking"
WS_JUDGING = "judging"
WS_ADJCORE = "adjcore"

USERS_SHEET = "users"
TOKENS_SHEET = "auth_tokens"
TOKEN_TTL_MINUTES = 30

FIELD_LABELS = {
    "tournament_pick": "Torneo",
    "tournament_other": "Torneo (si elegiste OTRO)",
    "year": "Año",
    "name_on_tab": "Nombre en tab",
    "tab_link": "Link de tab",
    "format": "Formato",
    "role": "Rol",
    "break": "¿Hubo break?",
    "furthest_round_judged": "Ronda más lejana juzgada",
    "role_in_round": "Rol en esa ronda",
    "team_name": "Nombre del equipo",
    "furthest_round_spoken": "Ronda más lejana debatida",
    "speaker_rank": "Ranking de oradora",
    "team_rank": "Ranking de equipo",
}

def pretty_field_name(field_key: str) -> str:
    return FIELD_LABELS.get(field_key, field_key)

# =========================
# TIERS POR RUBRO
# tier_detail puede ser: A, CE, B, DE, C, D
# tier_guess SIEMPRE será: A, B, C o D
# =========================
ADJCORE_TOURNAMENTS = {
    "A": [
        "CMUDE",
        "MED",
        "WUDC",
        "EUDC",
        "NAUDC",
        "WSDC",
    ],
    "CE": [
        "BP Complu",
        "Comunícate",
    ],
    "B": [
        "Round Robin Hispanohablante",
        "Round Robin Novato",
        "TODI",
        "TRD",
        "CHIDO",
        "BP UAM",
        "BP URJC",
        "TMD",
        "UNED",
        "TIPIS IV",
        "Rosario Open",
        "CMUDE Masters",
        "Princeton",
        "Cambridge",
        "Oxford",
        "Doxbridge",
    ],
    "DE": [
        "GAD UAB",
        "Interpoli",
    ],
    "C": [
        "MUMUDI",
        "ADMM Virtual",
        "CNDI / END (Nacional de Perú)",
        "TNDE (Nacional de Colombia)",
        "CND (Nacional de México)",
        "CNADE (Nacional de Panamá)",
        "PUCP Open",
        "UNIANDES IV",
    ],
    "D": [
        "CNDV (Nacional de Venezuela)",
        "TNDE (Nacional de Ecuador)",
        "Copa Jaguar (Nacional de Guatemala)",
        "PIRI IV",
        "Copa Borregos",
        "ToEx",
        "TDU",
        "Torneo de Verano",
        "Torneo de Otoño",
        "Torneo de Invierno",
        "DebateUP",
        "Torneo de Primavera",
        "Torneo de Navidad",
        "TODI Masters",
        "PRESTIGE OPEN",
        "PRE-CMUDE UNIANDES",
        "Torneo Verano de Debate",
    ],
    "E": [
        "Toniichan",
        "Mi Primer BP",
        "Torneo de las Estrellas Nacientes",
        "Torneo Novato",
        "TODISC",
        "COIN",
        "Copa Raptor",
        "PreCMUDE UAM",
        "DEBATOON",
        "CIMET",
        "Abya Yala",
        "BP Torres",
    ],
}

JUDGING_TOURNAMENTS = {
    "A": [
        "CMUDE",
        "WUDC",
        "WSDC",
        "Princeton",
        "Cambridge",
        "Oxford",
        "Doxbridge",
    ],
    "B": [
        "Round Robin Hispanohablante",
        "Round Robin Novato",
        "TODI",
        "TRD",
        "CHIDO",
        "BP UAM",
        "BP URJC",
        "TMD",
        "UNED",
        "TIPIS IV",
        "Rosario Open",
        "MED",
        "EUDC",
        "NAUDC",
    ],
    "DE": [
        "Interpoli",
        "Elías Ahuja",
    ],
    "C": [
        "TNDE (Nacional de Colombia)",
        "CND (Nacional de México)",
        "CNADE (Nacional de Panamá)",
        "CNDI / END (Nacional de Perú)",
        "UNIANDES IV",
        "BP Complutense",
        "BP Comunicate",
    ],
    "D": [
        "TNDE (Nacional de Ecuador)",
        "Copa Jaguar (Nacional de Guatemala)",
        "CNDV (Nacional de Venezuela)",
        "Torneo de Verano",
        "Torneo de Otoño",
        "Torneo de Invierno",
        "TDU",
        "Torneo de Primavera",
        "Torneo de Navidad",
        "MUMUDI",
        "ADMM Virtual",
        "CMUDE Masters",
        "PUCP Open",
        "Debate UP",
        "Zimbabwe WSDC",
        "PRE-CMUDE UNIANDES",
        "ADMM Presencial",
        "PUCP IV",
        "PIRI IV",
        "CIMET Presencial",
        "BP Granada",
        "BP GAD UAB",
        "BP La Regenta",
        "PRESTIGE OPEN",
        "Copa Borregxs",
        "Yale IV",
        "TONO",
    ],
    "E": [
        "Toniichan",
        "Torneo de las Estrellas Nacientes",
        "Mi Primer BP",
        "TODISC",
        "COIN",
        "Copa Raptor",
        "DEBATOON",
        "Abya Yala",
        "BP Torres",
    ],
}

SPEAKING_TOURNAMENTS = {
    "A": [
        "CMUDE",
        "WUDC",
    ],
    "B": [
        "Round Robin Hispanohablante",
        "TODI",
        "TRD",
        "BP UAM",
        "BP URJC",
        "CHIDO",
        "TMD",
        "UNED",
        "TIPIS IV",
        "Rosario Open",
        "Princeton",
        "Cambridge",
        "Oxford",
        "Doxbridge",
    ],
    "C": [
        "MED",
        "WSDC",
        "EUDC",
        "NAUDC",
        "CMUDE Masters",
        "Copenhaguen",
        "Comunícate",
        "UNIANDES IV",
    ],
    "D": [
        "Torneo de Verano",
        "Torneo de Otoño",
        "Torneo de Invierno",
        "Torneo de Primavera",
        "Torneo de Navidad",
        "MUMUDI",
        "ADMM Virtual",
        "TNDE (Nacional de Ecuador)",
        "Copa Jaguar (Nacional de Guatemala)",
        "CNDV (Nacional de Venezuela)",
        "Regenta",
        "Granada",
        "Interpoli",
        "Elías Ahuja",
        "GAD UAB",
        "TDU",
        "PUCP Open",
        "CNDI / END (Nacional de Perú)",
        "CND (Nacional de México)",
        "TNDE (Nacional de Colombia)",
        "PreCMUDE UAM",
        "PRE-CMUDE UNIANDES",
        "CNADE (Nacional de Panamá)",
        "CIMET Presencial",
        "PRESTIGE OPEN",
        "Pre-WUDC Western IV",
    ],
    "E": [
        "Toniichan",
        "Mi Primer BP",
        "Torneo Novato",
        "Torneo de las Estrellas Nacientes",
        "TODISC",
        "COIN",
        "Copa Raptor",
        "DEBATOON",
        "Abya Yala",
        "BP Torres",
    ],
}

TOURNAMENT_OTHER = "OTRO (no está en la lista)"

FORMAT_OPTIONS = [SELECT] + FORMATOS
YES_NO_OPTIONS = [SELECT] + SI_NO
ROUND_OPTIONS = [SELECT] + RONDAS_JUEZA
ROUND_SPK_OPTIONS = [SELECT] + RONDAS_ORADORA
JUDGE_ROLE_OPTIONS = [SELECT] + ROLES_JUEZA
ADJCORE_ROLE_OPTIONS = [SELECT] + ROLES_ADJCORE

# =========================
# COLUMNAS
# =========================
ADJCORE_SAVE_COLS = [
    "user_id", "submitted_utc", "tournament", "tier_guess", "tier_detail", "tier_is_guess",
    "year", "name_on_tab", "tab_link", "format", "role"
]

JUDGING_SAVE_COLS = [
    "user_id", "submitted_utc", "tournament", "tier_guess", "tier_detail", "tier_is_guess",
    "year", "name_on_tab", "tab_link", "format", "break",
    "furthest_round_judged", "role_in_round"
]

SPEAKING_SAVE_COLS = [
    "user_id", "submitted_utc", "tournament", "tier_guess", "tier_detail", "tier_is_guess",
    "year", "name_on_tab", "team_name", "tab_link", "format",
    "furthest_round_spoken", "speaker_rank", "team_rank"
]

ADJCORE_EDIT_COLS = ["tournament_pick", "tournament_other", "year", "name_on_tab", "tab_link", "format", "role"]
JUDGING_EDIT_COLS = [
    "tournament_pick", "tournament_other", "year", "name_on_tab", "tab_link", "format", "break",
    "furthest_round_judged", "role_in_round"
]
SPEAKING_EDIT_COLS = [
    "tournament_pick", "tournament_other", "year", "name_on_tab", "team_name", "tab_link", "format",
    "furthest_round_spoken", "speaker_rank", "team_rank"
]

# =========================
# ADMIN helpers
# =========================
def get_admin_emails() -> set[str]:
    raw = str(st.secrets.get("ADMIN_EMAILS", "")).strip()
    if not raw:
        return set()
    return {e.strip().lower() for e in raw.split(",") if e.strip()}

def is_admin(email: str) -> bool:
    return (email or "").strip().lower() in get_admin_emails()

# =========================
# GOOGLE SHEETS (robusto)
# =========================
@st.cache_resource
def get_spreadsheet():
    sa = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(sa, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(st.secrets["SHEET_ID"])

def _is_retryable_gspread_error(e: Exception) -> bool:
    msg = str(e)
    return ("[429]" in msg) or ("[503]" in msg) or ("Quota exceeded" in msg) or ("service is currently unavailable" in msg.lower())

def gspread_call(fn, tries: int = 5, base_sleep: float = 0.6):
    last = None
    for k in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            if not _is_retryable_gspread_error(e):
                raise
            time.sleep(base_sleep * (2 ** k))
    raise last

@st.cache_resource
def get_ws(title: str):
    sh = get_spreadsheet()
    return gspread_call(lambda: sh.worksheet(title))

def ensure_headers(ws, headers: list[str]):
    key = f"headers_ok__{ws.title}"
    if st.session_state.get(key, False):
        return

    first_row = gspread_call(lambda: ws.row_values(1))
    if len(first_row) == 0:
        gspread_call(lambda: ws.insert_row(headers, 1))
        st.session_state[key] = True
        return

    if [h.strip() for h in first_row] != headers:
        raise ValueError(
            f"Los encabezados de '{ws.title}' no coinciden.\n"
            f"Esperado: {headers}\n"
            f"Encontrado: {first_row}\n"
            f"Solución: ajusta la fila 1 o crea una pestaña nueva con esos encabezados."
        )

    st.session_state[key] = True

def load_user_df(ws, user_id: str) -> pd.DataFrame:
    records = gspread_call(lambda: ws.get_all_records())
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if "user_id" not in df.columns:
        return pd.DataFrame()
    df = df[df["user_id"].astype(str).str.strip().str.lower() == user_id.strip().lower()].copy()
    df.reset_index(drop=True, inplace=True)
    return df

def delete_user_rows(ws, user_id: str):
    all_values = gspread_call(lambda: ws.get_all_values())
    if not all_values:
        return
    header = all_values[0]
    if "user_id" not in header:
        return
    user_col = header.index("user_id")

    rows_to_delete = []
    for i, row in enumerate(all_values[1:], start=2):
        if len(row) > user_col and str(row[user_col]).strip().lower() == user_id.strip().lower():
            rows_to_delete.append(i)

    for r in reversed(rows_to_delete):
        gspread_call(lambda r=r: ws.delete_rows(r))

def dedupe_user_rows(ws, user_id: str, key_cols: list[str]):
    all_values = gspread_call(lambda: ws.get_all_values())
    if not all_values:
        return

    header = all_values[0]
    if "user_id" not in header:
        return

    idx_user = header.index("user_id")
    idxs = []
    for k in key_cols:
        if k not in header:
            return
        idxs.append(header.index(k))

    seen = set()
    rows_to_delete = []

    for i, row in enumerate(all_values[1:], start=2):
        if len(row) <= idx_user:
            continue
        if str(row[idx_user]).strip().lower() != user_id.strip().lower():
            continue

        key = tuple((str(row[j]).strip().lower() if len(row) > j else "") for j in idxs)
        if key in seen:
            rows_to_delete.append(i)
        else:
            seen.add(key)

    for r in reversed(rows_to_delete):
        gspread_call(lambda r=r: ws.delete_rows(r))

def append_rows(ws, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = df.astype(object).where(pd.notnull(df), "").values.tolist()
    gspread_call(lambda: ws.append_rows(rows, value_input_option="USER_ENTERED"))
    return len(rows)

def with_save_lock(user_id: str, fn, ttl_seconds: int = 12):
    user = (user_id or "").strip().lower()
    lock_key = f"is_saving__{user}"
    ts_key = f"is_saving_ts__{user}"

    now = datetime.utcnow().timestamp()
    locked = bool(st.session_state.get(lock_key, False))
    ts = float(st.session_state.get(ts_key, 0.0) or 0.0)

    if locked and (now - ts) > ttl_seconds:
        st.session_state[lock_key] = False
        st.session_state[ts_key] = 0.0
        locked = False

    if locked:
        st.warning("Ya se está guardando. Espera un momento y vuelve a intentar.")
        return None

    st.session_state[lock_key] = True
    st.session_state[ts_key] = now
    try:
        return fn()
    finally:
        st.session_state[lock_key] = False
        st.session_state[ts_key] = 0.0

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def utc_now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")

# Ya no usamos envío automático de correos.
# La recuperación se hace con códigos generados desde el panel admin.

def ensure_users_headers(users_ws):
    ensure_headers(users_ws, ["email", "password_hash", "created_utc"])

def ensure_tokens_headers(tokens_ws):
    ensure_headers(tokens_ws, ["email", "token_hash", "purpose", "expires_utc", "used", "created_utc"])

def find_user_row(users_ws, email: str) -> dict | None:
    email_l = email.strip().lower()
    records = gspread_call(lambda: users_ws.get_all_records())
    for r in records:
        if str(r.get("email", "")).strip().lower() == email_l:
            return r
    return None

def create_user(users_ws, email: str, password: str):
    email = email.strip().lower()
    if find_user_row(users_ws, email):
        raise ValueError("Ese correo ya está registrado.")
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    gspread_call(lambda: users_ws.append_row([email, pw_hash, utc_now_iso()], value_input_option="USER_ENTERED"))

def verify_login(users_ws, email: str, password: str) -> bool:
    u = find_user_row(users_ws, email)
    if not u:
        return False
    stored = str(u.get("password_hash", "")).strip()
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except Exception:
        return False

def issue_token(tokens_ws, email: str, purpose: str) -> str:
    raw = secrets.token_urlsafe(24)
    token_hash = sha256_hex(raw)
    expires = datetime.utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES)
    expires_iso = expires.isoformat(timespec="seconds")

    gspread_call(lambda: tokens_ws.append_row(
        [email.strip().lower(), token_hash, purpose, expires_iso, "No", utc_now_iso()],
        value_input_option="USER_ENTERED"
    ))
    return raw

def consume_token(tokens_ws, email: str, raw_token: str, purpose: str) -> bool:
    email_l = email.strip().lower()
    token_hash = sha256_hex(raw_token)

    rows = gspread_call(lambda: tokens_ws.get_all_values())
    if not rows or len(rows) < 2:
        return False

    header = rows[0]
    idx_email = header.index("email")
    idx_hash = header.index("token_hash")
    idx_purpose = header.index("purpose")
    idx_expires = header.index("expires_utc")
    idx_used = header.index("used")

    now = datetime.utcnow()

    for i in range(len(rows) - 1, 0, -1):
        r = rows[i]
        if len(r) <= max(idx_used, idx_expires, idx_purpose, idx_hash, idx_email):
            continue
        if r[idx_email].strip().lower() != email_l:
            continue
        if r[idx_hash].strip() != token_hash:
            continue
        if r[idx_purpose].strip() != purpose:
            continue
        if r[idx_used].strip() == "Sí":
            return False

        try:
            exp = datetime.fromisoformat(r[idx_expires].strip())
        except Exception:
            return False

        if now > exp:
            return False

        row_number = i + 1
        used_cell = gspread.utils.rowcol_to_a1(row_number, idx_used + 1)
        gspread_call(lambda: tokens_ws.update_acell(used_cell, "Sí"))
        return True

    return False

def set_new_password(users_ws, email: str, new_password: str):
    email_l = email.strip().lower()
    all_vals = gspread_call(lambda: users_ws.get_all_values())
    if not all_vals or len(all_vals) < 2:
        raise ValueError("No existe el usuario.")
    header = all_vals[0]
    idx_email = header.index("email")
    idx_hash = header.index("password_hash")

    pw_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    for i in range(1, len(all_vals)):
        r = all_vals[i]
        if len(r) > idx_email and r[idx_email].strip().lower() == email_l:
            row_number = i + 1
            hash_cell = gspread.utils.rowcol_to_a1(row_number, idx_hash + 1)
            gspread_call(lambda: users_ws.update_acell(hash_cell, pw_hash))
            return

    raise ValueError("No existe el usuario.")


# =========================
# HELPERS: LÍMITES
# =========================
def max_rows_for_type(typ: str) -> int:
    if typ == "speaking":
        return MAX_ROWS_SPEAKING
    return MAX_ROWS_DEFAULT

# =========================
# HELPERS: TIERS
# =========================
def rubro_to_internal(typ_ui: str) -> str:
    if typ_ui == "Debatiente":
        return "speaking"
    if typ_ui == "Jueza":
        return "judging"
    if typ_ui == "Equipo de adjudicación":
        return "adjcore"
    return ""

def internal_to_rubro(typ: str) -> str:
    if typ == "speaking":
        return "Debatiente"
    if typ == "judging":
        return "Jueza"
    if typ == "adjcore":
        return "Equipo de adjudicación"
    return ""

def get_tier_map(typ: str) -> dict:
    if typ == "adjcore":
        return ADJCORE_TOURNAMENTS
    if typ == "judging":
        return JUDGING_TOURNAMENTS
    if typ == "speaking":
        return SPEAKING_TOURNAMENTS
    return {}

def get_tournament_list_for_type(typ: str) -> list[str]:
    tier_map = get_tier_map(typ)
    seen = []

    for tier_detail in ["A", "CE", "B", "DE", "C", "D", "E"]:
        for t in tier_map.get(tier_detail, []):
            if t not in seen:
                seen.append(t)

    return sorted(seen, key=lambda x: x.lower())

def get_tournament_options_for_type(typ: str) -> list[str]:
    if typ == "":
        return [SELECT, TOURNAMENT_OTHER]
    return [SELECT] + [TOURNAMENT_OTHER] + get_tournament_list_for_type(typ) 

def collapse_tier_detail_to_guess(tier_detail: str) -> str:
    tier_detail = str(tier_detail).strip().upper()

    if tier_detail == "A":
        return "A"
    if tier_detail == "B":
        return "B"
    if tier_detail in ["C", "CE"]:
        return "C"
    if tier_detail in ["D", "DE"]:
        return "D"
    if tier_detail == "E":
        return "E"
    return "F"

def classify_tournament(typ: str, tournament_name: str) -> tuple[str, str, str]:
    t = str(tournament_name).strip()
    if t == "":
        return "", "", ""

    tier_map = get_tier_map(typ)
    for tier_detail, items in tier_map.items():
        if t in items:
            return tier_detail, collapse_tier_detail_to_guess(tier_detail), "No"

    return "F", "F", "Sí"

# =========================
# HELPERS: DATAFRAMES
# =========================
def blank_row(cols: list[str]) -> dict:
    row = {c: "" for c in cols}
    if "tournament_pick" in cols:
        row["tournament_pick"] = SELECT
    if "format" in cols:
        row["format"] = SELECT
    if "break" in cols:
        row["break"] = SELECT
    if "furthest_round_judged" in cols:
        row["furthest_round_judged"] = SELECT
    if "role_in_round" in cols:
        row["role_in_round"] = SELECT
    if "furthest_round_spoken" in cols:
        row["furthest_round_spoken"] = SELECT
    if "role" in cols:
        row["role"] = SELECT
    return row

def ensure_df(df_key: str, cols: list[str]):
    if df_key not in st.session_state or not isinstance(st.session_state[df_key], pd.DataFrame):
        st.session_state[df_key] = pd.DataFrame(columns=cols)
    for c in cols:
        if c not in st.session_state[df_key].columns:
            st.session_state[df_key][c] = ""
    st.session_state[df_key] = st.session_state[df_key][cols].copy()

def editor_row_used(r: pd.Series) -> bool:
    for v in r.values:
        if pd.isna(v):
            continue
        s = str(v).strip()
        if s != "" and s != SELECT:
            return True
    return False

def validate_other_names(df: pd.DataFrame) -> list[int]:
    bad = []
    for i, r in df.iterrows():
        if not editor_row_used(r):
            continue
        pick = str(r.get("tournament_pick", "")).strip()
        other = str(r.get("tournament_other", "")).strip()
        if pick == TOURNAMENT_OTHER and other == "":
            bad.append(i)
    return bad

def tournament_final(r: pd.Series) -> str:
    pick = str(r.get("tournament_pick", "")).strip()
    other = str(r.get("tournament_other", "")).strip()
    if pick == SELECT:
        return ""
    if pick == TOURNAMENT_OTHER:
        return other.strip()
    return pick

def tournament_to_pick_other(typ: str, t: str):
    t = (t or "").strip()
    if t == "":
        return (SELECT, "")
    if t in get_tournament_list_for_type(typ):
        return (t, "")
    return (TOURNAMENT_OTHER, t)

def to_editor_df(saved: pd.DataFrame, edit_cols: list[str], typ: str) -> pd.DataFrame:
    if saved.empty:
        return pd.DataFrame(columns=edit_cols)

    out_rows = []
    for _, r in saved.iterrows():
        row = blank_row(edit_cols)
        pick, other = tournament_to_pick_other(typ, str(r.get("tournament", "")))
        row["tournament_pick"] = pick
        row["tournament_other"] = other

        for c in edit_cols:
            if c in ["tournament_pick", "tournament_other"]:
                continue
            if c in r.index:
                row[c] = r[c]
        out_rows.append(row)

    out = pd.DataFrame(out_rows, columns=edit_cols)
    return out.iloc[:max_rows_for_type(typ)].copy()

def pretty_tournament(r: pd.Series) -> str:
    pick = str(r.get("tournament_pick", "")).strip()
    other = str(r.get("tournament_other", "")).strip()
    if pick == TOURNAMENT_OTHER:
        return other
    return pick

def make_duplicate_key(row_like) -> tuple[str, str]:
    torneo = ""
    if isinstance(row_like, pd.Series):
        torneo = tournament_final(row_like)
        year = str(row_like.get("year", "")).strip()
    else:
        torneo = str(row_like.get("tournament", "")).strip()
        year = str(row_like.get("year", "")).strip()
    return torneo.strip().lower(), year.strip()

def find_duplicate_keys_in_editor_df(df: pd.DataFrame) -> list[tuple[str, str]]:
    temp = df.copy()
    temp = temp[temp.apply(editor_row_used, axis=1)].copy()
    if temp.empty:
        return []

    seen = set()
    duplicates = []

    for _, r in temp.iterrows():
        key = make_duplicate_key(r)
        if key[0] == "" or key[1] == "":
            continue
        if key in seen and key not in duplicates:
            duplicates.append(key)
        seen.add(key)

    return duplicates

def validate_no_duplicates_in_editor_df(df: pd.DataFrame, rubro_nombre: str):
    duplicates = find_duplicate_keys_in_editor_df(df)
    if duplicates:
        formatted = [f"{torneo.upper()} ({year})" for torneo, year in duplicates]
        raise ValueError(
            f"No puedes repetir el mismo logro en {rubro_nombre}. "
            f"Ya existe un logro con el mismo torneo y año: {', '.join(formatted)}."
        )

def clean_build_save_df(edit_df: pd.DataFrame, user_id: str, save_cols: list[str], required_cols: list[str], typ: str, rubro_nombre: str) -> pd.DataFrame:
    df = edit_df.copy()
    df = df[df.apply(editor_row_used, axis=1)].copy()
    df.reset_index(drop=True, inplace=True)

    if df.empty:
        return pd.DataFrame(columns=save_cols)

    validate_no_duplicates_in_editor_df(df, rubro_nombre)

    df["tournament"] = df.apply(tournament_final, axis=1)

    tier_details = []
    tier_guesses = []
    tier_is_guess_vals = []

    for _, r in df.iterrows():
        td, tg, tig = classify_tournament(typ, r["tournament"])
        tier_details.append(td)
        tier_guesses.append(tg)
        tier_is_guess_vals.append(tig)

    df["tier_detail"] = tier_details
    df["tier_guess"] = tier_guesses
    df["tier_is_guess"] = tier_is_guess_vals

    for c in required_cols:
        if c == "tournament":
            bad = df["tournament"].astype(str).str.strip() == ""
        else:
            bad = df[c].isna() | (df[c].astype(str).str.strip() == "") | (df[c].astype(str).str.strip() == SELECT)
        if bad.any():
            raise ValueError(f"Faltan campos obligatorios en alguna fila: '{pretty_field_name(c)}'.")

    if "year" in df.columns:
        bad_rows = []
        for i, v in enumerate(df["year"].tolist()):
            try:
                y = int(v)
                if y < 1990 or y > CURRENT_YEAR + 1:
                    bad_rows.append(i)
            except:
                bad_rows.append(i)
        if bad_rows:
            raise ValueError("Año inválido en filas: " + ", ".join(str(i + 1) for i in bad_rows))

    submitted_utc = datetime.utcnow().isoformat(timespec="seconds")

    out_rows = []
    for _, r in df.iterrows():
        row = {c: "" for c in save_cols}
        row["user_id"] = user_id
        row["submitted_utc"] = submitted_utc
        row["tournament"] = r.get("tournament", "")
        row["tier_guess"] = r.get("tier_guess", "")
        row["tier_detail"] = r.get("tier_detail", "")
        row["tier_is_guess"] = r.get("tier_is_guess", "")
        for c in save_cols:
            if c in ["user_id", "submitted_utc", "tournament", "tier_guess", "tier_detail", "tier_is_guess"]:
                continue
            if c in r.index:
                row[c] = r[c]
        out_rows.append(row)

    return pd.DataFrame(out_rows, columns=save_cols)

def render_readonly_table(df: pd.DataFrame, cols: list[str], label_map: dict):
    if df.empty:
        st.info("Aún no tienes logros en esta sección.")
        return

    show = df.copy()
    show["tournament"] = show.apply(pretty_tournament, axis=1)

    display_cols = [c for c in cols if c not in ["tournament_pick", "tournament_other"]]
    display_cols = ["tournament"] + [c for c in display_cols if c != "tournament"]
    show = show[display_cols].copy()
    show.rename(columns=label_map, inplace=True)

    st.dataframe(show, use_container_width=True, hide_index=True)

def df_by_type_key(typ: str):
    if typ == "adjcore":
        return "adj_df", ADJCORE_EDIT_COLS
    if typ == "judging":
        return "jud_df", JUDGING_EDIT_COLS
    if typ == "speaking":
        return "spk_df", SPEAKING_EDIT_COLS
    raise ValueError("Tipo inválido.")

# =========================
# VALIDACIONES
# =========================
def validate_single_entry_required_fields(d: dict, typ: str):
    comunes = ["tournament_pick", "year", "name_on_tab", "tab_link", "format"]
    for c in comunes:
        v = str(d.get(c, "")).strip()
        if c == "tournament_pick":
            if v == "" or v == SELECT:
                raise ValueError(f"Falta: {pretty_field_name(c)}.")
        else:
            if v == "" or v == SELECT:
                raise ValueError(f"Falta: {pretty_field_name(c)}.")

    if str(d.get("tournament_pick", SELECT)).strip() == TOURNAMENT_OTHER and str(d.get("tournament_other", "")).strip() == "":
        raise ValueError(f"Falta: {pretty_field_name('tournament_other')}.")

    if typ == "adjcore":
        if str(d.get("role", SELECT)).strip() == SELECT:
            raise ValueError(f"Falta: {pretty_field_name('role')}.")
    
    elif typ == "judging":
        break_val = str(d.get("break", SELECT)).strip()

        if break_val == SELECT:
            raise ValueError(f"Falta: {pretty_field_name('break')}.")

        if break_val == "Sí":
            if str(d.get("furthest_round_judged", SELECT)).strip() == SELECT:
                raise ValueError(f"Falta: {pretty_field_name('furthest_round_judged')}.")
            if str(d.get("role_in_round", SELECT)).strip() == SELECT:
                raise ValueError(f"Falta: {pretty_field_name('role_in_round')}.")
    
    elif typ == "speaking":
        extras = ["team_name", "furthest_round_spoken", "speaker_rank", "team_rank"]
        for c in extras:
            v = str(d.get(c, "")).strip()
            if v == "" or v == SELECT:
                raise ValueError(f"Falta: {pretty_field_name(c)}.")

def validate_duplicate_against_section(d: dict, typ: str, mode: str, edit_index: int | None = None):
    df_key, cols = df_by_type_key(typ)
    df = st.session_state[df_key].copy()

    row = blank_row(cols)
    for k in cols:
        if k in d:
            row[k] = d[k]

    new_key = make_duplicate_key(pd.Series(row))
    if new_key[0] == "" or new_key[1] == "":
        return

    for i, existing in df.iterrows():
        if mode == "edit" and edit_index is not None and i == edit_index:
            continue
        if make_duplicate_key(existing) == new_key:
            raise ValueError("No puedes repetir el mismo torneo y año dentro de la misma categoría.")

def validate_wizard(d: dict, mode: str, edit_index: int | None = None):
    typ = d.get("type", "")
    if typ not in ["speaking", "judging", "adjcore"]:
        raise ValueError("Elige una categoría de logro.")

    validate_single_entry_required_fields(d, typ)
    validate_duplicate_against_section(d, typ, mode=mode, edit_index=edit_index)

# =========================
# GUARDADO AUTOMÁTICO
# =========================
def guardar_cv_en_sheets(user_id: str):
    if len(st.session_state["adj_df"]) > max_rows_for_type("adjcore"):
        raise ValueError("No puedes tener más de 10 logros en equipo de adjudicación.")
    if len(st.session_state["jud_df"]) > max_rows_for_type("judging"):
        raise ValueError("No puedes tener más de 10 logros en jueza.")
    if len(st.session_state["spk_df"]) > max_rows_for_type("speaking"):
        raise ValueError("No puedes tener más de 5 logros en debatiente.")

    bad_adj = validate_other_names(st.session_state["adj_df"])
    bad_jud = validate_other_names(st.session_state["jud_df"])
    bad_spk = validate_other_names(st.session_state["spk_df"])

    if bad_adj or bad_jud or bad_spk:
        msgs = []
        if bad_adj:
            msgs.append("Equipo de adjudicación: falta el nombre del torneo (OTRO) en filas " + ", ".join(str(i + 1) for i in bad_adj))
        if bad_jud:
            msgs.append("Jueza: falta el nombre del torneo (OTRO) en filas " + ", ".join(str(i + 1) for i in bad_jud))
        if bad_spk:
            msgs.append("Debatiente: falta el nombre del torneo (OTRO) en filas " + ", ".join(str(i + 1) for i in bad_spk))
        raise ValueError("\n".join(msgs))

    adj_out = clean_build_save_df(
        st.session_state["adj_df"],
        user_id,
        ADJCORE_SAVE_COLS,
        required_cols=["tournament", "year", "name_on_tab", "tab_link", "format", "role"],
        typ="adjcore",
        rubro_nombre="Equipo de adjudicación"
    )

    jud_out = clean_build_save_df(
        st.session_state["jud_df"],
        user_id,
        JUDGING_SAVE_COLS,
        required_cols=["tournament", "year", "name_on_tab", "tab_link", "format", "break"],
        typ="judging",
        rubro_nombre="Jueza"
    )

    spk_out = clean_build_save_df(
        st.session_state["spk_df"],
        user_id,
        SPEAKING_SAVE_COLS,
        required_cols=["tournament", "year", "name_on_tab", "team_name", "tab_link", "format", "furthest_round_spoken", "speaker_rank", "team_rank"],
        typ="speaking",
        rubro_nombre="Debatiente"
    )

    ws_adj = get_ws(WS_ADJCORE)
    ws_jud = get_ws(WS_JUDGING)
    ws_spk = get_ws(WS_SPEAKING)

    ensure_headers(ws_adj, ADJCORE_SAVE_COLS)
    ensure_headers(ws_jud, JUDGING_SAVE_COLS)
    ensure_headers(ws_spk, SPEAKING_SAVE_COLS)

    # Borra primero lo del usuario para no acumular duplicados.
    delete_user_rows(ws_adj, user_id)
    delete_user_rows(ws_jud, user_id)
    delete_user_rows(ws_spk, user_id)

    # Luego inserta una sola versión del CV.
    n_adj = append_rows(ws_adj, adj_out)
    n_jud = append_rows(ws_jud, jud_out)
    n_spk = append_rows(ws_spk, spk_out)

    # Cinturón y tirantes: si hubo doble click o rerun raro, deduplica por usuario + torneo + año.
    dedupe_user_rows(ws_adj, user_id, key_cols=["tournament", "year"])
    dedupe_user_rows(ws_jud, user_id, key_cols=["tournament", "year"])
    dedupe_user_rows(ws_spk, user_id, key_cols=["tournament", "year"])

    return n_adj, n_jud, n_spk

# =========================
# MUTACIONES
# =========================
def push_row_from_wizard(d: dict, mode: str, edit_index: int | None = None):
    typ = d.get("type", "")
    df_key, cols = df_by_type_key(typ)
    max_rows = max_rows_for_type(typ)

    df = st.session_state[df_key].copy()

    row = blank_row(cols)
    for k in cols:
        if k in d:
            row[k] = d[k]

    if mode == "add":
        if len(df) >= max_rows:
            raise ValueError(f"Máximo {max_rows} logros en esta sección.")
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        if edit_index is None or edit_index < 0 or edit_index >= len(df):
            raise ValueError("Índice inválido para edición.")
        for k in cols:
            df.loc[edit_index, k] = row.get(k, "")

    rubro = internal_to_rubro(typ)
    validate_no_duplicates_in_editor_df(df, rubro)

    if len(df) > max_rows:
        raise ValueError(f"Máximo {max_rows} logros en esta sección.")

    st.session_state[df_key] = df.copy()

def make_item_label(df: pd.DataFrame, idx: int) -> str:
    if df.empty or idx < 0 or idx >= len(df):
        return ""
    r = df.iloc[idx]
    t = pretty_tournament(r)
    y = str(r.get("year", "")).strip() or "—"
    fmt = str(r.get("format", "")).strip() or "—"
    name = str(r.get("name_on_tab", "")).strip() or "—"
    return f"{idx+1}. {t} | {y} | {fmt} | {name}"

# =========================
# INIT STATE
# =========================
ensure_df("adj_df", ADJCORE_EDIT_COLS)
ensure_df("jud_df", JUDGING_EDIT_COLS)
ensure_df("spk_df", SPEAKING_EDIT_COLS)

if "page" not in st.session_state:
    st.session_state["page"] = "cv"
if "draft_add" not in st.session_state:
    st.session_state["draft_add"] = {}
if "draft_edit" not in st.session_state:
    st.session_state["draft_edit"] = {}
if "manage_type" not in st.session_state:
    st.session_state["manage_type"] = "speaking"
if "manage_index" not in st.session_state:
    st.session_state["manage_index"] = None

# estado de auth/admin
if "authed" not in st.session_state:
    st.session_state["authed"] = False
if "user_id" not in st.session_state:
    st.session_state["user_id"] = ""
if "admin_real_user" not in st.session_state:
    st.session_state["admin_real_user"] = ""
if "impersonating" not in st.session_state:
    st.session_state["impersonating"] = None
if "loaded" not in st.session_state:
    st.session_state["loaded"] = False
if "last_manual_reset_code" not in st.session_state:
    st.session_state["last_manual_reset_code"] = ""
if "last_manual_reset_email" not in st.session_state:
    st.session_state["last_manual_reset_email"] = ""

# =========================
# AUTH (signup + login + reset)
# =========================
def auth_screen():
    st.title("Ingreso")

    sh = get_spreadsheet()
    users_ws = get_ws(USERS_SHEET)
    tokens_ws = get_ws(TOKENS_SHEET)
    ensure_users_headers(users_ws)
    ensure_tokens_headers(tokens_ws)

    tab_login, tab_signup, tab_reset = st.tabs(["Entrar", "Crear cuenta", "Recuperar contraseña"])

    with tab_login:
        email = st.text_input("Correo", key="login_email")
        pw = st.text_input("Contraseña", type="password", key="login_pw")

        if st.button("Entrar", use_container_width=True):
            if email.strip() == "" or "@" not in email:
                st.error("Ingresa un correo válido.")
            elif pw.strip() == "":
                st.error("Ingresa tu contraseña.")
            else:
                ok = verify_login(users_ws, email, pw)
                if not ok:
                    st.error("Correo o contraseña incorrectos.")
                else:
                    u = email.strip().lower()
                    st.session_state["authed"] = True
                    st.session_state["user_id"] = u
                    st.session_state["admin_real_user"] = u
                    st.session_state["impersonating"] = None
                    st.session_state["loaded"] = False
                    st.session_state["page"] = "cv"
                    st.rerun()

    with tab_signup:
        email = st.text_input("Correo", key="su_email")
        pw1 = st.text_input("Contraseña", type="password", key="su_pw1")
        pw2 = st.text_input("Repite la contraseña", type="password", key="su_pw2")

        if st.button("Crear cuenta", use_container_width=True):
            if email.strip() == "" or "@" not in email:
                st.error("Ingresa un correo válido.")
            elif pw1.strip() == "" or len(pw1.strip()) < 8:
                st.error("La contraseña debe tener al menos 8 caracteres.")
            elif pw1 != pw2:
                st.error("Las contraseñas no coinciden.")
            else:
                try:
                    create_user(users_ws, email, pw1)
                    st.success("Cuenta creada ✅ Ya puedes entrar en la pestaña “Entrar”.")
                except Exception as e:
                    st.error(str(e))

    with tab_reset:
        st.info(
            "Si olvidaste tu contraseña, escríbele a Fernanda Crousillat para pedir "
            "un código de recuperación. Indica el correo con el que creaste tu cuenta. "
            "Cuando recibas el código, ingrésalo aquí para crear una nueva contraseña."
        )

        email = st.text_input("Correo registrado", key="rp_email")

        st.caption(
            "El código no se envía automáticamente por correo. "
            "Debe ser generado manualmente por un admin."
        )

        code = st.text_input("Código de recuperación entregado por admin", key="rp_code")
        new_pw1 = st.text_input("Nueva contraseña", type="password", key="rp_pw1")
        new_pw2 = st.text_input("Repite la nueva contraseña", type="password", key="rp_pw2")

        if st.button("Cambiar contraseña", use_container_width=True):
            if email.strip() == "" or "@" not in email:
                st.error("Ingresa el correo con el que creaste tu cuenta.")
            elif code.strip() == "":
                st.error("Ingresa el código de recuperación que te dio el admin.")
            elif new_pw1.strip() == "" or len(new_pw1.strip()) < 8:
                st.error("La nueva contraseña debe tener al menos 8 caracteres.")
            elif new_pw1 != new_pw2:
                st.error("Las contraseñas no coinciden.")
            else:
                ok = consume_token(tokens_ws, email, code.strip(), purpose="reset")
                if not ok:
                    st.error("Código inválido, expirado o ya usado.")
                else:
                    try:
                        set_new_password(users_ws, email, new_pw1)
                        st.success("Contraseña actualizada ✅ Ir a la pestaña 'Entrar'.")
                    except Exception as e:
                        st.error(str(e))


# =========================
# UI: LOGIN (gated)
# =========================
st.title("CV - Proceso de Juezas Financiadas de CMUDE")

if not st.session_state.get("authed", False):
    st.caption(
        "Crea una cuenta o ingresa. Si olvidas tu contraseña, pide un código de recuperación al equipo organizador."
    )
    auth_screen()
    st.stop()

user_id = (st.session_state.get("user_id", "") or "").strip().lower()

if not st.session_state.get("admin_real_user"):
    st.session_state["admin_real_user"] = user_id

if not user_id:
    st.session_state["authed"] = False
    auth_screen()
    st.stop()


# =========================
# SIDEBAR: sesión + admin impersonation
# =========================
with st.sidebar:
    st.header("Sesión")
    st.write(f"Conectado como: **{user_id}**")

    if st.session_state.get("impersonating"):
        st.warning(f"Modo admin: estás editando como **{st.session_state['impersonating']}**.")
        real = st.session_state.get("admin_real_user", "")
        if real:
            st.caption(f"Usuario real: {real}")

    # Admin panel (solo si user actual o user real es admin)
    if is_admin(user_id) or is_admin(st.session_state.get("admin_real_user", "")):
        st.divider()
        st.subheader("Admin (troubleshooting)")

        try:
            sh = get_spreadsheet()
            users_ws = get_ws(USERS_SHEET)
            ensure_users_headers(users_ws)

            # más estable que col_values (y no depende de rango)
            records = users_ws.get_all_records()
            emails = sorted({
                str(r.get("email", "")).strip().lower()
                for r in records
                if str(r.get("email", "")).strip()
            })

            if not emails:
                st.info("No hay usuarios registrados aún.")
            else:
                target = st.selectbox(
                    "Entrar como usuario",
                    options=emails,
                    key="admin_impersonate_target"
                )

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Entrar como este usuario", use_container_width=True):
                        # si es la primera vez que impersonas, guarda tu real
                        if not st.session_state.get("admin_real_user"):
                            st.session_state["admin_real_user"] = user_id
                        st.session_state["impersonating"] = target
                        st.session_state["user_id"] = target
                        st.session_state["loaded"] = False
                        st.session_state["page"] = "cv"
                        st.rerun()

                with c2:
                    if st.button("Volver a mi usuario", use_container_width=True):
                        real = st.session_state.get("admin_real_user", "")
                        if real:
                            st.session_state["impersonating"] = None
                            st.session_state["user_id"] = real
                            st.session_state["loaded"] = False
                            st.session_state["page"] = "cv"
                            st.rerun()
                        else:
                            st.error("No tengo registrado tu usuario real (admin_real_user). Sal y vuelve a entrar.")

                st.divider()
                st.subheader("Recuperar contraseña")
                st.caption(
                    "Genera un código temporal para una usuaria. Cópialo y mándaselo manualmente. "
                    f"Expira en {TOKEN_TTL_MINUTES} minutos y solo se puede usar una vez."
                )

                reset_target = st.selectbox(
                    "Usuario para recuperar contraseña",
                    options=emails,
                    key="admin_reset_target"
                )

                if st.button("Generar código de recuperación", use_container_width=True):
                    try:
                        tokens_ws = get_ws(TOKENS_SHEET)
                        ensure_tokens_headers(tokens_ws)
                        token = issue_token(tokens_ws, reset_target, purpose="reset")
                        st.session_state["last_manual_reset_email"] = reset_target
                        st.session_state["last_manual_reset_code"] = token
                    except Exception as e:
                        st.error("No pude generar el código de recuperación.")
                        st.caption(str(e))

                if st.session_state.get("last_manual_reset_code"):
                    st.success(
                        "Código generado para "
                        f"{st.session_state.get('last_manual_reset_email', '')}:"
                    )
                    st.code(st.session_state["last_manual_reset_code"], language=None)
                    st.caption("Copia este código ahora. No se volverá a mostrar si se recarga la app.")

                st.divider()
                st.subheader("Forzar nueva contraseña")
                st.caption(
                    "Alternativa de emergencia: escribe una contraseña temporal y pídele a la usuaria "
                    "que la cambie entrando a Recuperar contraseña o creando una nueva después."
                )
                direct_target = st.selectbox(
                    "Usuario",
                    options=emails,
                    key="admin_direct_reset_target"
                )
                temp_pw1 = st.text_input("Contraseña temporal", type="password", key="admin_temp_pw1")
                temp_pw2 = st.text_input("Repite contraseña temporal", type="password", key="admin_temp_pw2")

                if st.button("Cambiar contraseña manualmente", use_container_width=True):
                    if len(temp_pw1.strip()) < 8:
                        st.error("La contraseña temporal debe tener al menos 8 caracteres.")
                    elif temp_pw1 != temp_pw2:
                        st.error("Las contraseñas no coinciden.")
                    else:
                        try:
                            set_new_password(users_ws, direct_target, temp_pw1)
                            st.success(f"Contraseña actualizada para {direct_target} ✅")
                        except Exception as e:
                            st.error(str(e))

        except Exception as e:
            st.error("Admin panel: no pude leer la pestaña 'users'. Revisa que exista y permisos del service account.")
            st.caption(str(e))

    # Cerrar sesión
    if st.button("Salir", use_container_width=True):
        for k in ["authed", "user_id", "loaded", "impersonating", "admin_real_user"]:
            st.session_state.pop(k, None)

        st.session_state["adj_df"] = pd.DataFrame(columns=ADJCORE_EDIT_COLS)
        st.session_state["jud_df"] = pd.DataFrame(columns=JUDGING_EDIT_COLS)
        st.session_state["spk_df"] = pd.DataFrame(columns=SPEAKING_EDIT_COLS)
        st.session_state["draft_add"] = {}
        st.session_state["draft_edit"] = {}
        st.session_state["page"] = "cv"
        st.rerun()


# =========================
# CARGAR DESDE SHEETS (una vez por login / cambio de usuario)
# =========================
if not st.session_state.get("loaded", False):
    try:
        sh = get_spreadsheet()
        ws_adj = sh.worksheet(WS_ADJCORE)
        ws_jud = sh.worksheet(WS_JUDGING)
        ws_spk = sh.worksheet(WS_SPEAKING)

        ensure_headers(ws_adj, ADJCORE_SAVE_COLS)
        ensure_headers(ws_jud, JUDGING_SAVE_COLS)
        ensure_headers(ws_spk, SPEAKING_SAVE_COLS)

        adj_saved = load_user_df(ws_adj, user_id)
        jud_saved = load_user_df(ws_jud, user_id)
        spk_saved = load_user_df(ws_spk, user_id)

        st.session_state["adj_df"] = to_editor_df(adj_saved, ADJCORE_EDIT_COLS, "adjcore")
        st.session_state["jud_df"] = to_editor_df(jud_saved, JUDGING_EDIT_COLS, "judging")
        st.session_state["spk_df"] = to_editor_df(spk_saved, SPEAKING_EDIT_COLS, "speaking")

        st.session_state["loaded"] = True
        st.session_state["page"] = "cv"
        st.rerun()

    except Exception as e:
        st.error("No pude cargar desde Google Sheets. Revisa permisos, SHEET_ID, secrets y nombres de pestañas.")
        st.exception(e)
        st.stop()

st.success(f"Ingresaste como: **{user_id}**")

# =========================
# NAVEGACIÓN SUPERIOR
# =========================
nav1, nav2, nav3 = st.columns([2, 2, 1])

with nav3:
    if st.button("🏠 Inicio", use_container_width=True):
        st.session_state["page"] = "cv"
        st.rerun()

with nav1:
    if st.button("➕ Añadir logro", use_container_width=True):
        st.session_state["draft_add"] = {}
        st.session_state["page"] = "add"
        st.rerun()

with nav2:
    if st.button("🛠️ Gestionar / Editar logros", use_container_width=True):
        st.session_state["page"] = "manage"
        st.rerun()

st.divider()


# =========================
# FORMULARIO WIZARD
# =========================
def wizard_form(state_key: str, mode: str, edit_index: int | None = None):
    d = st.session_state[state_key]

    def opt_index(options, value, default=0):
        try:
            return options.index(value)
        except Exception:
            return default

    titulo = "Añadir logro" if mode == "add" else "Editar logro"
    st.header(titulo)

    if mode == "edit":
        st.info(
            "Solo puedes editar un logro dentro de la misma categoría. "
            "Si quieres moverlo a otra categoría, elimínalo y vuelve a crearlo en la categoría correcta."
        )

    # categoría
    if mode == "add":
        current_type = d.get("type", "")
        current_type_ui = internal_to_rubro(current_type) if current_type in ["speaking", "judging", "adjcore"] else SELECT

        ach_type_ui = st.selectbox(
            "Categoría del logro",
            options=[SELECT] + TIPOS_LOGRO,
            index=opt_index([SELECT] + TIPOS_LOGRO, current_type_ui),
            key=f"{state_key}_type_selector"
        )
        ach_type = rubro_to_internal(ach_type_ui)
        d["type"] = ach_type
    else:
        ach_type = d.get("type", "")
        st.text_input("Categoría del logro", value=internal_to_rubro(ach_type), disabled=True)

    st.divider()

    tournament_options = get_tournament_options_for_type(ach_type)

    with st.form(f"{mode}_form", clear_on_submit=False):
        tournament_pick = st.selectbox(
            "Torneo",
            options=tournament_options,
            index=opt_index(tournament_options, d.get("tournament_pick", SELECT))
        )

        tournament_other = st.text_input(
            "Si elegiste OTRO, escribe el torneo",
            value=str(d.get("tournament_other", ""))
        )

        year_val = d.get("year", CURRENT_YEAR)
        try:
            year_val = int(year_val)
        except Exception:
            year_val = CURRENT_YEAR

        year = st.number_input(
            "Año",
            min_value=1990,
            max_value=CURRENT_YEAR + 1,
            step=1,
            value=year_val
        )

        name_on_tab = st.text_input("Nombre en tab", value=str(d.get("name_on_tab", "")))
        tab_link = st.text_input("Link de tab", value=str(d.get("tab_link", "")))
        format_pick = st.selectbox(
            "Formato",
            options=FORMAT_OPTIONS,
            index=opt_index(FORMAT_OPTIONS, d.get("format", SELECT))
        )

        d.update({
            "type": ach_type,
            "tournament_pick": tournament_pick,
            "tournament_other": tournament_other,
            "year": year,
            "name_on_tab": name_on_tab,
            "tab_link": tab_link,
            "format": format_pick,
        })

        # campos por tipo
        if ach_type == "adjcore":
            role = st.selectbox(
                "Rol",
                options=ADJCORE_ROLE_OPTIONS,
                index=opt_index(ADJCORE_ROLE_OPTIONS, d.get("role", SELECT))
            )
            d["role"] = role

        elif ach_type == "judging":
            br = st.selectbox(
                "¿Hubo break?",
                options=YES_NO_OPTIONS,
                index=opt_index(YES_NO_OPTIONS, d.get("break", SELECT))
            )

            if br == "Sí":
                fr = st.selectbox(
                    "Ronda más lejana juzgada",
                    options=ROUND_OPTIONS,
                    index=opt_index(ROUND_OPTIONS, d.get("furthest_round_judged", SELECT))
                )
                rr = st.selectbox(
                    "Rol en esa ronda",
                    options=JUDGE_ROLE_OPTIONS,
                    index=opt_index(JUDGE_ROLE_OPTIONS, d.get("role_in_round", SELECT))
                )
            else:
                fr = ""
                rr = ""

            d.update({
                "break": br,
                "furthest_round_judged": fr,
                "role_in_round": rr
            })

        elif ach_type == "speaking":
            team_name = st.text_input("Nombre del equipo", value=str(d.get("team_name", "")))
            furthest = st.selectbox(
                "Ronda más lejana debatida",
                options=ROUND_SPK_OPTIONS,
                index=opt_index(ROUND_SPK_OPTIONS, d.get("furthest_round_spoken", SELECT))
            )
            spk_rank = st.text_input("Ranking de oradora", value=str(d.get("speaker_rank", "")))
            tm_rank = st.text_input("Ranking de equipo", value=str(d.get("team_rank", "")))

            d.update({
                "team_name": team_name,
                "furthest_round_spoken": furthest,
                "speaker_rank": spk_rank,
                "team_rank": tm_rank
            })

        boton = "➕ Añadir logro" if mode == "add" else "💾 Guardar cambios"
        submitted = st.form_submit_button(boton)

    if submitted:
        try:
            validate_wizard(d, mode=mode, edit_index=edit_index)

            if mode == "add":
                push_row_from_wizard(d, mode="add")

                res = with_save_lock(user_id, lambda: guardar_cv_en_sheets(user_id))
                if res is None:
                    # lock activo (doble click / refresh rápido)
                    st.stop()

                st.session_state[state_key] = {}
                st.session_state["page"] = "cv"
                st.success("Logro añadido y guardado automáticamente ✅")
                st.rerun()

            else:
                push_row_from_wizard(d, mode="edit", edit_index=edit_index)

                res = with_save_lock(user_id, lambda: guardar_cv_en_sheets(user_id))
                if res is None:
                    st.stop()

                st.session_state[state_key] = {}
                st.session_state["page"] = "manage"
                st.success("Logro actualizado y guardado automáticamente ✅")
                st.rerun()

        except Exception as e:
            st.error(str(e))
            st.stop()


# =========================
# PAGE: MANAGE
# =========================
def manage_page():
    st.header("Gestionar / Editar logros")
    st.caption("Puedes editar o eliminar logros. No se puede mover un logro de una categoría a otra desde aquí.")

    opciones_tipo = ["speaking", "judging", "adjcore"]
    etiquetas = {
        "speaking": "Debatiente",
        "judging": "Jueza",
        "adjcore": "Equipo de adjudicación"
    }

    typ = st.selectbox(
        "Categoría",
        options=opciones_tipo,
        index=opciones_tipo.index(st.session_state.get("manage_type", "speaking")),
        format_func=lambda x: etiquetas[x],
        key="manage_type_select"
    )

    st.session_state["manage_type"] = typ

    df_key, cols = df_by_type_key(typ)
    df = st.session_state[df_key].copy()

    if df.empty:
        st.info("No hay logros en esta sección.")
        return

    labels = [make_item_label(df, i) for i in range(len(df))]
    default_idx = 0

    if st.session_state.get("manage_index") is not None:
        try:
            default_idx = int(st.session_state["manage_index"])
            if default_idx < 0 or default_idx >= len(df):
                default_idx = 0
        except Exception:
            default_idx = 0

    chosen = st.selectbox(
        "Elige el logro",
        options=list(range(len(df))),
        index=default_idx,
        format_func=lambda i: labels[i]
    )

    st.session_state["manage_index"] = int(chosen)

    r = df.iloc[int(chosen)]
    st.caption("Vista previa (solo lectura)")

    preview = pd.DataFrame([r]).copy()
    preview["tournament"] = preview.apply(pretty_tournament, axis=1)

    display_cols = [c for c in cols if c not in ["tournament_pick", "tournament_other"]]
    display_cols = ["tournament"] + [c for c in display_cols if c != "tournament"]

    st.dataframe(preview[display_cols], use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns([1, 1, 2])

    with c1:
        if st.button("✏️ Editar", use_container_width=True):
            d = {}
            for c in cols:
                d[c] = r.get(c, "")
            d["type"] = typ

            st.session_state["draft_edit"] = d
            st.session_state["edit_index"] = int(chosen)
            st.session_state["page"] = "edit"
            st.rerun()

    with c2:
        if st.button("🗑️ Eliminar", use_container_width=True):
            try:
                idx = int(chosen)
                df2 = df.drop(df.index[idx]).reset_index(drop=True)
                st.session_state[df_key] = df2.copy()

                res = with_save_lock(user_id, lambda: guardar_cv_en_sheets(user_id))
                if res is None:
                    st.stop()

                st.session_state["manage_index"] = None
                st.success("Logro eliminado y guardado automáticamente ✅")
                st.rerun()

            except Exception as e:
                st.error(str(e))
                st.stop()

    with c3:
        st.caption(
            "El orden en el que ingresas los logros no afectará su calificación. "
            "Si deseas modificar el orden, debes borrar e ingresar los logros nuevamente en el orden deseado."
        )


# =========================
# ROUTER
# =========================
if st.session_state["page"] == "add":
    if st.button("⬅️ Volver"):
        st.session_state["page"] = "cv"
        st.rerun()
    wizard_form("draft_add", mode="add")

elif st.session_state["page"] == "manage":
    manage_page()

elif st.session_state["page"] == "edit":
    idx = st.session_state.get("edit_index", None)
    if idx is None:
        st.session_state["page"] = "manage"
        st.rerun()

    if st.button("⬅️ Volver"):
        st.session_state["page"] = "manage"
        st.rerun()

    wizard_form("draft_edit", mode="edit", edit_index=int(idx))

else:
    # =========================
    # PAGE: CV
    # =========================
    LABEL_ADJ = {
        "tournament": "Torneo",
        "year": "Año",
        "name_on_tab": "Nombre en tab",
        "tab_link": "Link de tab",
        "format": "Formato",
        "role": "Rol",
    }

    LABEL_JUD = {
        "tournament": "Torneo",
        "year": "Año",
        "name_on_tab": "Nombre en tab",
        "tab_link": "Link de tab",
        "format": "Formato",
        "break": "Break",
        "furthest_round_judged": "Ronda más lejana juzgada",
        "role_in_round": "Rol en esa ronda",
    }

    LABEL_SPK = {
        "tournament": "Torneo",
        "year": "Año",
        "name_on_tab": "Nombre en tab",
        "team_name": "Equipo",
        "tab_link": "Link de tab",
        "format": "Formato",
        "furthest_round_spoken": "Ronda más lejana debatida",
        "speaker_rank": "Ranking de oradora",
        "team_rank": "Ranking de equipo",
    }

    st.subheader(f"Equipo de adjudicación (máximo {max_rows_for_type('adjcore')})")
    render_readonly_table(st.session_state["adj_df"], ADJCORE_EDIT_COLS, LABEL_ADJ)

    st.divider()

    st.subheader(f"Jueza (máximo {max_rows_for_type('judging')})")
    render_readonly_table(st.session_state["jud_df"], JUDGING_EDIT_COLS, LABEL_JUD)

    st.divider()

    st.subheader(f"Debatiente (máximo {max_rows_for_type('speaking')})")
    render_readonly_table(st.session_state["spk_df"], SPEAKING_EDIT_COLS, LABEL_SPK)

    st.divider()
    st.subheader("Guardar")

    if st.button("✅ Guardar", use_container_width=True):
        try:
            result = with_save_lock(user_id, lambda: guardar_cv_en_sheets(user_id))
            if result is None:
                st.stop()

            n_adj, n_jud, n_spk = result
            st.success(
                f"Guardado correctamente ✅ | "
                f"Equipo de adjudicación={n_adj} | Jueza={n_jud} | Debatiente={n_spk}"
            )

        except Exception as e:
            st.error("No se pudo guardar. Revisa permisos, encabezados, SHEET_ID y secrets.")
            st.exception(e)