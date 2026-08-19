# -*- coding: utf-8 -*-
"""
==================================================================================
 APP MULTIPROYECTO DE INSPECCIÓN Y MONITOREO PATOLÓGICO ESTRUCTURAL EDILICIO
 Integrada con Supabase (Nube Persistente: DB PostgreSQL + Storage Buckets)
==================================================================================
"""

import os
import io
import base64
import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image
from supabase import create_client, Client

try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_OK = True
except Exception:
    PDF2IMAGE_OK = False

# ==================================================================================
# CONFIGURACIÓN GENERAL Y CONEXIÓN A SUPABASE
# ==================================================================================

st.set_page_config(
    page_title="Monitoreo Patológico Estructural",
    page_icon="🏗️",
    layout="wide",
)

@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")
    if not url or not key:
        st.error("⚠️ Falta configurar SUPABASE_URL y SUPABASE_KEY en los Secrets de Streamlit.")
        st.stop()
    return create_client(url, key)

supabase = init_supabase()

ACI_224R_LIMITE_MM = 0.30

TIPOS_LESION = ["Fisura", "Grieta", "Humedad", "Losa / Hormigón en Altura", "Desprendimiento", "Otra"]
TIPOS_LOSA = ["Maciza", "Alivianada / Viguetas", "Casetonada", "No aplica / Otro"]
UBICACION_LOSA = ["Intradós (Cielorraso / Fondo)", "Extradós", "Nervaduras / Viguetas", "Borde de Losa"]
SEVERIDAD_LOSA = {
    "Grado 1 - Leve (Manchas / Fisuras superficiales)": 1,
    "Grado 2 - Moderado (Manchas de óxido / Fisura en armadura)": 2,
    "Grado 3 - Avanzado (Desprendimiento inicial / Armadura expuesta)": 3,
    "Grado 4 - Severo (Desprendimiento masivo / Pérdida de sección)": 4,
}
ESTADOS_LESION = ["Activa", "Aparentemente Estabilizada"]
INCIDENCIAS = ["Sin incidencia aparente", "Leve", "Moderada", "Alta / Compromiso estructural"]
CONDICIONES_AMBIENTALES = ["Interior seco", "Interior húmedo", "Exterior expuesto",
                            "Exterior con humedad permanente", "Zona con vibraciones", "Otra"]

USUARIOS_VALIDOS = {
    "iafas_admin": "Mantenimiento2026",
}

# ==================================================================================
# FUNCIONES BASE DE DATOS (SUPABASE)
# ==================================================================================

def slugify(texto):
    return "".join(c if c.isalnum() else "_" for c in texto).strip("_")

def subir_archivo_supabase(bucket: str, path: str, file_bytes: bytes, content_type: str) -> str:
    supabase.storage.from_(bucket).upload(
        path=path,
        file=file_bytes,
        file_options={"content-type": content_type, "upsert": "true"}
    )
    res = supabase.storage.from_(bucket).get_public_url(path)
    return res

def listar_proyectos():
    res = supabase.table("proyectos").select("*").order("nombre").execute()
    return pd.DataFrame(res.data)

def crear_proyecto(nombre, descripcion):
    data = {"nombre": nombre.strip(), "descripcion": descripcion.strip()}
    supabase.table("proyectos").insert(data).execute()

def listar_planos(proyecto_id):
    res = supabase.table("planos").select("*").eq("proyecto_id", proyecto_id).order("subido_en", desc=True).execute()
    return pd.DataFrame(res.data)

def guardar_plano(proyecto_id, nombre, url_archivo):
    data = {
        "proyecto_id": proyecto_id,
        "nombre": nombre,
        "ruta_archivo": url_archivo,
    }
    supabase.table("planos").insert(data).execute()

def listar_puntos(proyecto_id, plano_id=None):
    query = supabase.table("puntos").select("*").eq("proyecto_id", proyecto_id)
    if plano_id:
        query = query.eq("plano_id", plano_id)
    res = query.order("creado_en").execute()
    return pd.DataFrame(res.data)

