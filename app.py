# -*- coding: utf-8 -*-
"""
==================================================================================
 APP MULTIPROYECTO DE INSPECCIÓN Y MONITOREO PATOLÓGICO ESTRUCTURAL EDILICIO
==================================================================================
Autor: Generado para uso en inspecciones de Ingeniería Civil
Stack: Streamlit + Plotly + Pandas + Pillow + PyPDF2 / pdf2image + SQLite

Ejecutar localmente:
    streamlit run app.py

Desplegar en Streamlit Community Cloud: ver instrucciones en README / chat.
==================================================================================
"""

import os
import io
import base64
import sqlite3
import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image

try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_OK = True
except Exception:
    PDF2IMAGE_OK = False

try:
    import PyPDF2  # se usa para leer metadatos / cantidad de páginas del PDF
    PYPDF2_OK = True
except Exception:
    PYPDF2_OK = False


# ==================================================================================
# CONFIGURACIÓN GENERAL Y RUTAS
# ==================================================================================

st.set_page_config(
    page_title="Monitoreo Patológico Estructural",
    page_icon="🏗️",
    layout="wide",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "patologias.db")
FOTOS_DIR = os.path.join(BASE_DIR, "fotos_inspecciones")
PLANOS_DIR = os.path.join(BASE_DIR, "planos")

os.makedirs(FOTOS_DIR, exist_ok=True)
os.makedirs(PLANOS_DIR, exist_ok=True)

# Línea de control según ACI 224R (fisuración admisible orientativa) en mm
ACI_224R_LIMITE_MM = 0.30

TIPOS_LESION = ["Fisura", "Grieta", "Humedad", "Desprendimiento", "Otra"]
ESTADOS_LESION = ["Activa", "Aparentemente Estabilizada"]
INCIDENCIAS = ["Sin incidencia aparente", "Leve", "Moderada", "Alta / Compromiso estructural"]
CONDICIONES_AMBIENTALES = ["Interior seco", "Interior húmedo", "Exterior expuesto",
                            "Exterior con humedad permanente", "Zona con vibraciones", "Otra"]

# Credenciales de acceso (para producción real, mover a st.secrets)
USUARIOS_VALIDOS = {
    "iafas_admin": "Mantenimiento2026",
}


