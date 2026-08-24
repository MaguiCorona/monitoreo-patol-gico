import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as plotly_exp
from PIL import Image, ImageDraw
from fpdf import FPDF
import datetime
import io
import requests
from pdf2image import convert_from_bytes
from streamlit_image_coordinates import streamlit_image_coordinates

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Monitoreo y Patología Edilicia",
    page_icon="🏗️",
    layout="wide"
)

# -----------------------------------------------------------------------------
# CONEXIÓN SUPABASE
# -----------------------------------------------------------------------------
@st.cache_resource
def init_supabase() -> Client:
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
    return create_client(supabase_url, supabase_key)

supabase = init_supabase()

# -----------------------------------------------------------------------------
# FUNCIONES STORAGE & DATABASE
# -----------------------------------------------------------------------------
def subir_archivo_supabase(bucket: str, path: str, file_bytes: bytes, content_type: str):
    try:
        supabase.storage.from_(bucket).upload(
            path=path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        return supabase.storage.from_(bucket).get_public_url(path)
    except Exception:
        try:
            return supabase.storage.from_(bucket).get_public_url(path)
        except Exception as e:
            st.error(f"Error al subir archivo a {bucket}: {e}")
            return None

def obtener_proyectos():
    res = supabase.table("proyectos").select("*").order("creado_en", desc=True).execute()
    return res.data if res.data else []

def crear_proyecto(nombre, descripcion):
    return supabase.table("proyectos").insert({"nombre": nombre, "descripcion": descripcion}).execute()

def obtener_planos(proyecto_id):
    res = supabase.table("planos").select("*").eq("proyecto_id", proyecto_id).order("subido_en", desc=True).execute()
    return res.data if res.data else []

def crear_plano(proyecto_id, nombre, url_archivo):
    return supabase.table("planos").insert({"proyecto_id": proyecto_id, "nombre": nombre, "ruta_archivo": url_archivo}).execute()

def obtener_puntos(plano_id=None, proyecto_id=None):
    query = supabase.table("puntos").select("*")
    if plano_id:
        query = query.eq("plano_id", plano_id)
    if proyecto_id:
        query = query.eq("proyecto_id", proyecto_id)
    res = query.order("creado_en", desc=False).execute()
    return res.data if res.data else []

def crear_punto(proyecto_id, plano_id, x_pct, y_pct, etiqueta, tipo_patologia):
    data = {
        "proyecto_id": proyecto_id,
        "plano_id": plano_id,
        "x_pct": float(x_pct),
        "y_pct": float(y_pct),
        "etiqueta": etiqueta,
        "tipo_patologia": tipo_patologia
    }
    return supabase.table("puntos").insert(data).execute()

def actualizar_punto(punto_id, x_pct, y_pct, etiqueta, tipo_patologia):
    data = {
        "x_pct": float(x_pct),
        "y_pct": float(y_pct),
        "etiqueta": etiqueta,
        "tipo_patologia": tipo_patologia
    }
    return supabase.table("puntos").update(data).eq("id", punto_id).execute()

def eliminar_punto(punto_id):
    return supabase.table("puntos").delete().eq("id", punto_id).execute()

def obtener_inspecciones(punto_id=None, proyecto_id=None):
    if punto_id:
        res = supabase.table("inspecciones").select("*").eq("punto_id", punto_id).order("fecha", desc=False).execute()
        return res.data if res.data else []
    
    res = supabase.table("inspecciones").select("*, puntos!inner(etiqueta, tipo_patologia, proyecto_id)").order("fecha", desc=False).execute()
    if res.data:
        if proyecto_id:
            return [i for i in res.data if i["puntos"]["proyecto_id"] == proyecto_id]
        return res.data
    return []

def crear_inspeccion(punto_id, fecha, valor, unidad, severidad, observacion, url_foto):
    data = {
        "punto_id": punto_id,
        "fecha": str(fecha),
        "valor_medicion": float(valor),
        "unidad_medicion": unidad,
        "severidad_subjetiva": severidad,
        "descripcion": observacion,
        "foto_path": url_foto
    }
    return supabase.table("inspecciones").insert(data).execute()

def actualizar_inspeccion(inspeccion_id, fecha, valor, unidad, severidad, observacion, url_foto=None):
    data = {
        "fecha": str(fecha),
        "valor_medicion": float(valor),
        "unidad_medicion": unidad,
        "severidad_subjetiva": severidad,
        "descripcion": observacion
    }
    if url_foto:
        data["foto_path"] = url_foto
    return supabase.table("inspecciones").update(data).eq("id", inspeccion_id).execute()

def eliminar_inspeccion(inspeccion_id):
    return supabase.table("inspecciones").delete().eq("id", inspeccion_id).execute()

# -----------------------------------------------------------------------------
# DIBUJAR PUNTOS EN LA IMAGEN DEL PLANO
# -----------------------------------------------------------------------------
@st.cache_data(ttl=60)
def cargar_imagen_plano(url_plano):
    try:
        resp = requests.get(url_plano, timeout=10)
        return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        st.error(f"Error al descargar la imagen del plano: {e}")
        return None

def generar_imagen_con_puntos(img_base, puntos, punto_temp=None):
    img = img_base.copy()
    draw = ImageDraw.Draw(img)
    ancho, alto = img.size
    
    r = max(12, int(min(ancho, alto) * 0.018))

    for idx, p in enumerate(puntos):
        cx = int((float(p["x_pct"]) / 100.0) * ancho)
        cy = int((float(p["y_pct"]) / 100.0) * alto)

        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#FF0000", outline="#FFFFFF", width=3)
        draw.ellipse([cx - r//3, cy - r//3, cx + r//3, cy + r//3], fill="#FFFF00")

        texto = f" P{idx+1}: {p['etiqueta']} "
        draw.text((cx + r + 4, cy - r), texto, fill="#000000")

    if punto_temp:
        cx = int((float(punto_temp[0]) / 100.0) * ancho)
        cy = int((float(punto_temp[1]) / 100.0) * alto)
        draw.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill="#0066FF", outline="#FFFFFF", width=3)
        draw.text((cx + r + 6, cy - r), " 📍 NUEVO SELECCIONADO ", fill="#000000")

    return img

# -----------------------------------------------------------------------------
# DIAGNÓSTICO, SEVERIDAD AUTOMÁTICA Y SEMÁFORO
# -----------------------------------------------------------------------------
def determinar_severidad_automatica(tipo_patologia, valor):
    """Calcula automáticamente la severidad sugerida según la dimensión/medición."""
    v = float(valor)
    
    if tipo_patologia == "Fisura/Grieta":
        if v < 1.0:
            return "Baja"
        elif 1.0 <= v < 3.0:
            return "Media"
        elif 3.0 <= v <= 5.0:
            return "Alta"
        else:
            return "Crítica"

    elif tipo_patologia in ["Humedad/Filtración", "Desprendimiento en Muros", "Afectación en Losa"]:
        if v < 1.5:
            return "Baja"
        elif 1.5 <= v < 3.0:
            return "Media"
        elif 3.0 <= v < 5.0:
            return "Alta"
        else:
            return "Crítica"

    return "Baja"

def evaluar_semagoro(tipo_patologia, ultimo_valor, severidad):
    if tipo_patologia == "Fisura/Grieta":
        if ultimo_valor >= 5.0 or severidad == "Crítica":
            return "🔴 CRÍTICO", "Riesgo estructural o penetración directa de agua. Requiere prueba de carga y sellado estructural epóxico urgente.", "red"
        elif ultimo_valor >= 3.0 or severidad == "Alta":
            return "🟠 ALTO", "Fisura pronunciada activa. Inspeccionar y colocar testigos estructurales de control.", "orange"
        elif ultimo_valor >= 1.0 or severidad == "Media":
            return "🟡 MEDIO", "Fisura activa en monitoreo. Colocar testigo y sellar con sellador elástico.", "orange"
        else:
            return "🟢 BAJO", "Fisura superficial / de retracción. Monitorear periódicamente.", "green"

    elif tipo_patologia == "Humedad/Filtración":
        if severidad == "Crítica" or ultimo_valor >= 5.0:
            return "🔴 CRÍTICO", "Filtración activa con goteo continuo, moho denso o desprendimiento generalizado. Riesgo de degradación de estructuras y ambiente insalubre. Reparar impermeabilización de inmediato.", "red"
        elif severidad == "Alta" or ultimo_valor >= 3.0:
            return "🟠 ALTO", "Humedad de remonte capilar/eflorescencias severas o ampollamiento extendido. Intervenir barrera impermeable.", "orange"
        elif severidad == "Media" or ultimo_valor >= 1.5:
            return "🟡 MEDIO", "Mancha de humedad persistente con eflorescencias aisladas. Revisar sellados, albardillas o cañerías cercanas.", "orange"
        else:
            return "🟢 BAJO", "Mancha de humedad residual o seca sin eflorescencias activas. Monitorear evolución.", "green"

    elif tipo_patologia == "Afectación en Losa":
        if ultimo_valor >= 5.0 or severidad in ["Alta", "Crítica"]:
            return "🔴 CRÍTICO", "Área de losa afectada severa. Inspección con calculista urgente y pasivado de armaduras.", "red"
        elif ultimo_valor >= 1.5 or severidad == "Media":
            return "🟡 MEDIO", "Área afectada moderada. Monitorear flechas y fisuración.", "orange"
        else:
            return "🟢 BAJO", "Afectación dentro de tolerancias de servicio.", "green"

    elif tipo_patologia == "Desprendimiento en Muros":
        if ultimo_valor >= 5.0 or severidad in ["Alta", "Crítica"]:
            return "🔴 CRÍTICO", "Riesgo de caída de revoque/revestimiento. Picar zona afectada, consolidar sustrato y rehacer revoque de inmediato.", "red"
        elif ultimo_valor >= 1.5 or severidad == "Media":
            return "🟡 MEDIO", "Desprendimiento parcial o abombamiento. Monitorear adherencia y reparar en corto plazo.", "orange"
        else:
            return "🟢 BAJO", "Fisuración o desprendimiento localizado puntual. Continuar seguimiento.", "green"

    return "🟢 BAJO", "Sin anomalías mayores.", "green"

# -----------------------------------------------------------------------------
# GENERACIÓN DE PDF
# -----------------------------------------------------------------------------
def generar_pdf_informe(proyecto, puntos, inspecciones_todas, df_costos):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    
    pdf.cell(0, 10, f"INFORME TÉCNICO DE PATOLOGÍA EDILICIA", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Proyecto: {proyecto['nombre']}", ln=True, align="C")
    pdf.cell(0, 5, f"Fecha de emisión: {datetime.date.today().strftime('%d/%m/%Y')}", ln=True, align="C")
    pdf.ln(10)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "1. Resumen General del Proyecto", ln=True)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, 5, proyecto.get("descripcion") or "Sin descripción proporcionada.")
    pdf.ln(5)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "2. Puntos Monitoreados y Estado de Riesgo", ln=True)
    pdf.set_font("Arial", "", 10)

    for p in puntos:
        p_insps = [i for i in inspecciones_todas if i["punto_id"] == p["id"]]
        ult_val = p_insps[-1]["valor_medicion"] if p_insps else 0.0
        ult_sev = p_insps[-1]["severidad_subjetiva"] if p_insps else "Baja"
        ult_uni = p_insps[-1]["unidad_medicion"] if p_insps else ""
        
        estado, rec, _ = evaluar_semagoro(p["tipo_patologia"], ult_val, ult_sev)
        
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 6, f"• Punto: {p['etiqueta']} ({p['tipo_patologia']}) - Estado: {estado}", ln=True)
        pdf.set_font("Arial", "", 9)
        pdf.multi_cell(0, 5, f"  Última Medición: {ult_val} {ult_uni} | Severidad: {ult_sev}\n  Recomendación: {rec}")
        pdf.ln(2)

    pdf.ln(5)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "3. Presupuesto Estimado de Reparación", ln=True)
    pdf.set_font("Arial", "", 8)

    for _, row in df_costos.iterrows():
        tarea = str(row.get('Tareas a Realizar', ''))
        tipo_p = str(row.get('Tipo de Patología', ''))
        cant = float(row.get('Cantidad (m² o m)', 0.0))
        unit = float(row.get('Precio Unitario ($)', 0.0))
        subt = float(row.get('Subtotal ($)', 0.0))
        
        pdf.cell(0, 5, f"- [{tipo_p}] {tarea} | Cant: {cant} | Unit: ${unit:,.2f} | Subtotal: ${subt:,.2f}", ln=True)

    pdf.ln(5)
    total = df_costos["Subtotal ($)"].sum() if "Subtotal ($)" in df_costos else 0.0
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 8, f"COSTO TOTAL ESTIMADO: ${total:,.2f}", ln=True)

    return pdf.output(dest="S").encode("latin-1", errors="replace")