def crear_punto(proyecto_id, plano_id, etiqueta, ubicacion, x_pct, y_pct, tipo_categoria):
    data = {
        "proyecto_id": proyecto_id,
        "plano_id": plano_id,
        "etiqueta": etiqueta,
        "ubicacion_especifica": ubicacion,
        "x_pct": x_pct,
        "y_pct": y_pct,
        "tipo_categoria": tipo_categoria,
    }
    supabase.table("puntos").insert(data).execute()

def crear_inspeccion(datos):
    supabase.table("inspecciones").insert(datos).execute()

def listar_inspecciones(proyecto_id):
    res_puntos = supabase.table("puntos").select("id, etiqueta, ubicacion_especifica, tipo_categoria").eq("proyecto_id", proyecto_id).execute()
    df_puntos = pd.DataFrame(res_puntos.data)
    if df_puntos.empty:
        return pd.DataFrame()

    pids = df_puntos["id"].tolist()
    res_insp = supabase.table("inspecciones").select("*").in_("punto_id", pids).order("fecha").execute()
    df_insp = pd.DataFrame(res_insp.data)
    if df_insp.empty:
        return pd.DataFrame()

    df_merged = df_insp.merge(df_puntos, left_on="punto_id", right_on="id", suffixes=("", "_punto"))
    df_merged.rename(columns={"etiqueta": "punto_etiqueta", "tipo_categoria": "punto_categoria"}, inplace=True)
    return df_merged

def guardar_informe(datos):
    supabase.table("informes").insert(datos).execute()

def listar_informes(proyecto_id):
    res = supabase.table("informes").select("*").eq("proyecto_id", proyecto_id).order("creado_en", desc=True).execute()
    return pd.DataFrame(res.data)

# ==================================================================================
# LÓGICA DE SEMÁFORO Y CÓMPUTO EN EXCEL
# ==================================================================================

def calcular_nivel_riesgo(row):
    incidencia = str(row.get("incidencia_estructural", ""))
    grado_losa = row.get("grado_severidad_losa", 0) or 0
    ancho = row.get("ancho_mm", 0.0) or 0.0

    if incidencia == "Alta / Compromiso estructural" or grado_losa >= 3 or ancho > 0.30:
        return "🔴 ROJO (Urgente)"
    elif incidencia == "Moderada" or grado_losa == 2 or (0.15 <= ancho <= 0.30):
        return "🟡 AMARILLO (Atención)"
    else:
        return "🟢 VERDE (Bajo / Estable)"