# ==================================================================================
# BASE DE DATOS
# ==================================================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS proyectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            descripcion TEXT,
            creado_en TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS planos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL,
            nombre TEXT,
            ruta_archivo TEXT,
            subido_en TEXT,
            FOREIGN KEY (proyecto_id) REFERENCES proyectos(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS puntos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL,
            plano_id INTEGER NOT NULL,
            etiqueta TEXT,
            ubicacion_especifica TEXT,
            x_pct REAL,
            y_pct REAL,
            creado_en TEXT,
            FOREIGN KEY (proyecto_id) REFERENCES proyectos(id),
            FOREIGN KEY (plano_id) REFERENCES planos(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inspecciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            punto_id INTEGER NOT NULL,
            fecha TEXT,
            tipo_lesion TEXT,
            ancho_mm REAL,
            longitud_m REAL,
            area_m2 REAL,
            extension TEXT,
            estado TEXT,
            incidencia_estructural TEXT,
            condiciones_ambientales TEXT,
            intervenciones_previas TEXT,
            descripcion TEXT,
            observaciones TEXT,
            foto_path TEXT,
            creado_en TEXT,
            FOREIGN KEY (punto_id) REFERENCES puntos(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS informes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL,
            punto_id INTEGER,
            titulo TEXT,
            diagnostico TEXT,
            gravedad_riesgo TEXT,
            estado_actividad TEXT,
            pronostico TEXT,
            propuesta_solucion TEXT,
            creado_en TEXT,
            FOREIGN KEY (proyecto_id) REFERENCES proyectos(id),
            FOREIGN KEY (punto_id) REFERENCES puntos(id)
        )
    """)

    conn.commit()
    conn.close()


# ---------- helpers de acceso a datos ----------

def listar_proyectos():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM proyectos ORDER BY nombre", conn)
    conn.close()
    return df


def crear_proyecto(nombre, descripcion):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO proyectos (nombre, descripcion, creado_en) VALUES (?, ?, ?)",
        (nombre.strip(), descripcion.strip(), dt.datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def listar_planos(proyecto_id):
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM planos WHERE proyecto_id = ? ORDER BY subido_en DESC",
        conn, params=(proyecto_id,),
    )
    conn.close()
    return df


def guardar_plano(proyecto_id, nombre, ruta_archivo):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO planos (proyecto_id, nombre, ruta_archivo, subido_en) VALUES (?, ?, ?, ?)",
        (proyecto_id, nombre, ruta_archivo, dt.datetime.now().isoformat()),
    )
    conn.commit()
    plano_id = cur.lastrowid
    conn.close()
    return plano_id


def listar_puntos(proyecto_id, plano_id=None):
    conn = get_conn()
    if plano_id:
        df = pd.read_sql_query(
            "SELECT * FROM puntos WHERE proyecto_id = ? AND plano_id = ? ORDER BY creado_en",
            conn, params=(proyecto_id, plano_id),
        )
    else:
        df = pd.read_sql_query(
            "SELECT * FROM puntos WHERE proyecto_id = ? ORDER BY creado_en",
            conn, params=(proyecto_id,),
        )
    conn.close()
    return df


def crear_punto(proyecto_id, plano_id, etiqueta, ubicacion, x_pct, y_pct):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO puntos (proyecto_id, plano_id, etiqueta, ubicacion_especifica, x_pct, y_pct, creado_en)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (proyecto_id, plano_id, etiqueta, ubicacion, x_pct, y_pct, dt.datetime.now().isoformat()))
    conn.commit()
    punto_id = cur.lastrowid
    conn.close()
    return punto_id


def crear_inspeccion(datos):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO inspecciones (
            punto_id, fecha, tipo_lesion, ancho_mm, longitud_m, area_m2, extension,
            estado, incidencia_estructural, condiciones_ambientales, intervenciones_previas,
            descripcion, observaciones, foto_path, creado_en
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datos["punto_id"], datos["fecha"], datos["tipo_lesion"], datos["ancho_mm"],
        datos["longitud_m"], datos["area_m2"], datos["extension"], datos["estado"],
        datos["incidencia_estructural"], datos["condiciones_ambientales"],
        datos["intervenciones_previas"], datos["descripcion"], datos["observaciones"],
        datos["foto_path"], dt.datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


def listar_inspecciones(proyecto_id):
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT i.*, p.etiqueta AS punto_etiqueta, p.ubicacion_especifica
        FROM inspecciones i
        JOIN puntos p ON p.id = i.punto_id
        WHERE p.proyecto_id = ?
        ORDER BY i.fecha
    """, conn, params=(proyecto_id,))
    conn.close()
    return df


def guardar_informe(datos):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO informes (
            proyecto_id, punto_id, titulo, diagnostico, gravedad_riesgo,
            estado_actividad, pronostico, propuesta_solucion, creado_en
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datos["proyecto_id"], datos["punto_id"], datos["titulo"], datos["diagnostico"],
        datos["gravedad_riesgo"], datos["estado_actividad"], datos["pronostico"],
        datos["propuesta_solucion"], dt.datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


def listar_informes(proyecto_id):
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM informes WHERE proyecto_id = ? ORDER BY creado_en DESC",
        conn, params=(proyecto_id,),
    )
    conn.close()
    return df


# ==================================================================================
# UTILIDADES DE ARCHIVOS: PLANOS (PDF/IMG) Y FOTOS
# ==================================================================================

def slugify(texto):
    return "".join(c if c.isalnum() else "_" for c in texto).strip("_")


def guardar_archivo_plano(uploaded_file, proyecto_nombre):
    carpeta = os.path.join(PLANOS_DIR, slugify(proyecto_nombre))
    os.makedirs(carpeta, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_final = f"{timestamp}_{uploaded_file.name}"
    ruta = os.path.join(carpeta, nombre_final)
    with open(ruta, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return ruta


def guardar_archivo_foto(uploaded_file, proyecto_nombre, etiqueta_punto):
    carpeta = os.path.join(FOTOS_DIR, slugify(proyecto_nombre), slugify(etiqueta_punto))
    os.makedirs(carpeta, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_final = f"{timestamp}_{uploaded_file.name}"
    ruta = os.path.join(carpeta, nombre_final)
    with open(ruta, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return ruta


@st.cache_data(show_spinner=False)
def cargar_imagen_desde_ruta(ruta_archivo):
    """
    Convierte el archivo de plano (PDF o imagen) en un objeto PIL.Image.
    Se cachea por ruta de archivo para evitar reconversiones costosas de PDF.
    """
    ext = os.path.splitext(ruta_archivo)[1].lower()

    if ext == ".pdf":
        with open(ruta_archivo, "rb") as f:
            pdf_bytes = f.read()

        if not PDF2IMAGE_OK:
            raise RuntimeError(
                "pdf2image / poppler no está disponible en este entorno. "
                "Agregá 'poppler-utils' a packages.txt para desplegar en Streamlit Cloud."
            )

        paginas = convert_from_bytes(pdf_bytes, dpi=150, first_page=1, last_page=1)
        imagen = paginas[0].convert("RGB")
        return imagen

    else:
        imagen = Image.open(ruta_archivo).convert("RGB")
        return imagen


def imagen_a_data_uri(imagen: Image.Image) -> str:
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


# ==================================================================================
# GRÁFICOS
# ==================================================================================

def construir_figura_plano(imagen: Image.Image, puntos_df: pd.DataFrame, punto_resaltado_id=None):
    """Arma la figura de Plotly con el plano de fondo y los puntos geolocalizados."""
    ancho, alto = imagen.size
    data_uri = imagen_a_data_uri(imagen)

    fig = go.Figure()

    fig.add_layout_image(
        dict(
            source=data_uri,
            xref="x", yref="y",
            x=0, y=alto,
            sizex=ancho, sizey=alto,
            sizing="stretch",
            layer="below",
        )
    )

    if puntos_df is not None and not puntos_df.empty:
        xs = puntos_df["x_pct"] / 100.0 * ancho
        ys = alto - (puntos_df["y_pct"] / 100.0 * alto)  # invertir eje Y (imagen vs plotly)
        colores = [
            "#e74c3c" if pid == punto_resaltado_id else "#2980b9"
            for pid in puntos_df["id"]
        ]
        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            mode="markers+text",
            marker=dict(size=16, color=colores, line=dict(width=2, color="white")),
            text=puntos_df["etiqueta"],
            textposition="top center",
            hovertext=puntos_df["ubicacion_especifica"],
            hoverinfo="text+x+y",
            name="Puntos de inspección",
        ))

    fig.update_xaxes(visible=False, range=[0, ancho])
    fig.update_yaxes(visible=False, range=[0, alto], scaleanchor="x", scaleratio=1)
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=650,
        showlegend=False,
        dragmode="pan",
    )
    return fig


def construir_grafico_evolucion(df_punto: pd.DataFrame, etiqueta_punto: str):
    df_punto = df_punto.sort_values("fecha")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_punto["fecha"], y=df_punto["ancho_mm"],
        mode="lines+markers",
        name="Ancho de fisura (mm)",
        line=dict(color="#2980b9", width=3),
        marker=dict(size=9),
    ))
    fig.add_hline(
        y=ACI_224R_LIMITE_MM,
        line_dash="dash",
        line_color="#e74c3c",
        annotation_text=f"Límite orientativo ACI 224R ({ACI_224R_LIMITE_MM} mm)",
        annotation_position="top left",
    )
    fig.update_layout(
        title=f"Evolución temporal — {etiqueta_punto}",
        xaxis_title="Fecha de inspección",
        yaxis_title="Ancho de fisura (mm)",
        height=420,
        margin=dict(l=40, r=20, t=60, b=40),
    )
    return fig