# -----------------------------------------------------------------------------
# INTERFAZ PRINCIPAL
# -----------------------------------------------------------------------------
def main():
    st.title("🏗️ Monitoreo Patológico & Diagnóstico Edilicio")

    proyectos = obtener_proyectos()
    
    st.sidebar.header("📁 Gestión de Proyectos")
    opcion_proyecto = st.sidebar.selectbox(
        "Seleccionar Proyecto",
        options=["-- Seleccionar --", "+ Crear nuevo proyecto"] + [p["nombre"] for p in proyectos]
    )

    if opcion_proyecto == "+ Crear nuevo proyecto":
        st.subheader("Crear Nuevo Proyecto")
        with st.form("form_nuevo_proyecto"):
            nombre_p = st.text_input("Nombre del Proyecto / Edificio")
            desc_p = st.text_area("Descripción u Ubicación")
            if st.form_submit_button("Crear Proyecto") and nombre_p:
                try:
                    crear_proyecto(nombre_p, desc_p)
                    st.success(f"Proyecto '{nombre_p}' creado con éxito.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear proyecto: {e}")
        return

    if opcion_proyecto == "-- Seleccionar --" or not proyectos:
        st.info("Seleccioná o creá un proyecto en el menú lateral para comenzar.")
        return

    proyecto_actual = next(p for p in proyectos if p["nombre"] == opcion_proyecto)
    proyecto_id = proyecto_actual["id"]

    st.header(f"🏢 Proyecto: {proyecto_actual['nombre']}")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📌 Planos y Puntos", 
        "📝 Relevamiento e Inspección", 
        "🚥 Semáforo & Evolución", 
        "💰 Presupuesto e Informe PDF"
    ])

    with tab1:
        tab_planos_y_puntos(proyecto_id)

    with tab2:
        tab_relevamiento(proyecto_id)

    with tab3:
        tab_semaforo_y_graficas(proyecto_id)

    with tab4:
        tab_presupuesto_y_pdf(proyecto_actual)