def generar_excel_cotizacion(df_inspecciones, proyecto_nombre):
    buffer = io.BytesIO()
    
    total_longitud_fisuras = df_inspecciones["longitud_m"].sum() if "longitud_m" in df_inspecciones else 0.0
    total_area_afectada = df_inspecciones["area_m2"].sum() if "area_m2" in df_inspecciones else 0.0
    puntos_losa_criticos = df_inspecciones[df_inspecciones["grado_severidad_losa"] >= 2] if "grado_severidad_losa" in df_inspecciones else []
    
    items_cotizacion = [
        {
            "Ítem": "1.01",
            "Descripción de Tarea": "Picado, saneado y retiro de recubrimiento suelto/fisurado en losas a gran altura",
            "Unidad": "m²",
            "Cantidad Estimada": round(max(total_area_afectada, len(puntos_losa_criticos) * 2.5), 2),
            "Precio Unitario ($)": "",
            "Notas de Campo": "Incluye uso de andamios o silleta según relevamiento."
        },
        {
            "Ítem": "1.02",
            "Descripción de Tarea": "Limpieza manual/mecánica de armadura expuesta con cepillo de acero e pasivador anticorrosivo",
            "Unidad": "m²",
            "Cantidad Estimada": round(len(puntos_losa_criticos) * 1.5, 2),
            "Precio Unitario ($)": "",
            "Notas de Campo": "Aplicar mortero pasivador sintético sobre hierro expuesto."
        },
        {
            "Ítem": "1.03",
            "Descripción de Tarea": "Reconstrucción de recubrimiento con mortero tixotrópico de reparación estructural",
            "Unidad": "m²",
            "Cantidad Estimada": round(max(total_area_afectada, len(puntos_losa_criticos) * 2.5), 2),
            "Precio Unitario ($)": "",
            "Notas de Campo": "Restablecer geometría original de la losa."
        },
        {
            "Ítem": "2.01",
            "Descripción de Tarea": "Sellado de fisuras y grietas con masilla/resina elástica de poliuretano",
            "Unidad": "m",
            "Cantidad Estimada": round(max(total_longitud_fisuras, 10.0), 2),
            "Precio Unitario ($)": "",
            "Notas de Campo": "Apertura en 'V' previo al sellado sintético."
        },
        {
            "Ítem": "3.01",
            "Descripción de Tarea": "Provisión y armado de estructura de andamios / equipos de seguridad para trabajos en altura",
            "Unidad": "Gl",
            "Cantidad Estimada": 1.0,
            "Precio Unitario ($)": "",
            "Notas de Campo": "Global por sector según zonas rojas identificadas."
        }
    ]

    df_cotiz = pd.DataFrame(items_cotizacion)

    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_cotiz.to_excel(writer, sheet_name="Orden de Trabajo - Cotizador", index=False)
        
        df_detalle = df_inspecciones.copy()
        df_detalle["Semaforo_Riesgo"] = df_detalle.apply(calcular_nivel_riesgo, axis=1)
        df_detalle.to_excel(writer, sheet_name="Relevamiento de Campo", index=False)

        workbook = writer.book
        worksheet = writer.sheets["Orden de Trabajo - Cotizador"]

        fmt_header = workbook.add_format({"bold": True, "bg_color": "#2c3e50", "font_color": "white", "border": 1})
        fmt_num = workbook.add_format({"num_format": "$#,##0.00", "border": 1})

        for col_num, value in enumerate(df_cotiz.columns.values):
            worksheet.write(0, col_num, value, fmt_header)
            worksheet.set_column(col_num, col_num, 25)

        for row_idx in range(1, len(df_cotiz) + 1):
            worksheet.write_formula(row_idx, 5, f"=D{row_idx+1}*E{row_idx+1}", fmt_num)

    return buffer.getvalue()

# ==================================================================================
# UTILIDADES DE IMÁGENES Y PLANOS
# ==================================================================================

import requests

@st.cache_data(show_spinner=False)
def cargar_imagen_desde_url(url: str):
    res = requests.get(url)
    res.raise_for_status()
    file_bytes = res.content
    ext = url.split("?")[0].split(".")[-1].lower()
    if ext == "pdf":
        if not PDF2IMAGE_OK:
            raise RuntimeError("pdf2image no disponible para visualizar el plano PDF.")
        paginas = convert_from_bytes(file_bytes, dpi=150, first_page=1, last_page=1)
        return paginas[0].convert("RGB")
    else:
        return Image.open(io.BytesIO(file_bytes)).convert("RGB")

def imagen_a_data_uri(imagen: Image.Image) -> str:
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{b64}"

# ==================================================================================
# GRÁFICOS
# ==================================================================================