# ==================================================================================
# AUTENTICACIÓN
# ==================================================================================

def pantalla_login():
    st.title("🏗️ Monitoreo Patológico Estructural Edilicio")
    st.caption("Ingresá con tus credenciales para acceder a la plataforma.")

    with st.form("login_form"):
        usuario = st.text_input("Usuario")
        clave = st.text_input("Contraseña", type="password")
        enviado = st.form_submit_button("Ingresar", use_container_width=True)

    if enviado:
        if usuario in USUARIOS_VALIDOS and USUARIOS_VALIDOS[usuario] == clave:
            st.session_state["autenticado"] = True
            st.session_state["usuario"] = usuario
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")


def cerrar_sesion():
    for key in ["autenticado", "usuario", "proyecto_id", "proyecto_nombre", "plano_id"]:
        st.session_state.pop(key, None)
    st.rerun()


# ==================================================================================
# SELECTOR / CREADOR DE PROYECTOS (SIDEBAR)
# ==================================================================================

def panel_proyectos():
    st.sidebar.header("📁 Proyecto")

    proyectos_df = listar_proyectos()

    opciones = ["— Seleccionar proyecto —"] + proyectos_df["nombre"].tolist() if not proyectos_df.empty else ["— Seleccionar proyecto —"]
    seleccion = st.sidebar.selectbox("Proyecto activo", opciones)

    if seleccion != "— Seleccionar proyecto —":
        fila = proyectos_df[proyectos_df["nombre"] == seleccion].iloc[0]
        st.session_state["proyecto_id"] = int(fila["id"])
        st.session_state["proyecto_nombre"] = fila["nombre"]

    with st.sidebar.expander("➕ Crear nuevo proyecto"):
        nombre_nuevo = st.text_input("Nombre del proyecto", key="nombre_nuevo_proyecto")
        desc_nueva = st.text_area("Descripción (opcional)", key="desc_nuevo_proyecto", height=80)
        if st.button("Crear proyecto", key="btn_crear_proyecto"):
            if nombre_nuevo.strip():
                try:
                    crear_proyecto(nombre_nuevo, desc_nueva)
                    st.success(f"Proyecto '{nombre_nuevo}' creado.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Ya existe un proyecto con ese nombre.")
            else:
                st.warning("Ingresá un nombre para el proyecto.")

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Usuario conectado: **{st.session_state.get('usuario', '')}**")
    if st.sidebar.button("Cerrar sesión"):
        cerrar_sesion()