# -----------------------------------------------------------------------------
# TAB 1: PLANOS Y MARCADOR INTERACTIVO
# -----------------------------------------------------------------------------
def tab_planos_y_puntos(proyecto_id):
    planos = obtener_planos(proyecto_id)
    col_izq, col_der = st.columns([1, 2])

    with col_izq:
        st.subheader("Planos del Proyecto")
        
        with st.expander("➕ Subir Nuevo Plano"):
            nombre_plano = st.text_input("Nombre del Plano (Ej: Piso 1, Fachada Este)")
            archivo_plano = st.file_uploader(
                "Seleccionar plano (Imagen o PDF)", 
                type=["jpg", "jpeg", "png", "webp", "pdf"]
            )
            
            if st.button("Guardar Plano") and nombre_plano and archivo_plano:
                ext = archivo_plano.name.split(".")[-1].lower()
                
                if ext == "pdf":
                    try:
                        imagenes = convert_from_bytes(archivo_plano.getvalue(), first_page=1, last_page=1)
                        img_byte_arr = io.BytesIO()
                        imagenes[0].save(img_byte_arr, format='PNG')
                        file_bytes = img_byte_arr.getvalue()
                        content_type = "image/png"
                        path_str = f"{proyecto_id}/{nombre_plano.replace(' ', '_')}.png"
                    except Exception as e:
                        st.error(f"Error al procesar el archivo PDF: {e}")
                        return
                else:
                    file_bytes = archivo_plano.getvalue()
                    content_type = archivo_plano.type
                    path_str = f"{proyecto_id}/{nombre_plano.replace(' ', '_')}.{ext}"
                
                url_publica = subir_archivo_supabase("planos", path_str, file_bytes, content_type)
                if url_publica:
                    crear_plano(proyecto_id, nombre_plano, url_publica)
                    st.success("Plano procesado y guardado correctamente.")
                    st.rerun()

        if not planos:
            st.warning("Cargá un plano para marcar puntos de patología.")
            return

        plano_sel_nombre = st.selectbox("Plano Activo", [p["nombre"] for p in planos])
        plano_actual = next(p for p in planos if p["nombre"] == plano_sel_nombre)

    puntos = obtener_puntos(plano_id=plano_actual["id"])
    img_base = cargar_imagen_plano(plano_actual["ruta_archivo"])

    if "clic_x" not in st.session_state:
        st.session_state.clic_x = 50.0
    if "clic_y" not in st.session_state:
        st.session_state.clic_y = 50.0

    with col_der:
        st.subheader(f"Plano: {plano_actual['nombre']}")
        
        zoom_ancho = st.slider("📏 Tamaño del plano en pantalla (ancho en píxeles):", min_value=300, max_value=1200, value=650, step=50)
        st.caption("👇 **Hacé clic en cualquier lugar del plano para marcar la posición:**")

        punto_temp_coord = (st.session_state.clic_x, st.session_state.clic_y)
        
        if img_base:
            img_render = generar_imagen_con_puntos(img_base, puntos, punto_temp_coord)
            
            ancho_orig, alto_orig = img_render.size
            proporcion = zoom_ancho / float(ancho_orig)
            alto_display = int(alto_orig * proporcion)
            
            img_resizing = img_render.resize((zoom_ancho, alto_display), Image.Resampling.LANCZOS)
            
            coordenadas = streamlit_image_coordinates(img_resizing, key=f"plano_clic_{plano_actual['id']}")
            
            if coordenadas and isinstance(coordenadas, dict):
                st.session_state.clic_x = round((coordenadas["x"] / float(zoom_ancho)) * 100, 2)
                st.session_state.clic_y = round((coordenadas["y"] / float(alto_display)) * 100, 2)

    with col_izq:
        st.divider()
        st.subheader("Marcar Nuevo Punto Patológico")
        
        etiqueta = st.text_input("Etiqueta (Ej: P1 - Columna C2)")
        tipos_opciones = ["Fisura/Grieta", "Humedad/Filtración", "Afectación en Losa", "Desprendimiento en Muros"]
        tipo_patologia = st.selectbox("Tipo de Patología", tipos_opciones)
        
        coord_x = st.number_input("Posición X (%)", 0.0, 100.0, float(st.session_state.clic_x), 0.1)
        coord_y = st.number_input("Posición Y (%)", 0.0, 100.0, float(st.session_state.clic_y), 0.1)

        if st.button("Registrar Punto") and etiqueta:
            try:
                crear_punto(proyecto_id, plano_actual["id"], coord_x, coord_y, etiqueta, tipo_patologia)
                st.success("¡Punto registrado correctamente!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error de Supabase al guardar el punto: {e}")

        if puntos:
            st.divider()
            st.subheader("✏️ Editar / Eliminar Puntos Existentes")
            
            opciones_puntos = {f"{p['etiqueta']} ({p['tipo_patologia']})": p for p in puntos}
            punto_sel_label = st.selectbox("Seleccionar punto a editar/eliminar", list(opciones_puntos.keys()))
            punto_a_editar = opciones_puntos[punto_sel_label]

            with st.expander("Modificar datos de este punto"):
                edit_etiqueta = st.text_input("Editar Etiqueta", value=punto_a_editar["etiqueta"], key="edit_etiq")
                
                idx_tipo = tipos_opciones.index(punto_a_editar["tipo_patologia"]) if punto_a_editar["tipo_patologia"] in tipos_opciones else 0
                edit_tipo = st.selectbox("Editar Tipo de Patología", tipos_opciones, index=idx_tipo, key="edit_tipo")
                
                edit_x = st.number_input("Editar Posición X (%)", 0.0, 100.0, float(punto_a_editar["x_pct"]), 0.1, key="edit_x")
                edit_y = st.number_input("Editar Posición Y (%)", 0.0, 100.0, float(punto_a_editar["y_pct"]), 0.1, key="edit_y")

                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("💾 Guardar Cambios"):
                        try:
                            actualizar_punto(punto_a_editar["id"], edit_x, edit_y, edit_etiqueta, edit_tipo)
                            st.success("¡Punto actualizado!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error al actualizar: {e}")

                with col_b2:
                    if st.button("🗑️ Eliminar Punto", type="primary"):
                        try:
                            eliminar_punto(punto_a_editar["id"])
                            st.warning("Punto eliminado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error al eliminar: {e}")

            st.write("📍 **Tabla de Puntos:**")
            df_pt = pd.DataFrame(puntos)[["etiqueta", "tipo_patologia", "x_pct", "y_pct"]]
            st.dataframe(df_pt, use_container_width=True)