def construir_figura_plano(imagen: Image.Image, puntos_df: pd.DataFrame, punto_resaltado_id=None):
    ancho, alto = imagen.size
    data_uri = imagen_a_data_uri(imagen)

    fig = go.Figure()
    fig.add_layout_image(
        dict(
            source=data_uri, xref="x", yref="y",
            x=0, y=alto, sizex=ancho, sizey=alto,
            sizing="stretch", layer="below",
        )
    )

    if puntos_df is not None and not puntos_df.empty:
        xs = puntos_df["x_pct"] / 100.0 * ancho
        ys = alto - (puntos_df["y_pct"] / 100.0 * alto)
        
        colores = []
        for _, p in puntos_df.iterrows():
            if p["id"] == punto_resaltado_id:
                colores.append("#e74c3c")
            elif p.get("tipo_categoria") == "Losa / Hormigón en Altura":
                colores.append("#e67e22")
            elif p.get("tipo_categoria") == "Humedad":
                colores.append("#3498db")
            else:
                colores.append("#2ecc71")

        textos = puntos_df["etiqueta"]
        hover_text = puntos_df["ubicacion_especifica"].fillna("") + " [" + puntos_df["tipo_categoria"].fillna("General") + "]"

        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text",
            marker=dict(size=16, color=colores, line=dict(width=2, color="white")),
            text=textos, textposition="top center",
            hovertext=hover_text, hoverinfo="text+x+y",
        ))

    fig.update_xaxes(visible=False, range=[0, ancho])
    fig.update_yaxes(visible=False, range=[0, alto], scaleanchor="x", scaleratio=1)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=650, showlegend=False, dragmode="pan")
    return fig

def construir_grafico_evolucion(df_punto: pd.DataFrame, etiqueta_punto: str):
    df_punto = df_punto.sort_values("fecha")
    fig = go.Figure()

    es_losa = "Losa" in df_punto["tipo_lesion"].values or (df_punto["grado_severidad_losa"].sum() > 0)

    if es_losa:
        fig.add_trace(go.Scatter(
            x=df_punto["fecha"], y=df_punto["grado_severidad_losa"],
            mode="lines+markers", name="Grado de Severidad Visual (1-4)",
            line=dict(color="#e67e22", width=3), marker=dict(size=10),
        ))
        fig.update_layout(
            title=f"Evolución de Severidad Visual — {etiqueta_punto}",
            xaxis_title="Fecha de inspección",
            yaxis_title="Grado de Severidad (1: Leve a 4: Severo)",
            yaxis=dict(dtick=1, range=[0.5, 4.5]), height=420,
        )
    else:
        fig.add_trace(go.Scatter(
            x=df_punto["fecha"], y=df_punto["ancho_mm"],
            mode="lines+markers", name="Ancho de fisura (mm)",
            line=dict(color="#2980b9", width=3), marker=dict(size=9),
        ))
        fig.add_hline(
            y=ACI_224R_LIMITE_MM, line_dash="dash", line_color="#e74c3c",
            annotation_text=f"Límite ACI 224R ({ACI_224R_LIMITE_MM} mm)",
        )
        fig.update_layout(
            title=f"Evolución temporal — {etiqueta_punto}",
            xaxis_title="Fecha de inspección", yaxis_title="Ancho de fisura (mm)",
            height=420,
        )
    return fig

# ==================================================================================
# AUTENTICACIÓN Y PANEL LATERAL
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
                except Exception as e:
                    st.error(f"Error al crear proyecto: {e}")
            else:
                st.warning("Ingresá un nombre para el proyecto.")

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Usuario: **{st.session_state.get('usuario', '')}**")
    if st.sidebar.button("Cerrar sesión"):
        cerrar_sesion()

# ==================================================================================
# PESTAÑAS
# ==================================================================================