# ==================================================================================
# TAB 1: PLANO Y PUNTOS
# ==================================================================================

def tab_plano_y_puntos(proyecto_id, proyecto_nombre):
    st.subheader("🗺️ Plano interactivo y geolocalización de puntos")

    col_upload, col_info = st.columns([2, 1])
    with col_upload:
        archivo_plano = st.file_uploader(
            "Subir plano (PDF, PNG o JPG)", type=["pdf", "png", "jpg", "jpeg"],
            key="uploader_plano",
        )
        if archivo_plano is not None:
            if st.button("Guardar este plano en el proyecto"):
                ruta = guardar_archivo_plano(archivo_plano, proyecto_nombre)
                guardar_plano(proyecto_id, archivo_plano.name, ruta)
                st.success("Plano guardado correctamente.")
                st.rerun()

    planos_df = listar_planos(proyecto_id)
    if planos_df.empty:
        st.info("Todavía no hay planos cargados para este proyecto. Subí uno arriba para empezar.")
        return

    with col_info:
        nombres_planos = planos_df["nombre"] + " (" + planos_df["subido_en"].str.slice(0, 10) + ")"
        idx_sel = st.selectbox(
            "Plano activo", range(len(planos_df)),
            format_func=lambda i: nombres_planos.iloc[i],
        )
        plano_actual = planos_df.iloc[idx_sel]
        st.session_state["plano_id"] = int(plano_actual["id"])

    try:
        imagen = cargar_imagen_desde_ruta(plano_actual["ruta_archivo"])
    except Exception as e:
        st.error(f"No se pudo renderizar el plano: {e}")
        return

    puntos_df = listar_puntos(proyecto_id, plano_id=int(plano_actual["id"]))

    fig = construir_figura_plano(imagen, puntos_df)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### ➕ Agregar nuevo punto de inspección")
    st.caption(
        "Ubicá el punto indicando su posición relativa sobre el plano (en % del ancho y alto). "
        "El marcador de vista previa se actualiza abajo antes de guardar."
    )

    col1, col2 = st.columns(2)
    with col1:
        x_pct = st.slider("Posición horizontal (%)", 0.0, 100.0, 50.0, step=0.5, key="x_pct_nuevo")
    with col2:
        y_pct = st.slider("Posición vertical (%)", 0.0, 100.0, 50.0, step=0.5, key="y_pct_nuevo")

    preview_df = pd.DataFrame([{
        "id": -1, "etiqueta": "Nuevo punto", "ubicacion_especifica": "",
        "x_pct": x_pct, "y_pct": y_pct,
    }])
    if not puntos_df.empty:
        preview_df = pd.concat([puntos_df, preview_df], ignore_index=True)

    fig_preview = construir_figura_plano(imagen, preview_df, punto_resaltado_id=-1)
    st.plotly_chart(fig_preview, use_container_width=True, key="preview_plot")

    with st.form("form_nuevo_punto"):
        etiqueta = st.text_input("Etiqueta / identificador del punto (ej. F-01, Muro Norte)")
        ubicacion = st.text_input("Ubicación específica (ej. Planta baja, muro perimetral este)")
        crear = st.form_submit_button("Guardar punto en el plano")

    if crear:
        if etiqueta.strip():
            crear_punto(proyecto_id, int(plano_actual["id"]), etiqueta.strip(), ubicacion.strip(), x_pct, y_pct)
            st.success(f"Punto '{etiqueta}' creado correctamente.")
            st.rerun()
        else:
            st.warning("La etiqueta del punto es obligatoria.")


