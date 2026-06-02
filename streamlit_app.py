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
    page_title="CV - Postulación RRH",
    page_icon="👑",
    layout="wide"
)

MAX_ROWS = 15
CURRENT_YEAR = datetime.utcnow().year
SELECT = "— Selecciona —"

FORMATOS = ["BP", "WSDC", "AP", "Otro"]
SI_NO = ["Sí", "No"]
RONDAS_ORADORA = ["Octavos", "Cuartos", "Semis", "Final", "Campeón"]

TOURNAMENT_OTHER = "OTRO (no está en la lista)"

# Pestañas de Google Sheets (se crean solas si no existen)
WS_P1 = "persona1"
WS_P2 = "persona2"
WS_DUPLA = "dupla"

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
    "team_name": "Nombre del equipo",
    "break": "¿Hubo break?",
    "furthest_round_spoken": "Ronda más lejana debatida",
    "speaker_rank": "Ranking de oradora",
    "team_rank": "Ranking de equipo",
    "num_salas": "Número de salas",
    "is_novato_tematico": "¿Novato o temático?",
    "name_on_tab_p2": "Nombre de Persona 2 en tab",
    "speaker_rank_p2": "Ranking de oradora de Persona 2",
}

def pretty_field_name(field_key: str) -> str:
    return FIELD_LABELS.get(field_key, field_key)

# =========================
# CLASIFICACIÓN DE TORNEOS
# - A y B son listas fijas.
# - Todo lo demás (opens conocidos + OTRO) se clasifica por número de salas.
# - OTRO + novato/temático => E.
# - Sin break => E (siempre, aunque sea A/B).
# Los tiers NO se muestran a las usuarias.
# =========================
TIER_A = [
    "CMUDE",
    "WUDC",
]

TIER_B = [
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
    "MUMUDI",
    "UNIANDES IV",
]

# Torneos novatos/temáticos conocidos: siempre tier E (el menor peso),
# sin importar el número de salas.
TIER_E = [
    "Toniichan",
    "Mi Primer BP",
    "Torneo Novato",
    "Torneo de las Estrellas Nacientes",
    "DEBATOON",
]

# Opens conocidos que aparecen en el menú por comodidad,
# pero cuyo peso se calcula por número de salas (no son novatos/temáticos).
OPENS_KNOWN = [
    "MED",
    "WSDC",
    "EUDC",
    "NAUDC",
    "CMUDE Masters",
    "Copenhaguen",
    "Comunícate",
    "Torneo de Verano",
    "Torneo de Otoño",
    "Torneo de Invierno",
    "Torneo de Primavera",
    "Torneo de Navidad",
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
]

ALL_KNOWN = TIER_A + TIER_B + OPENS_KNOWN + TIER_E

def all_tournaments() -> list[str]:
    seen = []
    for t in ALL_KNOWN:
        if t not in seen:
            seen.append(t)
    return sorted(seen, key=lambda x: x.lower())

def tournament_options() -> list[str]:
    return [SELECT, TOURNAMENT_OTHER] + all_tournaments()

FORMAT_OPTIONS = [SELECT] + FORMATOS
YES_NO_OPTIONS = [SELECT] + SI_NO
ROUND_SPK_OPTIONS = [SELECT] + RONDAS_ORADORA

def parse_int_or_none(v):
    try:
        return int(str(v).strip())
    except Exception:
        return None

def salas_to_tier(n) -> str | None:
    if n is None:
        return None
    if n > 15:
        return "C"
    if n >= 10:
        return "D"
    return "E"

def is_other_tournament(name: str) -> bool:
    name = str(name).strip()
    return name != "" and name not in ALL_KNOWN

def classify_logro(tournament: str, had_break: str, is_novato_tematico: str, num_salas) -> tuple[str, str]:
    """Devuelve (tier, criterio). 'criterio' explica por qué se asignó ese tier."""
    name = str(tournament).strip()
    other = is_other_tournament(name)

    # Sin break => siempre E (aunque sea CMUDE/WUDC o un torneo B).
    if str(had_break).strip() == "No":
        return ("E", "Sin break")

    if name in TIER_A:
        return ("A", name)
    if name in TIER_B:
        return ("B", name)
    if name in TIER_E:
        return ("E", "Novato/temático")

    # No A/B: novato/temático (solo para OTRO) => E
    if other and str(is_novato_tematico).strip() == "Sí":
        return ("E", "Novato/temático")

    # Resto: por número de salas
    n = parse_int_or_none(num_salas)
    t = salas_to_tier(n)
    if t is None:
        return ("E", "Salas (sin dato)")
    return (t, f"Salas: {n}")

# =========================
# SECCIONES (3 CV de debatiente)
# =========================
COMMON_EDIT_COLS = [
    "tournament_pick", "tournament_other", "is_novato_tematico", "num_salas",
    "year", "name_on_tab", "tab_link", "format", "team_name",
    "break", "furthest_round_spoken", "speaker_rank", "team_rank",
]