def tab_plano_y_puntos(proyecto_id, proyecto_nombre):
    st.subheader("🗺️ Plano interactivo y geolocalización de puntos")

    col_upload, col_info = st.columns([2, 1])
    with col_upload:
        archivo_plano = st.file_uploader("Subir plano (PDF, PNG o JPG)", type=["pdf", "png", "jpg", "jpeg"], key="uploader_plano")
        if archivo_plano is not None:
            if st.button("Guardar este plano en el proyecto"):
                path_str = f"{slugify(proyecto_nombre)}/{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{archivo_plano.name}"
                url_publica = subir_archivo_supabase("planos", path_str, archivo_plano.getbuffer().tobytes(), archivo_plano.type)
                guardar_plano(proyecto_id, archivo_plano.name, url_publica)
                st.success("Plano guardado correctamente en la nube.")
                st.rerun()

    planos_df = listar_planos(proyecto_id)
    if planos_df.empty:
        st.info("Todavía no hay planos cargados para este proyecto. Subí uno arriba para empezar.")
        return

    with col_info:
        nombres_planos = planos_df["nombre"] + " (" + planos_df["subido_en"].str.slice(0, 10) + ")"
        idx_sel = st.selectbox("Plano activo", range(len(planos_df)), format_func=lambda i: nombres_planos.iloc[i])
        plano_actual = planos_df.iloc[idx_sel]
        st.session_state["plano_id"] = int(plano_actual["id"])

    try:
        imagen = cargar_imagen_desde_url(plano_actual["ruta_archivo"])
    except Exception as e:
        st.error(f"No se pudo cargar el plano desde la nube: {e}")
        return

    puntos_df = listar_puntos(proyecto_id, plano_id=int(plano_actual["id"]))
    fig = construir_figura_plano(imagen, puntos_df)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### ➕ Agregar nuevo punto de inspección")
    col1, col2 = st.columns(2)
    with col1:
        x_pct = st.slider("Posición horizontal (%)", 0.0, 100.0, 50.0, step=0.5, key="x_pct_nuevo")
    with col2:
        y_pct = st.slider("Posición vertical (%)", 0.0, 100.0, 50.0, step=0.5, key="y_pct_nuevo")

    preview_df = pd.DataFrame([{"id": -1, "etiqueta": "Nuevo punto", "ubicacion_especifica": "", "x_pct": x_pct, "y_pct": y_pct, "tipo_categoria": "General"}])
    if not puntos_df.empty:
        preview_df = pd.concat([puntos_df, preview_df], ignore_index=True)

    fig_preview = construir_figura_plano(imagen, preview_df, punto_resaltado_id=-1)
    st.plotly_chart(fig_preview, use_container_width=True, key="preview_plot")

    with st.form("form_nuevo_punto"):
        c_p1, c_p2 = st.columns(2)
        with c_p1:
            etiqueta = st.text_input("Etiqueta / ID (ej. F-01, Losa L-02, Humedad H-01)")
            ubicacion = st.text_input("Ubicación específica (ej. Cielorraso sector Tesorería)")
        with c_p2:
            tipo_cat = st.selectbox("Categoría Principal del Punto", TIPOS_LESION)
        
        crear = st.form_submit_button("Guardar punto en el plano")

    if crear:
        if etiqueta.strip():
            crear_punto(proyecto_id, int(plano_actual["id"]), etiqueta.strip(), ubicacion.strip(), x_pct, y_pct, tipo_cat)
            st.success(f"Punto '{etiqueta}' ({tipo_cat}) creado correctamente.")
            st.rerun()
        else:
            st.warning("La etiqueta del punto es obligatoria.")