# ==================================================================================
# TAB 2: NUEVA INSPECCIÓN (FICHA PATOLÓGICA)
# ==================================================================================

def tab_nueva_inspeccion(proyecto_id, proyecto_nombre):
    st.subheader("📝 Ficha de inspección patológica")

    puntos_df = listar_puntos(proyecto_id)
    if puntos_df.empty:
        st.info("Primero creá al menos un punto de inspección en la pestaña 'Plano y Puntos'.")
        return

    etiquetas = puntos_df["etiqueta"] + " — " + puntos_df["ubicacion_especifica"].fillna("")
    idx_sel = st.selectbox("Punto a inspeccionar", range(len(puntos_df)), format_func=lambda i: etiquetas.iloc[i])
    punto_sel = puntos_df.iloc[idx_sel]

    with st.form("form_inspeccion", clear_on_submit=True):
        st.markdown("##### Datos generales")
        c1, c2 = st.columns(2)
        with c1:
            fecha = st.date_input("Fecha de inspección", value=dt.date.today())
            tipo_lesion = st.selectbox("Tipo de lesión", TIPOS_LESION)
            ancho_mm = st.number_input("Ancho (mm)", min_value=0.0, step=0.01, format="%.2f")
        with c2:
            longitud_m = st.number_input("Longitud (m)", min_value=0.0, step=0.01, format="%.2f")
            area_m2 = st.number_input("Área (m²)", min_value=0.0, step=0.01, format="%.2f")
            extension = st.text_input("Extensión (descripción, ej. 'de piso a techo')")

        st.markdown("##### Estado y entorno")
        c3, c4 = st.columns(2)
        with c3:
            estado = st.selectbox("Estado", ESTADOS_LESION)
            incidencia = st.selectbox("Incidencia estructural aparente", INCIDENCIAS)
        with c4:
            condiciones = st.selectbox("Condiciones ambientales", CONDICIONES_AMBIENTALES)
            intervenciones = st.text_input("Intervenciones previas (si las hubo)")

        st.markdown("##### Descripción")
        descripcion = st.text_area("Descripción general (corta y concisa)", height=80)
        observaciones = st.text_area("Observaciones libres", height=100)

        st.markdown("##### Registro fotográfico")
        foto = st.file_uploader("Foto de inspección semanal", type=["png", "jpg", "jpeg"])

        enviar = st.form_submit_button("Guardar inspección", use_container_width=True)

    if enviar:
        foto_path = ""
        if foto is not None:
            foto_path = guardar_archivo_foto(foto, proyecto_nombre, punto_sel["etiqueta"])

        datos = {
            "punto_id": int(punto_sel["id"]),
            "fecha": fecha.isoformat(),
            "tipo_lesion": tipo_lesion,
            "ancho_mm": ancho_mm,
            "longitud_m": longitud_m,
            "area_m2": area_m2,
            "extension": extension,
            "estado": estado,
            "incidencia_estructural": incidencia,
            "condiciones_ambientales": condiciones,
            "intervenciones_previas": intervenciones,
            "descripcion": descripcion,
            "observaciones": observaciones,
            "foto_path": foto_path,
        }
        crear_inspeccion(datos)
        st.success(f"Inspección registrada para el punto '{punto_sel['etiqueta']}'.")