DUPLA_EDIT_COLS = [
    "tournament_pick", "tournament_other", "is_novato_tematico", "num_salas",
    "year", "name_on_tab", "name_on_tab_p2", "tab_link", "format", "team_name",
    "break", "furthest_round_spoken", "team_rank", "speaker_rank", "speaker_rank_p2",
]

COMMON_SAVE_COLS = [
    "user_id", "submitted_utc", "tournament",
    "year", "name_on_tab", "tab_link", "format", "team_name",
    "break", "furthest_round_spoken", "team_rank", "speaker_rank",
    "num_salas", "is_novato_tematico",
    "tier", "criterio",
]

DUPLA_SAVE_COLS = [
    "user_id", "submitted_utc", "tournament",
    "year", "name_on_tab", "name_on_tab_p2", "tab_link", "format", "team_name",
    "break", "furthest_round_spoken", "team_rank", "speaker_rank", "speaker_rank_p2",
    "num_salas", "is_novato_tematico",
    "tier", "criterio",
]

SECTIONS = {
    "p1": {
        "label": "CV de Persona 1", "ws": WS_P1, "is_dupla": False,
        "df_key": "p1_df", "edit_cols": COMMON_EDIT_COLS, "save_cols": COMMON_SAVE_COLS,
    },
    "p2": {
        "label": "CV de Persona 2", "ws": WS_P2, "is_dupla": False,
        "df_key": "p2_df", "edit_cols": COMMON_EDIT_COLS, "save_cols": COMMON_SAVE_COLS,
    },
    "dupla": {
        "label": "CV de Dupla", "ws": WS_DUPLA, "is_dupla": True,
        "df_key": "dupla_df", "edit_cols": DUPLA_EDIT_COLS, "save_cols": DUPLA_SAVE_COLS,
    },
}
SECTION_ORDER = ["p1", "p2", "dupla"]

def label_to_section(label: str) -> str | None:
    for sk in SECTION_ORDER:
        if SECTIONS[sk]["label"] == label:
            return sk
    return None

def current_user() -> str:
    return (st.session_state.get("user_id", "") or "").strip().lower()

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

    def _get():
        try:
            return sh.worksheet(title)
        except gspread.WorksheetNotFound:
            try:
                return sh.add_worksheet(title=title, rows=2000, cols=30)
            except Exception:
                return sh.worksheet(title)

    return gspread_call(_get)

def ensure_headers(ws, headers: list[str]):
    # Siempre verificamos la fila 1 (sin caché): así, si la pestaña está vacía,
    # reponemos los encabezados solos; y si hay datos sin encabezado, avisamos claro
    # en lugar de corromper el guardado.
    first_row = gspread_call(lambda: ws.row_values(1))
    norm = [h.strip() for h in first_row]

    if len(norm) == 0:
        gspread_call(lambda: ws.insert_row(headers, 1))
        return

    if norm == headers:
        return

    raise ValueError(
        f"La pestaña '{ws.title}' no tiene los encabezados correctos en la fila 1.\n"
        f"Esperado: {headers}\n"
        f"Encontrado: {first_row}\n"
        f"Solución: borra TODO el contenido de esa pestaña (déjala completamente vacía) "
        f"y vuelve a guardar; la app reescribirá los encabezados automáticamente."
    )

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
# HELPERS: DATAFRAMES
# =========================
SELECTBOX_FIELDS = ("tournament_pick", "format", "break", "furthest_round_spoken", "is_novato_tematico")

def blank_row(cols: list[str]) -> dict:
    row = {c: "" for c in cols}
    for c in SELECTBOX_FIELDS:
        if c in cols:
            row[c] = SELECT
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

def tournament_final(r) -> str:
    pick = str(r.get("tournament_pick", "")).strip()
    other = str(r.get("tournament_other", "")).strip()
    if pick in ("", SELECT):
        return ""
    if pick == TOURNAMENT_OTHER:
        return other.strip()
    return pick

def pretty_tournament(r) -> str:
    pick = str(r.get("tournament_pick", "")).strip()
    other = str(r.get("tournament_other", "")).strip()
    if pick == TOURNAMENT_OTHER:
        return other
    if pick == SELECT:
        return ""
    return pick

def tournament_to_pick_other(t: str):
    t = (t or "").strip()
    if t == "":
        return (SELECT, "")
    if t in all_tournaments():
        return (t, "")
    return (TOURNAMENT_OTHER, t)