def tab_nueva_inspeccion(proyecto_id, proyecto_nombre):
    st.subheader("📝 Ficha de inspección patológica")

    puntos_df = listar_puntos(proyecto_id)
    if puntos_df.empty:
        st.info("Primero creá al menos un punto de inspección en la pestaña 'Plano y Puntos'.")
        return

    etiquetas = puntos_df["etiqueta"] + " [" + puntos_df["tipo_categoria"].fillna("General") + "] — " + puntos_df["ubicacion_especifica"].fillna("")
    idx_sel = st.selectbox("Punto a inspeccionar", range(len(puntos_df)), format_func=lambda i: etiquetas.iloc[i])
    punto_sel = puntos_df.iloc[idx_sel]

    cat_defecto = punto_sel.get("tipo_categoria", "Fisura")
    if cat_defecto not in TIPOS_LESION:
        cat_defecto = "Fisura"

    with st.form("form_inspeccion", clear_on_submit=True):
        st.markdown("##### Datos generales de la lesión")
        c1, c2 = st.columns(2)
        with c1:
            fecha = st.date_input("Fecha de inspección", value=dt.date.today())
            tipo_lesion = st.selectbox("Tipo de lesión / elemento", TIPOS_LESION, index=TIPOS_LESION.index(cat_defecto))
            ancho_mm = st.number_input("Ancho de fisura (mm) - Opcional", min_value=0.0, step=0.01, format="%.2f")
        with c2:
            longitud_m = st.number_input("Longitud (m) - Opcional", min_value=0.0, step=0.01, format="%.2f")
            area_m2 = st.number_input("Área afectada (m²) - Opcional", min_value=0.0, step=0.01, format="%.2f")
            extension = st.text_input("Extensión (ej. 'Toda la luz de la losa')")

        tipo_losa = ""
        ubicacion_losa = ""
        manifestaciones_str = ""
        obs_losa = ""
        grado_sev_num = 0
        sup_afectada_pct = ""

        if tipo_lesion in ["Losa / Hormigón en Altura", "Desprendimiento"]:
            st.markdown("---")
            st.markdown("##### 🧱 Relevamiento Específico de Losas / Elementos en Altura")
            
            c_l1, c_l2 = st.columns(2)
            with c_l1:
                tipo_losa = st.selectbox("Tipo de Losa", TIPOS_LOSA)
                ubicacion_losa = st.selectbox("Ubicación en el elemento", UBICACION_LOSA)
                sup_afectada_pct = st.selectbox("Superficie visual afectada (%)", ["< 10%", "10% - 30%", "30% - 60%", "> 60%"])
            
            with c_l2:
                sev_label = st.selectbox("Grado de Severidad Visual", list(SEVERIDAD_LOSA.keys()))
                grado_sev_num = SEVERIDAD_LOSA[sev_label]
            
            st.write("**Manifestaciones observadas:**")
            m1, m2, m3 = st.columns(3)
            with m1:
                ch_desprendimiento = st.checkbox("Desprendimiento de recubrimiento")
                ch_armadura = st.checkbox("Armadura expuesta")
            with m2:
                ch_oxido = st.checkbox("Oxidación / Manchas de óxido")
                ch_fisuras_paralelas = st.checkbox("Fisuras paralelas a la armadura")
            with m3:
                ch_fisuras_perp = st.checkbox("Fisuras perpendiculares a la armadura")
                ch_eflorescencias = st.checkbox("Eflorescencias / Filtración")
                ch_flecha = st.checkbox("Deflexión / Flecha visible")

            manifestaciones_lista = []
            if ch_desprendimiento: manifestaciones_lista.append("Desprendimiento recubrimiento")
            if ch_armadura: manifestaciones_lista.append("Armadura expuesta")
            if ch_oxido: manifestaciones_lista.append("Oxidación/Corrosión")
            if ch_fisuras_paralelas: manifestaciones_lista.append("Fisuras paralelas a armadura")
            if ch_fisuras_perp: manifestaciones_lista.append("Fisuras perpendiculares a armadura")
            if ch_eflorescencias: manifestaciones_lista.append("Eflorescencias")
            if ch_flecha: manifestaciones_lista.append("Deflexión visible")
            manifestaciones_str = ", ".join(manifestaciones_lista)

            obs_losa = st.text_area("Observaciones específicas de la losa", height=80)

        st.markdown("---")
        st.markdown("##### Estado y entorno")
        c3, c4 = st.columns(2)
        with c3:
            estado = st.selectbox("Estado", ESTADOS_LESION)
            incidencia = st.selectbox("Incidencia estructural aparente", INCIDENCIAS)
        with c4:
            condiciones = st.selectbox("Condiciones ambientales", CONDICIONES_AMBIENTALES)
            intervenciones = st.text_input("Intervenciones previas")

        st.markdown("##### Descripción y Registro Fotográfico")
        descripcion = st.text_area("Descripción general corta", height=70)
        observaciones = st.text_area("Observaciones libres", height=90)
        foto = st.file_uploader("Foto de inspección", type=["png", "jpg", "jpeg"])

        enviar = st.form_submit_button("Guardar inspección", use_container_width=True)

    if enviar:
        foto_url = ""
        if foto is not None:
            path_str = f"{slugify(proyecto_nombre)}/{slugify(punto_sel['etiqueta'])}/{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{foto.name}"
            foto_url = subir_archivo_supabase("fotos", path_str, foto.getbuffer().tobytes(), foto.type)

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
            "foto_path": foto_url,
            "tipo_losa": tipo_losa,
            "ubicacion_losa": ubicacion_losa,
            "manifestaciones_losa": manifestaciones_str,
            "obs_losa": obs_losa,
            "grado_severidad_losa": grado_sev_num,
            "superficie_afectada_pct": sup_afectada_pct,
        }
        crear_inspeccion(datos)
        st.success(f"Inspección guardada permanentemente para '{punto_sel['etiqueta']}'.")