# ==================================================================================
# TAB 3: EVOLUCIÓN Y GRÁFICOS
# ==================================================================================

def tab_evolucion(proyecto_id):
    st.subheader("📈 Evolución temporal por punto")

    inspecciones_df = listar_inspecciones(proyecto_id)
    if inspecciones_df.empty:
        st.info("Todavía no hay inspecciones registradas en este proyecto.")
        return

    puntos_unicos = inspecciones_df[["punto_id", "punto_etiqueta"]].drop_duplicates()
    idx_sel = st.selectbox(
        "Seleccioná el punto a analizar", range(len(puntos_unicos)),
        format_func=lambda i: puntos_unicos["punto_etiqueta"].iloc[i],
    )
    punto_id_sel = int(puntos_unicos["punto_id"].iloc[idx_sel])
    etiqueta_sel = puntos_unicos["punto_etiqueta"].iloc[idx_sel]

    df_punto = inspecciones_df[inspecciones_df["punto_id"] == punto_id_sel].copy()
    df_punto["fecha"] = pd.to_datetime(df_punto["fecha"])

    fig = construir_grafico_evolucion(df_punto, etiqueta_sel)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### Historial fotográfico cronológico")
    for _, fila in df_punto.sort_values("fecha", ascending=False).iterrows():
        with st.expander(f"{fila['fecha'].date()} — {fila['tipo_lesion']} ({fila['ancho_mm']} mm)"):
            c1, c2 = st.columns([1, 2])
            with c1:
                if fila["foto_path"] and os.path.exists(fila["foto_path"]):
                    st.image(fila["foto_path"], use_container_width=True)
                else:
                    st.caption("Sin foto asociada.")
            with c2:
                st.write(f"**Estado:** {fila['estado']}")
                st.write(f"**Incidencia estructural:** {fila['incidencia_estructural']}")
                st.write(f"**Condiciones ambientales:** {fila['condiciones_ambientales']}")
                st.write(f"**Intervenciones previas:** {fila['intervenciones_previas']}")
                st.write(f"**Descripción:** {fila['descripcion']}")
                st.write(f"**Observaciones:** {fila['observaciones']}")


# ==================================================================================
# TAB 4: TABLA Y EXPORTACIÓN
# ==================================================================================