def to_editor_df(saved: pd.DataFrame, section_key: str) -> pd.DataFrame:
    cfg = SECTIONS[section_key]
    edit_cols = cfg["edit_cols"]
    if saved.empty:
        return pd.DataFrame(columns=edit_cols)

    out_rows = []
    for _, r in saved.iterrows():
        row = blank_row(edit_cols)
        pick, other = tournament_to_pick_other(str(r.get("tournament", "")))
        row["tournament_pick"] = pick
        row["tournament_other"] = other
        for c in edit_cols:
            if c in ("tournament_pick", "tournament_other"):
                continue
            if c in r.index:
                row[c] = r[c]
        out_rows.append(row)

    out = pd.DataFrame(out_rows, columns=edit_cols)
    return out.iloc[:MAX_ROWS].copy()

def make_duplicate_key(r) -> tuple[str, str]:
    torneo = tournament_final(r).strip().lower()
    year = str(r.get("year", "")).strip()
    return (torneo, year)

def validate_no_duplicates(df: pd.DataFrame, label: str):
    temp = df[df.apply(editor_row_used, axis=1)].copy()
    seen = set()
    dups = []
    for _, r in temp.iterrows():
        k = make_duplicate_key(r)
        if k[0] == "" or k[1] == "":
            continue
        if k in seen and k not in dups:
            dups.append(k)
        seen.add(k)
    if dups:
        formatted = [f"{t.upper()} ({y})" for t, y in dups]
        raise ValueError(
            f"No puedes repetir el mismo torneo y año en {label}: {', '.join(formatted)}."
        )

def render_readonly_table(df: pd.DataFrame, section_key: str, label_map: dict):
    cfg = SECTIONS[section_key]
    edit_cols = cfg["edit_cols"]
    if df.empty:
        st.info("Aún no hay logros en esta sección.")
        return

    show = df.copy()
    show["tournament"] = show.apply(pretty_tournament, axis=1)

    display_cols = [c for c in edit_cols if c not in ("tournament_pick", "tournament_other")]
    display_cols = ["tournament"] + [c for c in display_cols if c != "tournament"]
    show = show[display_cols].copy()
    show.rename(columns=label_map, inplace=True)

    st.dataframe(show, use_container_width=True, hide_index=True)

def make_item_label(df: pd.DataFrame, idx: int) -> str:
    if df.empty or idx < 0 or idx >= len(df):
        return ""
    r = df.iloc[idx]
    t = pretty_tournament(r) or "—"
    y = str(r.get("year", "")).strip() or "—"
    name = str(r.get("name_on_tab", "")).strip() or "—"
    return f"{idx+1}. {t} | {y} | {name}"

# =========================
# LÓGICA DEL WIZARD
# =========================
def resolve_tournament(d: dict) -> str:
    pick = str(d.get("tournament_pick", SELECT)).strip()
    other = str(d.get("tournament_other", "")).strip()
    if pick in ("", SELECT):
        return ""
    if pick == TOURNAMENT_OTHER:
        return other
    return pick

def needs_salas(d: dict) -> bool:
    """Pedimos salas solo cuando el peso depende de ellas (torneos fuera de A/B/E
    que no sean novatos/temáticos)."""
    t = resolve_tournament(d)
    if t == "":
        return False
    if t in TIER_A or t in TIER_B or t in TIER_E:
        return False
    pick = str(d.get("tournament_pick", SELECT)).strip()
    if pick == TOURNAMENT_OTHER and str(d.get("is_novato_tematico", SELECT)).strip() == "Sí":
        return False
    return True

def collect_wizard_values(is_dupla: bool, wk) -> dict:
    def gv(f, default=""):
        return st.session_state.get(wk(f), default)

    d = {
        "tournament_pick": gv("tournament_pick", SELECT),
        "tournament_other": gv("tournament_other", ""),
        "break": gv("break", SELECT),
        "furthest_round_spoken": gv("furthest_round_spoken", SELECT),
        "is_novato_tematico": gv("is_novato_tematico", SELECT),
        "num_salas": gv("num_salas", ""),
        "year": gv("year", CURRENT_YEAR),
        "name_on_tab": gv("name_on_tab", ""),
        "tab_link": gv("tab_link", ""),
        "format": gv("format", SELECT),
        "team_name": gv("team_name", ""),
        "speaker_rank": gv("speaker_rank", ""),
        "team_rank": gv("team_rank", ""),
    }
    if is_dupla:
        d["name_on_tab_p2"] = gv("name_on_tab_p2", "")
        d["speaker_rank_p2"] = gv("speaker_rank_p2", "")
    return d