def tab_evolucion(proyecto_id):
    st.subheader("📈 Evolución temporal por punto y afectación")

    inspecciones_df = listar_inspecciones(proyecto_id)
    if inspecciones_df.empty:
        st.info("Todavía no hay inspecciones registradas en este proyecto.")
        return

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filtro_tipo = st.selectbox("Filtrar por tipo de lesión", ["Todas"] + TIPOS_LESION)
    
    if filtro_tipo != "Todas":
        inspecciones_df = inspecciones_df[inspecciones_df["tipo_lesion"] == filtro_tipo]

    if inspecciones_df.empty:
        st.info(f"No hay inspecciones registradas para el tipo de lesión '{filtro_tipo}'.")
        return

    puntos_unicos = inspecciones_df[["punto_id", "punto_etiqueta", "punto_categoria"]].drop_duplicates()
    
    with col_f2:
        etiquetas_p = puntos_unicos["punto_etiqueta"] + " [" + puntos_unicos["punto_categoria"].fillna("General") + "]"
        idx_sel = st.selectbox("Seleccioná el punto a analizar", range(len(puntos_unicos)), format_func=lambda i: etiquetas_p.iloc[i])
    
    punto_id_sel = int(puntos_unicos["punto_id"].iloc[idx_sel])
    etiqueta_sel = puntos_unicos["punto_etiqueta"].iloc[idx_sel]

    df_punto = inspecciones_df[inspecciones_df["punto_id"] == punto_id_sel].copy()
    df_punto["fecha"] = pd.to_datetime(df_punto["fecha"])

    fig = construir_grafico_evolucion(df_punto, etiqueta_sel)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### Historial fotográfico y clínico cronológico")
    for _, fila in df_punto.sort_values("fecha", ascending=False).iterrows():
        titulo_exp = f"{fila['fecha'].date()} — {fila['tipo_lesion']}"
        if fila.get("grado_severidad_losa", 0) > 0:
            titulo_exp += f" (Grado Severidad Visual: {fila['grado_severidad_losa']}/4)"
        elif fila['ancho_mm'] > 0:
            titulo_exp += f" ({fila['ancho_mm']} mm)"

        with st.expander(titulo_exp):
            c1, c2 = st.columns([1, 2])
            with c1:
                if fila["foto_path"]:
                    st.image(fila["foto_path"], use_container_width=True)
                else:
                    st.caption("Sin foto asociada.")
            with c2:
                if fila.get("tipo_losa"):
                    st.write(f"**Tipo de Losa:** {fila['tipo_losa']} | **Ubicación:** {fila['ubicacion_losa']}")
                    st.write(f"**Manifestaciones:** {fila['manifestaciones_losa']}")
                    if fila.get("obs_losa"):
                        st.write(f"**Obs. Losa:** {fila['obs_losa']}")
                    st.write(f"**Superficie afectada est.:** {fila['superficie_afectada_pct']}")
                st.write(f"**Estado:** {fila['estado']} | **Incidencia:** {fila['incidencia_estructural']}")
                st.write(f"**Condiciones:** {fila['condiciones_ambientales']}")
                st.write(f"**Descripción:** {fila['descripcion']}")
                st.write(f"**Observaciones:** {fila['observaciones']}")