def tab_tabla_exportacion(proyecto_id, proyecto_nombre):
    st.subheader("📊 Registro acumulado de inspecciones")

    inspecciones_df = listar_inspecciones(proyecto_id)
    if inspecciones_df.empty:
        st.info("Todavía no hay inspecciones registradas en este proyecto.")
        return

    columnas_mostrar = [
        "fecha", "punto_etiqueta", "ubicacion_especifica", "tipo_lesion",
        "ancho_mm", "longitud_m", "area_m2", "extension", "estado",
        "incidencia_estructural", "condiciones_ambientales", "intervenciones_previas",
        "descripcion", "observaciones",
    ]
    df_mostrar = inspecciones_df[columnas_mostrar].rename(columns={
        "fecha": "Fecha", "punto_etiqueta": "Punto", "ubicacion_especifica": "Ubicación específica",
        "tipo_lesion": "Tipo de lesión", "ancho_mm": "Ancho (mm)", "longitud_m": "Longitud (m)",
        "area_m2": "Área (m²)", "extension": "Extensión", "estado": "Estado",
        "incidencia_estructural": "Incidencia estructural", "condiciones_ambientales": "Condiciones ambientales",
        "intervenciones_previas": "Intervenciones previas", "descripcion": "Descripción",
        "observaciones": "Observaciones",
    })

    st.dataframe(df_mostrar, use_container_width=True, height=450)

    col_csv, col_xlsx = st.columns(2)
    with col_csv:
        csv_bytes = df_mostrar.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "⬇️ Descargar CSV", data=csv_bytes,
            file_name=f"planilla_{slugify(proyecto_nombre)}.csv",
            mime="text/csv", use_container_width=True,
        )
    with col_xlsx:
        buffer_xlsx = io.BytesIO()
        with pd.ExcelWriter(buffer_xlsx, engine="xlsxwriter") as writer:
            df_mostrar.to_excel(writer, index=False, sheet_name="Inspecciones")
        st.download_button(
            "⬇️ Descargar Excel", data=buffer_xlsx.getvalue(),
            file_name=f"planilla_{slugify(proyecto_nombre)}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


# ==================================================================================
# TAB 5: INFORME TÉCNICO Y DIAGNÓSTICO
# ==================================================================================

def tab_informe_tecnico(proyecto_id, proyecto_nombre):
    st.subheader("📄 Informe técnico y diagnóstico")

    puntos_df = listar_puntos(proyecto_id)
    opciones_punto = ["Informe general del proyecto"]
    if not puntos_df.empty:
        opciones_punto += puntos_df["etiqueta"].tolist()

    seleccion = st.selectbox("Alcance del informe", opciones_punto)
    punto_id = None
    if seleccion != "Informe general del proyecto":
        punto_id = int(puntos_df[puntos_df["etiqueta"] == seleccion].iloc[0]["id"])

    with st.form("form_informe"):
        titulo = st.text_input("Título del informe", value=f"Informe técnico — {proyecto_nombre}")
        diagnostico = st.text_area("Diagnóstico e hipótesis de origen", height=120)
        gravedad = st.text_area("Evaluación de gravedad y riesgo", height=100)
        estado_actividad = st.selectbox("Estado de actividad de la lesión", ["Activa", "Inactiva"])
        pronostico = st.text_area("Pronóstico en caso de no intervención", height=100)
        propuesta = st.text_area("Propuesta de solución o reparación sugerida", height=120)

        guardar = st.form_submit_button("Guardar informe", use_container_width=True)

    if guardar:
        datos = {
            "proyecto_id": proyecto_id, "punto_id": punto_id, "titulo": titulo,
            "diagnostico": diagnostico, "gravedad_riesgo": gravedad,
            "estado_actividad": estado_actividad, "pronostico": pronostico,
            "propuesta_solucion": propuesta,
        }
        guardar_informe(datos)
        st.success("Informe guardado correctamente.")

    st.markdown("---")
    st.markdown("##### Informes guardados")
    informes_df = listar_informes(proyecto_id)
    if informes_df.empty:
        st.caption("Todavía no se guardaron informes para este proyecto.")
    else:
        for _, fila in informes_df.iterrows():
            with st.expander(f"{fila['titulo']} — {fila['creado_en'][:10]}"):
                st.write(f"**Diagnóstico e hipótesis de origen:** {fila['diagnostico']}")
                st.write(f"**Evaluación de gravedad y riesgo:** {fila['gravedad_riesgo']}")
                st.write(f"**Estado de actividad:** {fila['estado_actividad']}")
                st.write(f"**Pronóstico sin intervención:** {fila['pronostico']}")
                st.write(f"**Propuesta de solución:** {fila['propuesta_solucion']}")


# ==================================================================================
# MAIN
# ==================================================================================

def main():
    init_db()

    if not st.session_state.get("autenticado", False):
        pantalla_login()
        return

    panel_proyectos()

    proyecto_id = st.session_state.get("proyecto_id")
    proyecto_nombre = st.session_state.get("proyecto_nombre")

    st.title("🏗️ Monitoreo Patológico Estructural Edilicio")

    if not proyecto_id:
        st.info("⬅️ Seleccioná o creá un proyecto en el panel lateral para comenzar.")
        return

    st.caption(f"Proyecto activo: **{proyecto_nombre}**")

    tabs = st.tabs([
        "🗺️ Plano y Puntos",
        "📝 Nueva Inspección",
        "📈 Evolución y Gráficos",
        "📊 Tabla y Exportación",
        "📄 Informe Técnico",
    ])

    with tabs[0]:
        tab_plano_y_puntos(proyecto_id, proyecto_nombre)
    with tabs[1]:
        tab_nueva_inspeccion(proyecto_id, proyecto_nombre)
    with tabs[2]:
        tab_evolucion(proyecto_id)
    with tabs[3]:
        tab_tabla_exportacion(proyecto_id, proyecto_nombre)
    with tabs[4]:
        tab_informe_tecnico(proyecto_id, proyecto_nombre)


if __name__ == "__main__":
    main()