def validate_wizard_values(d: dict, is_dupla: bool):
    pick = str(d.get("tournament_pick", SELECT)).strip()
    if pick in ("", SELECT):
        raise ValueError("Falta: Torneo.")
    if pick == TOURNAMENT_OTHER and str(d.get("tournament_other", "")).strip() == "":
        raise ValueError("Falta: Torneo (si elegiste OTRO).")

    try:
        y = int(d.get("year"))
        if y < 1990 or y > CURRENT_YEAR + 1:
            raise ValueError
    except Exception:
        raise ValueError(f"Año inválido (debe estar entre 1990 y {CURRENT_YEAR + 1}).")

    if str(d.get("name_on_tab", "")).strip() == "":
        raise ValueError("Falta: Nombre en tab.")
    if is_dupla and str(d.get("name_on_tab_p2", "")).strip() == "":
        raise ValueError("Falta: Nombre de Persona 2 en tab.")
    if str(d.get("tab_link", "")).strip() == "":
        raise ValueError("Falta: Link de tab.")
    if str(d.get("format", SELECT)).strip() in ("", SELECT):
        raise ValueError("Falta: Formato.")
    if str(d.get("team_name", "")).strip() == "":
        raise ValueError("Falta: Nombre del equipo.")

    br = str(d.get("break", SELECT)).strip()
    if br in ("", SELECT):
        raise ValueError("Falta: ¿Hubo break?")
    if br == "Sí":
        if str(d.get("furthest_round_spoken", SELECT)).strip() in ("", SELECT):
            raise ValueError("Falta: Ronda más lejana debatida.")

    if pick == TOURNAMENT_OTHER:
        if str(d.get("is_novato_tematico", SELECT)).strip() in ("", SELECT):
            raise ValueError("Falta: ¿El torneo era novato o temático?")

    if needs_salas(d):
        n = parse_int_or_none(d.get("num_salas"))
        if n is None or n < 1:
            raise ValueError("Falta: número de salas (debe ser un número mayor a 0).")

    if is_dupla:
        if str(d.get("speaker_rank", "")).strip() == "":
            raise ValueError("Falta: Ranking de oradora de Persona 1.")
        if str(d.get("speaker_rank_p2", "")).strip() == "":
            raise ValueError("Falta: Ranking de oradora de Persona 2.")
    else:
        if str(d.get("speaker_rank", "")).strip() == "":
            raise ValueError("Falta: Ranking de oradora.")
    if str(d.get("team_rank", "")).strip() == "":
        raise ValueError("Falta: Ranking de equipo.")

def normalize_wizard(d: dict, is_dupla: bool):
    pick = str(d.get("tournament_pick", SELECT)).strip()
    if pick != TOURNAMENT_OTHER:
        d["tournament_other"] = ""
        d["is_novato_tematico"] = ""
    if str(d.get("break", SELECT)).strip() != "Sí":
        d["furthest_round_spoken"] = ""
    if not needs_salas(d):
        d["num_salas"] = ""
    if not is_dupla:
        d.pop("name_on_tab_p2", None)
        d.pop("speaker_rank_p2", None)
    return d

def push_row(section_key: str, d: dict, mode: str, edit_index: int | None = None):
    cfg = SECTIONS[section_key]
    df_key = cfg["df_key"]
    edit_cols = cfg["edit_cols"]

    df = st.session_state[df_key].copy()

    row = blank_row(edit_cols)
    for c in edit_cols:
        if c in d:
            row[c] = d[c]

    if mode == "add":
        if len(df) >= MAX_ROWS:
            raise ValueError(f"Máximo {MAX_ROWS} logros en {cfg['label']}.")
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        if edit_index is None or edit_index < 0 or edit_index >= len(df):
            raise ValueError("Índice inválido para edición.")
        for c in edit_cols:
            df.loc[edit_index, c] = row.get(c, "")

    validate_no_duplicates(df, cfg["label"])
    if len(df) > MAX_ROWS:
        raise ValueError(f"Máximo {MAX_ROWS} logros en {cfg['label']}.")

    st.session_state[df_key] = df.copy()

# =========================
# GUARDADO
# =========================
def build_save_df(edit_df: pd.DataFrame, user_id: str, section_key: str) -> pd.DataFrame:
    cfg = SECTIONS[section_key]
    save_cols = cfg["save_cols"]

    df = edit_df.copy()
    df = df[df.apply(editor_row_used, axis=1)].copy()
    df.reset_index(drop=True, inplace=True)
    if df.empty:
        return pd.DataFrame(columns=save_cols)

    validate_no_duplicates(df, cfg["label"])

    submitted_utc = datetime.utcnow().isoformat(timespec="seconds")
    out_rows = []
    for _, r in df.iterrows():
        tournament = tournament_final(r)
        if tournament == "":
            continue  # fila incompleta: la ignoramos en vez de romper el guardado

        had_break = str(r.get("break", "")).strip()
        novato = str(r.get("is_novato_tematico", "")).strip()
        salas = r.get("num_salas", "")
        tier, criterio = classify_logro(tournament, had_break, novato, salas)

        row = {c: "" for c in save_cols}
        row["user_id"] = user_id
        row["submitted_utc"] = submitted_utc
        row["tournament"] = tournament
        row["tier"] = tier
        row["criterio"] = criterio
        for c in save_cols:
            if c in ("user_id", "submitted_utc", "tournament", "tier", "criterio"):
                continue
            if c in r.index:
                row[c] = r[c]
        out_rows.append(row)

    return pd.DataFrame(out_rows, columns=save_cols)