def tab_dashboard_y_cotizador(proyecto_id, proyecto_nombre):
    st.subheader("🚦 Semáforo de Riesgo y Planilla de Cotización Excel")

    inspecciones_df = listar_inspecciones(proyecto_id)
    if inspecciones_df.empty:
        st.info("Todavía no hay inspecciones registradas para construir el tablero de control.")
        return

    inspecciones_df["Riesgo"] = inspecciones_df.apply(calcular_nivel_riesgo, axis=1)
    
    cant_rojo = len(inspecciones_df[inspecciones_df["Riesgo"].str.contains("ROJO")])
    cant_amarillo = len(inspecciones_df[inspecciones_df["Riesgo"].str.contains("AMARILLO")])
    cant_verde = len(inspecciones_df[inspecciones_df["Riesgo"].str.contains("VERDE")])

    m1, m2, m3 = st.columns(3)
    m1.metric("🔴 Críticos / Urgentes", cant_rojo)
    m2.metric("🟡 Monitoreo / Atención", cant_amarillo)
    m3.metric("🟢 Estable / Bajo Riesgo", cant_verde)

    st.markdown("---")
    st.markdown("##### 📋 Clasificación de Puntos según Prioridad")
    
    cols_mostrar = ["fecha", "punto_etiqueta", "tipo_lesion", "Riesgo", "incidencia_estructural", "grado_severidad_losa", "descripcion"]
    st.dataframe(inspecciones_df[cols_mostrar], use_container_width=True)

    st.markdown("---")
    st.markdown("##### 💵 Descargar Pliego de Cotización / Orden de Trabajo")

    bytes_excel = generar_excel_cotizacion(inspecciones_df, proyecto_nombre)
    st.download_button(
        label="⬇️ Descargar Orden de Trabajo y Cotizador (Excel Editable)",
        data=bytes_excel,
        file_name=f"cotizador_obra_{slugify(proyecto_nombre)}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

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
        st.success("Informe guardado correctamente en la nube.")

    st.markdown("---")
    st.markdown("##### Informes guardados")
    informes_df = listar_informes(proyecto_id)
    if informes_df.empty:
        st.caption("Todavía no se guardaron informes para este proyecto.")
    else:
        for _, fila in informes_df.iterrows():
            with st.expander(f"{fila['titulo']} — {str(fila['creado_en'])[:10]}"):
                st.write(f"**Diagnóstico:** {fila['diagnostico']}")
                st.write(f"**Gravedad y riesgo:** {fila['gravedad_riesgo']}")
                st.write(f"**Estado de actividad:** {fila['estado_actividad']}")
                st.write(f"**Pronóstico:** {fila['pronostico']}")
                st.write(f"**Propuesta de solución:** {fila['propuesta_solucion']}")

# ==================================================================================
# MAIN
# ==================================================================================

def main():
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
        "🚦 Dashboard y Cotizador Excel",
        "📄 Informe Técnico",
    ])

    with tabs[0]:
        tab_plano_y_puntos(proyecto_id, proyecto_nombre)
    with tabs[1]:
        tab_nueva_inspeccion(proyecto_id, proyecto_nombre)
    with tabs[2]:
        tab_evolucion(proyecto_id)
    with tabs[3]:
        tab_dashboard_y_cotizador(proyecto_id, proyecto_nombre)
    with tabs[4]:
        tab_informe_tecnico(proyecto_id, proyecto_nombre)

if __name__ == "__main__":
    main()