# -----------------------------------------------------------------------------
# TAB 2: RELEVAMIENTO E INSPECCIONES (CON SELECCIÓN AUTOMÁTICA DE SEVERIDAD)
# -----------------------------------------------------------------------------
def tab_relevamiento(proyecto_id):
    puntos = obtener_puntos(proyecto_id=proyecto_id)
    if not puntos:
        st.warning("Primero debes registrar puntos en la pestaña 'Planos y Puntos'.")
        return

    punto_nom = st.selectbox("Seleccionar Punto de Monitoreo", [f"{p['etiqueta']} ({p['tipo_patologia']})" for p in puntos])
    punto_idx = [f"{p['etiqueta']} ({p['tipo_patologia']})" for p in puntos].index(punto_nom)
    punto_actual = puntos[punto_idx]

    # --- RECUADRO GUÍA DE CRITERIOS DE SEVERIDAD ---
    with st.expander("📋 **Guía y Criterios Estandarizados de Evaluación de Severidad**", expanded=False):
        st.info("""
        **Reglas de cálculo automático de severidad según la dimensión:**
        * **Fisuras (mm):** `< 1.0 mm` → 🟢 **Baja** | `1.0 a 2.9 mm` → 🟡 **Media** | `3.0 a 5.0 mm` → 🟠 **Alta** | `> 5.0 mm` → 🔴 **Crítica**
        * **Humedad / Desprendimientos / Losas (m²):** `< 1.5 m²` → 🟢 **Baja** | `1.5 a 2.9 m²` → 🟡 **Media** | `3.0 a 4.9 m²` → 🟠 **Alta** | `≥ 5.0 m²` → 🔴 **Crítica**
        """)

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader(f"Cargar Nueva Inspección: {punto_actual['etiqueta']}")
        
        tipo = punto_actual["tipo_patologia"]
        unidad = "mm" if tipo == "Fisura/Grieta" else "m²"
        
        fecha = st.date_input("Fecha de medición", datetime.date.today())
        valor = st.number_input(f"Medición registrada ({unidad})", min_value=0.0, value=1.0, step=0.1)
        
        # Selección e indicación automática de severidad según la dimensión
        sev_auto = determinar_severidad_automatica(tipo, valor)
        severidades_opts = ["Baja", "Media", "Alta", "Crítica"]
        idx_auto = severidades_opts.index(sev_auto)
        
        st.caption(f"🤖 Severidad sugerida automáticamente según dimensión ({valor} {unidad}): **{sev_auto}**")
        severidad = st.selectbox("Evaluación de severidad", severidades_opts, index=idx_auto)
        
        obs = st.text_area("Observaciones técnicas y causas probables")
        foto = st.file_uploader("Foto de evidencia", type=["jpg", "jpeg", "png", "webp"])

        if st.button("Guardar Inspección"):
            url_foto = None
            if foto:
                bytes_f = foto.getvalue()
                path = f"{punto_actual['id']}/{fecha}_{foto.name.replace(' ', '_')}"
                url_foto = subir_archivo_supabase("fotos", path, bytes_f, foto.type)

            try:
                crear_inspeccion(punto_actual["id"], fecha, valor, unidad, severidad, obs, url_foto)
                st.success("Inspección guardada con éxito.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al guardar inspección: {e}")

    with col2:
        st.subheader("Historial de este Punto")
        inspecciones = obtener_inspecciones(punto_id=punto_actual["id"])
        
        if not inspecciones:
            st.caption("Aún no hay mediciones registradas.")
        else:
            for idx, insp in enumerate(inspecciones):
                with st.container(border=True):
                    st.write(f"📅 **Fecha:** {insp['fecha']} | **Valor:** {insp['valor_medicion']} {insp['unidad_medicion']}")
                    st.write(f"⚠️ **Severidad:** {insp['severidad_subjetiva']}")
                    st.write(f"📝 {insp['descripcion']}")
                    if insp.get("foto_path"):
                        st.image(insp["foto_path"], width=280)
                    
                    with st.expander(f"✏️ Editar / Eliminar esta inspección (#{idx+1})"):
                        try:
                            fecha_val = datetime.datetime.strptime(insp['fecha'], "%Y-%m-%d").date()
                        except Exception:
                            fecha_val = datetime.date.today()

                        edit_fecha = st.date_input("Fecha", value=fecha_val, key=f"edit_f_{insp['id']}")
                        edit_valor = st.number_input(f"Medición ({insp['unidad_medicion']})", min_value=0.0, value=float(insp['valor_medicion']), step=0.1, key=f"edit_v_{insp['id']}")
                        
                        edit_sev_auto = determinar_severidad_automatica(tipo, edit_valor)
                        idx_edit_sev = severidades_opts.index(insp['severidad_subjetiva']) if insp['severidad_subjetiva'] in severidades_opts else severidades_opts.index(edit_sev_auto)
                        
                        edit_sev = st.selectbox("Severidad", severidades_opts, index=idx_edit_sev, key=f"edit_s_{insp['id']}")
                        edit_obs = st.text_area("Observaciones", value=insp.get('descripcion', ''), key=f"edit_o_{insp['id']}")
                        edit_foto = st.file_uploader("Reemplazar foto (opcional)", type=["jpg", "jpeg", "png", "webp"], key=f"edit_img_{insp['id']}")

                        col_e1, col_e2 = st.columns(2)
                        with col_e1:
                            if st.button("💾 Actualizar", key=f"btn_save_{insp['id']}"):
                                url_foto_edit = None
                                if edit_foto:
                                    bytes_f = edit_foto.getvalue()
                                    path = f"{punto_actual['id']}/{edit_fecha}_{edit_foto.name.replace(' ', '_')}"
                                    url_foto_edit = subir_archivo_supabase("fotos", path, bytes_f, edit_foto.type)
                                
                                try:
                                    actualizar_inspeccion(insp['id'], edit_fecha, edit_valor, insp['unidad_medicion'], edit_sev, edit_obs, url_foto_edit)
                                    st.success("Inspección modificada correctamente.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al actualizar inspección: {e}")

                        with col_e2:
                            if st.button("🗑️ Eliminar", type="primary", key=f"btn_del_{insp['id']}"):
                                try:
                                    eliminar_inspeccion(insp['id'])
                                    st.warning("Inspección eliminada.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al eliminar inspección: {e}")