def guardar_cv():
    user_id = current_user()

    for sk in SECTION_ORDER:
        cfg = SECTIONS[sk]
        if len(st.session_state[cfg["df_key"]]) > MAX_ROWS:
            raise ValueError(f"Máximo {MAX_ROWS} logros en {cfg['label']}.")

    for sk in SECTION_ORDER:
        cfg = SECTIONS[sk]
        bad = validate_other_names(st.session_state[cfg["df_key"]])
        if bad:
            raise ValueError(
                f"{cfg['label']}: falta el nombre del torneo (OTRO) en filas "
                + ", ".join(str(i + 1) for i in bad)
            )

    outs = {sk: build_save_df(st.session_state[SECTIONS[sk]["df_key"]], user_id, sk) for sk in SECTION_ORDER}

    wss = {sk: get_ws(SECTIONS[sk]["ws"]) for sk in SECTION_ORDER}
    for sk in SECTION_ORDER:
        ensure_headers(wss[sk], SECTIONS[sk]["save_cols"])

    for sk in SECTION_ORDER:
        delete_user_rows(wss[sk], user_id)

    counts = {sk: append_rows(wss[sk], outs[sk]) for sk in SECTION_ORDER}

    for sk in SECTION_ORDER:
        dedupe_user_rows(wss[sk], user_id, key_cols=["tournament", "year"])

    return counts

# =========================
# INIT STATE
# =========================
ensure_df("p1_df", COMMON_EDIT_COLS)
ensure_df("p2_df", COMMON_EDIT_COLS)
ensure_df("dupla_df", DUPLA_EDIT_COLS)

for k, v in {
    "page": "cv",
    "manage_type": "p1",
    "manage_index": None,
    "wizard_nonce": 0,
    "wz_mode": "add",
    "wz_seed": {},
    "wz_section": None,
    "wz_edit_index": -1,
    "authed": False,
    "user_id": "",
    "admin_real_user": "",
    "impersonating": None,
    "loaded": False,
    "last_manual_reset_code": "",
    "last_manual_reset_email": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =========================
# AUTH (signup + login + reset)
# =========================
def auth_screen():
    st.title("Ingreso")

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
        st.info(
            "**Esta cuenta es compartida por las dos personas de la dupla.** "
            "Pónganse de acuerdo entre ambas sobre qué correo y qué contraseña usar: "
            "las dos van a entrar con la misma cuenta y desde ahí llenarán el **CV de Persona 1**, "
            "el **CV de Persona 2** y el **CV de Dupla**. "
            "Guarden bien el correo y la contraseña, porque las usarán las dos."
        )

        email = st.text_input("Correo (acordado entre las dos)", key="su_email")
        pw1 = st.text_input("Contraseña (acordada entre las dos)", type="password", key="su_pw1")
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
                    st.success("Cuenta creada ✅ Ya pueden entrar en la pestaña “Entrar”.")
                except Exception as e:
                    st.error(str(e))

    with tab_reset:
        st.info(
            "Si olvidaron la contraseña, pídanle un código de recuperación a una persona del "
            "equipo organizador. Indiquen el correo con el que crearon la cuenta. "
            "Cuando reciban el código, ingrésenlo aquí para crear una contraseña nueva."
        )

        email = st.text_input("Correo registrado", key="rp_email")
        st.caption("El código no se envía automáticamente por correo; lo genera manualmente un admin.")

        code = st.text_input("Código de recuperación entregado por admin", key="rp_code")
        new_pw1 = st.text_input("Nueva contraseña", type="password", key="rp_pw1")
        new_pw2 = st.text_input("Repite la nueva contraseña", type="password", key="rp_pw2")

        if st.button("Cambiar contraseña", use_container_width=True):
            if email.strip() == "" or "@" not in email:
                st.error("Ingresa el correo con el que crearon la cuenta.")
            elif code.strip() == "":
                st.error("Ingresa el código de recuperación que les dio el admin.")
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
                        st.success("Contraseña actualizada ✅ Vayan a la pestaña 'Entrar'.")
                    except Exception as e:
                        st.error(str(e))

# =========================
# UI: LOGIN (gated)
# =========================
st.title("CV — Postulación al RRH 👑")

if not st.session_state.get("authed", False):
    st.caption(
        "Crea una cuenta (una sola, compartida por la dupla) o ingresa. "
        "Si olvidan la contraseña, pidan un código de recuperación al equipo organizador."
    )
    auth_screen()
    st.stop()

user_id = current_user()

if not st.session_state.get("admin_real_user"):
    st.session_state["admin_real_user"] = user_id

if not user_id:
    st.session_state["authed"] = False
    auth_screen()
    st.stop()

# =========================
# SIDEBAR: sesión + admin
# =========================
with st.sidebar:
    st.header("Sesión")
    st.write(f"Conectado como: **{user_id}**")

    if st.session_state.get("impersonating"):
        st.warning(f"Modo admin: estás editando como **{st.session_state['impersonating']}**.")
        real = st.session_state.get("admin_real_user", "")
        if real:
            st.caption(f"Usuario real: {real}")

    if is_admin(user_id) or is_admin(st.session_state.get("admin_real_user", "")):
        st.divider()
        st.subheader("Admin (troubleshooting)")

        try:
            users_ws = get_ws(USERS_SHEET)
            ensure_users_headers(users_ws)

            records = gspread_call(lambda: users_ws.get_all_records())
            emails = sorted({
                str(r.get("email", "")).strip().lower()
                for r in records
                if str(r.get("email", "")).strip()
            })

            if not emails:
                st.info("No hay usuarios registrados aún.")
            else:
                target = st.selectbox("Entrar como usuario", options=emails, key="admin_impersonate_target")

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Entrar como este usuario", use_container_width=True):
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
                            st.error("No tengo registrado tu usuario real. Sal y vuelve a entrar.")

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
                    st.success(f"Código generado para {st.session_state.get('last_manual_reset_email', '')}:")
                    st.code(st.session_state["last_manual_reset_code"], language=None)
                    st.caption("Copia este código ahora. No se volverá a mostrar si se recarga la app.")

                st.divider()
                st.subheader("Forzar nueva contraseña")
                st.caption(
                    "Alternativa de emergencia: escribe una contraseña temporal y pídele a la usuaria "
                    "que la cambie después."
                )
                direct_target = st.selectbox("Usuario", options=emails, key="admin_direct_reset_target")
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
            st.error("Admin panel: no pude leer la pestaña 'users'. Revisa que exista y los permisos del service account.")
            st.caption(str(e))

    if st.button("Salir", use_container_width=True):
        for k in ["authed", "user_id", "loaded", "impersonating", "admin_real_user"]:
            st.session_state.pop(k, None)

        st.session_state["p1_df"] = pd.DataFrame(columns=COMMON_EDIT_COLS)
        st.session_state["p2_df"] = pd.DataFrame(columns=COMMON_EDIT_COLS)
        st.session_state["dupla_df"] = pd.DataFrame(columns=DUPLA_EDIT_COLS)
        st.session_state["wz_seed"] = {}
        st.session_state["page"] = "cv"
        st.rerun()

# =========================
# CARGAR DESDE SHEETS
# =========================
if not st.session_state.get("loaded", False):
    try:
        wss = {sk: get_ws(SECTIONS[sk]["ws"]) for sk in SECTION_ORDER}
        for sk in SECTION_ORDER:
            ensure_headers(wss[sk], SECTIONS[sk]["save_cols"])
        for sk in SECTION_ORDER:
            saved = load_user_df(wss[sk], user_id)
            st.session_state[SECTIONS[sk]["df_key"]] = to_editor_df(saved, sk)

        st.session_state["loaded"] = True
        st.session_state["page"] = "cv"
        st.rerun()

    except Exception as e:
        st.error(
            "No pude cargar desde Google Sheets. Revisa permisos, SHEET_ID, secrets y que las "
            "pestañas persona1 / persona2 / dupla estén bien."
        )
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
        st.session_state["wizard_nonce"] += 1
        st.session_state["wz_mode"] = "add"
        st.session_state["wz_seed"] = {}
        st.session_state["wz_section"] = None
        st.session_state["wz_edit_index"] = -1
        st.session_state["page"] = "add"
        st.rerun()

with nav2:
    if st.button("🛠️ Gestionar / Editar logros", use_container_width=True):
        st.session_state["page"] = "manage"
        st.rerun()

st.divider()

# =========================
# WIZARD (sin st.form: condicionales en vivo)
# =========================
def wizard_render(mode: str):
    nonce = st.session_state["wizard_nonce"]
    seed = st.session_state.get("wz_seed", {})

    def wk(f):
        return f"wz{nonce}_{f}"

    def sb(label, field, options, default=None, help=None):
        if default is None:
            default = options[0]
        k = wk(field)
        if k not in st.session_state:
            v = seed.get(field, default)
            if v not in options:
                v = default
            st.session_state[k] = v
        elif st.session_state[k] not in options:
            st.session_state[k] = default
        return st.selectbox(label, options=options, key=k, help=help)

    def tb(label, field, default="", help=None):
        k = wk(field)
        if k not in st.session_state:
            st.session_state[k] = str(seed.get(field, default) or "")
        return st.text_input(label, key=k, help=help)

    def yr(field):
        k = wk(field)
        if k not in st.session_state:
            v = parse_int_or_none(seed.get(field, CURRENT_YEAR))
            if v is None or v < 1990 or v > CURRENT_YEAR + 1:
                v = CURRENT_YEAR
            st.session_state[k] = v
        return st.number_input("Año", min_value=1990, max_value=CURRENT_YEAR + 1, step=1, key=k)

    def salas(field):
        k = wk(field)
        if k not in st.session_state:
            v = parse_int_or_none(seed.get(field, "")) or 10
            if v < 1:
                v = 10
            st.session_state[k] = v
        return st.number_input(
            "Número de salas del torneo",
            min_value=1, max_value=300, step=1, key=k,
            help="Cuántas salas (debates simultáneos por ronda) tuvo el torneo."
        )

    st.header("Añadir logro" if mode == "add" else "Editar logro")

    if mode == "add":
        section_label = sb(
            "¿A qué CV pertenece este logro?",
            "section_label",
            [SELECT] + [SECTIONS[s]["label"] for s in SECTION_ORDER]
        )
        section_key = label_to_section(section_label)
    else:
        section_key = st.session_state.get("wz_section")
        st.text_input(
            "CV",
            value=SECTIONS[section_key]["label"] if section_key else "",
            disabled=True
        )
        st.info(
            "No puedes mover un logro de un CV a otro desde aquí. "
            "Si necesitas moverlo, elimínalo y créalo en el CV correcto."
        )

    is_dupla = bool(section_key and SECTIONS[section_key]["is_dupla"])

    st.divider()

    pick = sb("Torneo", "tournament_pick", tournament_options())
    if pick == TOURNAMENT_OTHER:
        tb("Si elegiste OTRO, escribe el nombre del torneo", "tournament_other")

    yr("year")
    sb("Formato", "format", FORMAT_OPTIONS)

    if pick == TOURNAMENT_OTHER:
        sb("¿El torneo era novato o temático?", "is_novato_tematico", YES_NO_OPTIONS)

    # salas: solo si el peso depende de ellas
    d_now = collect_wizard_values(is_dupla, wk)
    if needs_salas(d_now):
        salas("num_salas")

    tb("Link de tab", "tab_link")

    if is_dupla:
        tb("Nombre de Persona 1 en tab", "name_on_tab")
        tb("Nombre de Persona 2 en tab", "name_on_tab_p2")
    else:
        tb("Nombre en tab", "name_on_tab")

    tb("Nombre del equipo", "team_name")

    br = sb("¿Hubo break?", "break", YES_NO_OPTIONS)
    if br == "Sí":
        sb("Ronda más lejana debatida", "furthest_round_spoken", ROUND_SPK_OPTIONS)

    tb("Ranking de equipo", "team_rank")

    if is_dupla:
        tb("Ranking de oradora de Persona 1", "speaker_rank")
        tb("Ranking de oradora de Persona 2", "speaker_rank_p2")
    else:
        tb("Ranking de oradora", "speaker_rank")

    st.divider()
    boton = "➕ Añadir logro" if mode == "add" else "💾 Guardar cambios"

    if st.button(boton, use_container_width=True, key=f"wizard_submit_{mode}"):
        try:
            if not section_key:
                raise ValueError("Elige a qué CV pertenece el logro.")

            d = collect_wizard_values(is_dupla, wk)
            validate_wizard_values(d, is_dupla)
            normalize_wizard(d, is_dupla)

            if mode == "add":
                push_row(section_key, d, mode="add")
            else:
                push_row(section_key, d, mode="edit", edit_index=int(st.session_state.get("wz_edit_index", -1)))

            res = with_save_lock(current_user(), lambda: guardar_cv())
            if res is None:
                st.stop()

            st.session_state["page"] = "cv" if mode == "add" else "manage"
            st.success("Logro guardado automáticamente ✅")
            st.rerun()

        except Exception as e:
            st.error(str(e))
            st.stop()

# =========================
# PAGE: MANAGE
# =========================
def manage_page():
    st.header("Gestionar / Editar logros")
    st.caption("Puedes editar o eliminar logros. No se puede mover un logro de un CV a otro desde aquí.")

    _mt = st.session_state.get("manage_type", "p1")
    if _mt not in SECTION_ORDER:
        _mt = "p1"

    typ = st.selectbox(
        "CV",
        options=SECTION_ORDER,
        index=SECTION_ORDER.index(_mt),
        format_func=lambda x: SECTIONS[x]["label"],
        key="manage_type_select"
    )
    st.session_state["manage_type"] = typ

    cfg = SECTIONS[typ]
    df = st.session_state[cfg["df_key"]].copy()

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
    display_cols = [c for c in cfg["edit_cols"] if c not in ("tournament_pick", "tournament_other")]
    display_cols = ["tournament"] + [c for c in display_cols if c != "tournament"]
    label_map = LABEL_DUPLA if cfg["is_dupla"] else LABEL_COMMON
    st.dataframe(preview[display_cols].rename(columns=label_map), use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns([1, 1, 2])

    with c1:
        if st.button("✏️ Editar", use_container_width=True):
            seed = {c: r.get(c, "") for c in cfg["edit_cols"]}
            st.session_state["wizard_nonce"] += 1
            st.session_state["wz_mode"] = "edit"
            st.session_state["wz_seed"] = seed
            st.session_state["wz_section"] = typ
            st.session_state["wz_edit_index"] = int(chosen)
            st.session_state["page"] = "edit"
            st.rerun()

    with c2:
        if st.button("🗑️ Eliminar", use_container_width=True):
            try:
                idx = int(chosen)
                df2 = df.drop(df.index[idx]).reset_index(drop=True)
                st.session_state[cfg["df_key"]] = df2.copy()

                res = with_save_lock(current_user(), lambda: guardar_cv())
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
            "El orden en el que ingresas los logros no afecta su calificación. "
            "Si quieres cambiar el orden, debes borrarlos y volver a ingresarlos."
        )

# =========================
# ETIQUETAS PARA TABLAS
# =========================
LABEL_COMMON = {
    "tournament": "Torneo",
    "year": "Año",
    "name_on_tab": "Nombre en tab",
    "tab_link": "Link de tab",
    "format": "Formato",
    "team_name": "Equipo",
    "break": "¿Hubo break?",
    "furthest_round_spoken": "Ronda más lejana debatida",
    "speaker_rank": "Ranking de oradora",
    "speaker_rank_p2": "Ranking de oradora P2",
    "team_rank": "Ranking de equipo",
    "num_salas": "N° de salas",
    "is_novato_tematico": "Novato/temático",
}
LABEL_DUPLA = dict(LABEL_COMMON)
LABEL_DUPLA["name_on_tab"] = "Nombre P1 en tab"
LABEL_DUPLA["name_on_tab_p2"] = "Nombre P2 en tab"
LABEL_DUPLA["speaker_rank"] = "Rank oradora P1"
LABEL_DUPLA["speaker_rank_p2"] = "Rank oradora P2"

# =========================
# ROUTER
# =========================
if st.session_state["page"] == "add":
    if st.button("⬅️ Volver", key="back_add"):
        st.session_state["page"] = "cv"
        st.rerun()
    wizard_render(mode="add")

elif st.session_state["page"] == "manage":
    manage_page()

elif st.session_state["page"] == "edit":
    if st.session_state.get("wz_edit_index", -1) is None or int(st.session_state.get("wz_edit_index", -1)) < 0:
        st.session_state["page"] = "manage"
        st.rerun()

    if st.button("⬅️ Volver", key="back_edit"):
        st.session_state["page"] = "manage"
        st.rerun()

    wizard_render(mode="edit")

else:
    # =========================
    # PAGE: CV
    # =========================
    with st.expander("¿Cómo se llena este CV? (léelo antes de empezar)", expanded=False):
        st.markdown(
            "- Este es un proceso de **postulación**. Llenan **tres CV**: el de **Persona 1**, el de "
            "**Persona 2** y el de la **Dupla** (torneos en los que debatieron juntas). Cada CV admite "
            f"hasta **{MAX_ROWS} logros**.\n"
            "- En el CV de **Dupla** se piden los nombres de **ambas** oradoras en tab. En los CV "
            "individuales, solo el de esa persona.\n"
            "- **Solo cuentan los torneos en los que hiciste break.** Si **no hubo break**, el logro se "
            "registra igual (la ronda más lejana queda opcional), pero tiene el **menor peso**.\n"
            "- **Cómo se valoran los torneos**, de mayor a menor peso: 1) los **Mundiales de BP**; "
            "2) los **torneos clasificatorios al RRH**; 3) el resto se valora según su **número de salas**, "
            "y los torneos **temáticos o novatos** quedan al final.\n"
            "- Por eso, en torneos que no están en la lista te preguntamos si fue **novato/temático** y, "
            "si no lo fue, te pedimos el **número de salas**."
        )

    st.subheader(f"CV de Persona 1 (máximo {MAX_ROWS})")
    render_readonly_table(st.session_state["p1_df"], "p1", LABEL_COMMON)

    st.divider()

    st.subheader(f"CV de Persona 2 (máximo {MAX_ROWS})")
    render_readonly_table(st.session_state["p2_df"], "p2", LABEL_COMMON)

    st.divider()

    st.subheader(f"CV de Dupla (máximo {MAX_ROWS})")
    render_readonly_table(st.session_state["dupla_df"], "dupla", LABEL_DUPLA)

    st.divider()
    st.subheader("Guardar")

    if st.button("✅ Guardar todo", use_container_width=True):
        try:
            result = with_save_lock(current_user(), lambda: guardar_cv())
            if result is None:
                st.stop()
            st.success(
                "Guardado correctamente ✅ | "
                f"Persona 1={result['p1']} | Persona 2={result['p2']} | Dupla={result['dupla']}"
            )
        except Exception as e:
            st.error("No se pudo guardar. Revisa permisos, encabezados, SHEET_ID y secrets.")
            st.exception(e)