# -----------------------------------------------------------------------------
# TAB 3: SEMÁFORO Y GRÁFICAS DE EVOLUCIÓN
# -----------------------------------------------------------------------------
def tab_semaforo_y_graficas(proyecto_id):
    st.subheader("🚥 Diagnóstico de Riesgo y Semáforo Patológico")

    puntos = obtener_puntos(proyecto_id=proyecto_id)
    inspecciones_todas = obtener_inspecciones(proyecto_id=proyecto_id)

    if not puntos:
        st.info("No hay datos cargados para analizar.")
        return

    cols = st.columns(3)
    for idx, p in enumerate(puntos):
        p_insps = [i for i in inspecciones_todas if i["punto_id"] == p["id"]]
        ult_val = p_insps[-1]["valor_medicion"] if p_insps else 0.0
        ult_sev = p_insps[-1]["severidad_subjetiva"] if p_insps else determinar_severidad_automatica(p["tipo_patologia"], ult_val)
        ult_uni = p_insps[-1]["unidad_medicion"] if p_insps else ("mm" if p["tipo_patologia"] == "Fisura/Grieta" else "m²")
        
        estado, rec, color = evaluar_semagoro(p["tipo_patologia"], ult_val, ult_sev)

        with cols[idx % 3]:
            with st.container(border=True):
                st.markdown(f"### {p['etiqueta']}")
                st.caption(f"Tipo: {p['tipo_patologia']}")
                
                if color == "red":
                    st.error(f"Estado: {estado}")
                elif color in ["orange", "yellow"]:
                    st.warning(f"Estado: {estado}")
                else:
                    st.success(f"Estado: {estado}")

                st.write(f"**Última Medición:** {ult_val} {ult_uni}")
                st.write(f"**Severidad:** {ult_sev}")
                st.write(f"**Diagnóstico:** {rec}")

    st.divider()
    st.subheader("📈 Evolución Temporal de las Patologías")

    if inspecciones_todas:
        data = []
        for i in inspecciones_todas:
            data.append({
                "Fecha": i["fecha"],
                "Valor": i["valor_medicion"],
                "Punto": i["puntos"]["etiqueta"],
                "Unidad": i["unidad_medicion"]
            })
        df_chart = pd.DataFrame(data)

        fig = plotly_exp.line(
            df_chart, 
            x="Fecha", 
            y="Valor", 
            color="Punto", 
            markers=True,
            title="Evolución de Medición en el Tiempo"
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Cargá mediciones para ver los gráficos de tendencias.")

# -----------------------------------------------------------------------------
# TAB 4: PRESUPUESTO EDITABLE E INFORME EXCEL / PDF
# -----------------------------------------------------------------------------
def tab_presupuesto_y_pdf(proyecto):
    st.subheader("💰 Presupuesto de Reparación y Planilla de Costos")
    st.caption("Los costos de mano de obra y materiales están expresados en $/m² o $/m y pueden ser ajustados tomando como referencia publicaciones técnicas como Cifras, Vivienda o UOCRA.")

    puntos = obtener_puntos(proyecto_id=proyecto["id"])
    inspecciones_todas = obtener_inspecciones(proyecto_id=proyecto["id"])

    def construir_df_presupuesto_base():
        filas = []
        if puntos:
            for p in puntos:
                p_insps = [i for i in inspecciones_todas if i["punto_id"] == p["id"]]
                cant = float(p_insps[-1]["valor_medicion"]) if p_insps else 1.0
                tipo = p["tipo_patologia"]

                if tipo == "Desprendimiento en Muros":
                    tarea = f"Picado de revoque en abombamiento/desprendimiento ({p['etiqueta']}), limpieza de sustrato y reconstrucción con azotado e impermeable fino."
                    mo = 12500.0
                    mat = 8500.0
                elif tipo == "Fisura/Grieta":
                    tarea = f"Apertura de fisura en V ({p['etiqueta']}), fijación de testigos, sellado con masa elástica de poliuretano y acabado superficial."
                    mo = 9500.0
                    mat = 7000.0
                elif tipo == "Humedad/Filtración":
                    tarea = f"Retiro de revestimiento afectado por humedad ({p['etiqueta']}), aplicación de bloqueador de humedad y pintura impermeable."
                    mo = 14000.0
                    mat = 11000.0
                elif tipo == "Afectación en Losa":
                    tarea = f"Tratamiento de corrosión en armadura ({p['etiqueta']}), cepillado, pasivado con pintura anticorrosiva y parcheo con mortero de alta resistencia."
                    mo = 18000.0
                    mat = 15000.0
                else:
                    tarea = f"Tarea de reparación general en {p['etiqueta']}"
                    mo = 10000.0
                    mat = 8000.0

                filas.append({
                    "Punto": p["etiqueta"],
                    "Tipo de Patología": tipo,
                    "Tareas a Realizar": tarea,
                    "Cantidad (m² o m)": cant,
                    "Mano de Obra ($)": mo,
                    "Materiales/Equipos ($)": mat
                })
        else:
            filas.append({
                "Punto": "P1 - Muro",
                "Tipo de Patología": "Desprendimiento en Muros",
                "Tareas a Realizar": "Picado de revoque existente con posterior colocación del nuevo hidrófugo y fino.",
                "Cantidad (m² o m)": 1.0,
                "Mano de Obra ($)": 12500.0,
                "Materiales/Equipos ($)": 8500.0
            })
        return pd.DataFrame(filas)

    df_base = construir_df_presupuesto_base()

    st.write("✏️ **Podés modificar directamente las cantidades y costos en la siguiente tabla:**")
    df_edited = st.data_editor(
        df_base,
        num_rows="dynamic",
        use_container_width=True,
        key=f"editor_presupuesto_{proyecto['id']}"
    )

    df_edited["Precio Unitario ($)"] = df_edited["Mano de Obra ($)"] + df_edited["Materiales/Equipos ($)"]
    df_edited["Subtotal ($)"] = df_edited["Cantidad (m² o m)"] * df_edited["Precio Unitario ($)"]

    st.divider()
    
    total_general = df_edited["Subtotal ($)"].sum()
    st.metric(label="💵 Costo Total Estimado de Reparación", value=f"${total_general:,.2f}")

    st.divider()
    st.subheader("📄 Generación de Informe PDF")

    if st.button("🔴 Generar y Descargar Informe Técnico en PDF"):
        with st.spinner("Procesando documento..."):
            pdf_bytes = generar_pdf_informe(proyecto, puntos, inspecciones_todas, df_edited)
            st.download_button(
                label="📥 Descargar PDF Generado",
                data=pdf_bytes,
                file_name=f"Informe_Patologia_{proyecto['nombre'].replace(' ', '_')}.pdf",
                mime="application/pdf"
            )

if __name__ == "__main__":
    main()
