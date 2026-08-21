import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as plotly_exp
from PIL import Image
from fpdf import FPDF
import datetime
import io
from pdf2image import convert_from_bytes

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
        "x_pct": x_pct,
        "y_pct": y_pct,
        "etiqueta": etiqueta,
        "tipo_patologia": tipo_patologia
    }
    return supabase.table("puntos").insert(data).execute()

def obtener_inspecciones(punto_id=None, proyecto_id=None):
    if punto_id:
        res = supabase.table("inspecciones").select("*").eq("punto_id", punto_id).order("fecha", desc=False).execute()
        return res.data if res.data else []
    
    # Obtención masiva para reportes
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
        "valor_medicion": valor,
        "unidad_medicion": unidad,
        "severidad_subjetiva": severidad,
        "descripcion": observacion,
        "foto_path": url_foto
    }
    return supabase.table("inspecciones").insert(data).execute()

# -----------------------------------------------------------------------------
# LÓGICA DE DIAGNÓSTICO Y SEMÁFORO
# -----------------------------------------------------------------------------
def evaluar_semagoro(tipo_patologia, ultimo_valor, severidad):
    """Retorna un estado de riesgo (Verde, Amarillo, Rojo) y recomendación."""
    if tipo_patologia == "Fisura/Grieta":
        if ultimo_valor >= 3.0 or severidad == "Crítica":
            return "🔴 CRÍTICO", "Riesgo estructural o penetración directa de agua. Requiere prueba de carga y sellado estructural epóxico urgente.", "red"
        elif ultimo_valor >= 1.0 or severidad == "Alta":
            return "🟡 MEDIO", "Fisura activa en monitoreo. Colocar testigo y sellar con sellador elástico.", "orange"
        else:
            return "🟢 BAJO", "Fisura superficial / de retracción. Monitorear periódicamente.", "green"

    elif tipo_patologia == "Humedad/Filtración":
        if ultimo_valor >= 50.0 or severidad == "Crítica":
            return "🔴 CRÍTICO", "Filtración severa con riesgo de degradación en armaduras o mampostería. Localizar fuga/membrana dañada de inmediato.", "red"
        elif ultimo_valor >= 20.0 or severidad == "Alta":
            return "🟡 MEDIO", "Humedad persistente. Reparar impermeabilización y mejorar ventilación.", "orange"
        else:
            return "🟢 BAJO", "Humedad residual o leve. Continuar seguimiento.", "green"

    elif tipo_patologia == "Afectación en Losa":
        if ultimo_valor >= 5.0 or severidad in ["Alta", "Crítica"]:
            return "🔴 CRÍTICO", "Posible flecha excesiva o desprendimiento de hormigón/recubrimiento. Inspección con calculista urgente.", "red"
        elif ultimo_valor >= 2.0 or severidad == "Media":
            return "🟡 MEDIO", "Fisuración en zona tensionada de losa. Monitorear flechas y corrosión.", "orange"
        else:
            return "🟢 BAJO", "Deflexión o fisura dentro de tolerancias de servicio.", "green"

    return "🟢 BAJO", "Sin anomalías mayores.", "green"

# -----------------------------------------------------------------------------
# GENERACIÓN DE PDF
# -----------------------------------------------------------------------------
def generar_pdf_informe(proyecto, puntos, inspecciones_todas, df_costos):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    
    # Encabezado
    pdf.cell(0, 10, f"INFORME TÉCNICO DE PATOLOGÍA EDILICIA", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Proyecto: {proyecto['nombre']}", ln=True, align="C")
    pdf.cell(0, 5, f"Fecha de emisión: {datetime.date.today().strftime('%d/%m/%Y')}", ln=True, align="C")
    pdf.ln(10)

    # Descripción
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "1. Resumen General del Proyecto", ln=True)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, 5, proyecto.get("descripcion") or "Sin descripción proporcionada.")
    pdf.ln(5)

    # Diagnóstico de Puntos
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "2. Puntos Monitoreados y Estado de Riesgo", ln=True)
    pdf.set_font("Arial", "", 10)

    for p in puntos:
        p_insps = [i for i in inspecciones_todas if i["punto_id"] == p["id"]]
        ult_val = p_insps[-1]["valor_medicion"] if p_insps else 0.0
        ult_sev = p_insps[-1]["severidad_subjetiva"] if p_insps else "Baja"
        
        estado, rec, _ = evaluar_semagoro(p["tipo_patologia"], ult_val, ult_sev)
        
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 6, f"• Punto: {p['etiqueta']} ({p['tipo_patologia']}) - Estado: {estado}", ln=True)
        pdf.set_font("Arial", "", 9)
        pdf.multi_cell(0, 5, f"  Última Medición: {ult_val} | Severidad: {ult_sev}\n  Recomendación: {rec}")
        pdf.ln(2)

    pdf.ln(5)

    # Costos
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "3. Presupuesto Estimado de Reparación", ln=True)
    pdf.set_font("Arial", "", 9)

    for _, row in df_costos.iterrows():
        pdf.cell(0, 5, f"- {row['Material / Tarea']}: {row['Cantidad']} x ${row['Precio Unitario ($)']:,.2f} = ${row['Total ($)']:,.2f}", ln=True)

    pdf.ln(5)
    total = df_costos["Total ($)"].sum()
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
# TAB 1: PLANOS Y MARCADOR DE PUNTOS
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
                
                # Conversión si el archivo subido es PDF
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

        st.divider()
        st.subheader("Marcar Nuevo Punto Patológico")
        with st.form("form_punto"):
            etiqueta = st.text_input("Etiqueta (Ej: P1 - Columna C2, Grieta Losa 3)")
            tipo_patologia = st.selectbox("Tipo de Patología", ["Fisura/Grieta", "Humedad/Filtración", "Afectación en Losa"])
            coord_x = st.number_input("Posición X (%) en plano", 0.0, 100.0, 50.0, 0.5)
            coord_y = st.number_input("Posición Y (%) en plano", 0.0, 100.0, 50.0, 0.5)
            
            if st.form_submit_button("Registrar Punto") and etiqueta:
                crear_punto(proyecto_id, plano_actual["id"], coord_x, coord_y, etiqueta, tipo_patologia)
                st.success("Punto registrado.")
                st.rerun()

    with col_der:
        st.subheader(f"Plano: {plano_actual['nombre']}")
        puntos = obtener_puntos(plano_id=plano_actual["id"])
        
        st.image(plano_actual["ruta_archivo"], use_container_width=True)

        if puntos:
            st.write("📍 **Puntos marcados:**")
            df_pt = pd.DataFrame(puntos)[["etiqueta", "tipo_patologia", "x_pct", "y_pct"]]
            st.dataframe(df_pt, use_container_width=True)

# -----------------------------------------------------------------------------
# TAB 2: RELEVAMIENTO E INSPECCIONES
# -----------------------------------------------------------------------------
def tab_relevamiento(proyecto_id):
    puntos = obtener_puntos(proyecto_id=proyecto_id)
    if not puntos:
        st.warning("Primero debes registrar puntos en la pestaña 'Planos y Puntos'.")
        return

    punto_nom = st.selectbox("Seleccionar Punto de Monitoreo", [f"{p['etiqueta']} ({p['tipo_patologia']})" for p in puntos])
    punto_idx = [f"{p['etiqueta']} ({p['tipo_patologia']})" for p in puntos].index(punto_nom)
    punto_actual = puntos[punto_idx]

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader(f"Cargar Inspección: {punto_actual['etiqueta']}")
        
        tipo = punto_actual["tipo_patologia"]
        unidad = "mm" if tipo in ["Fisura/Grieta", "Afectación en Losa"] else "%"
        
        fecha = st.date_input("Fecha de medición", datetime.date.today())
        valor = st.number_input(f"Medición registrada ({unidad})", min_value=0.0, value=0.5, step=0.1)
        severidad = st.selectbox("Evaluación visual de severidad", ["Baja", "Media", "Alta", "Crítica"])
        obs = st.text_area("Observaciones técnicas y causas probables")
        foto = st.file_uploader("Foto de evidencia", type=["jpg", "jpeg", "png", "webp"])

        if st.button("Guardar Inspección"):
            url_foto = None
            if foto:
                bytes_f = foto.getvalue()
                path = f"{punto_actual['id']}/{fecha}_{foto.name.replace(' ', '_')}"
                url_foto = subir_archivo_supabase("fotos", path, bytes_f, foto.type)

            crear_inspeccion(punto_actual["id"], fecha, valor, unidad, severidad, obs, url_foto)
            st.success("Inspección guardada con éxito.")
            st.rerun()

    with col2:
        st.subheader("Historial de este Punto")
        inspecciones = obtener_inspecciones(punto_id=punto_actual["id"])
        
        if not inspecciones:
            st.caption("Aún no hay mediciones registradas.")
        else:
            for insp in inspecciones:
                with st.container(border=True):
                    st.write(f"📅 **Fecha:** {insp['fecha']} | **Valor:** {insp['valor_medicion']} {insp['unidad_medicion']}")
                    st.write(f"⚠️ **Severidad:** {insp['severidad_subjetiva']}")
                    st.write(f"📝 {insp['descripcion']}")
                    if insp.get("foto_path"):
                        st.image(insp["foto_path"], width=280)

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
        ult_sev = p_insps[-1]["severidad_subjetiva"] if p_insps else "Baja"
        
        estado, rec, color = evaluar_semagoro(p["tipo_patologia"], ult_val, ult_sev)

        with cols[idx % 3]:
            with st.container(border=True):
                st.markdown(f"### {p['etiqueta']}")
                st.caption(f"Tipo: {p['tipo_patologia']}")
                
                if color == "red":
                    st.error(f"Estado: {estado}")
                elif color == "orange":
                    st.warning(f"Estado: {estado}")
                else:
                    st.success(f"Estado: {estado}")

                st.write(f"**Última Medición:** {ult_val}")
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
# TAB 4: PRESUPUESTO EDITABLE E INFORME PDF
# -----------------------------------------------------------------------------
def tab_presupuesto_y_pdf(proyecto):
    st.subheader("💰 Presupuesto Estimado de Reparación")

    datos_base = {
        "Material / Tarea": ["Inyección de resina epóxica", "Sellador poliuretánico", "Membrana elástomérica", "Mano de obra especializada"],
        "Cantidad": [10, 15, 20, 5],
        "Precio Unitario ($)": [15000.0, 8500.0, 12000.0, 45000.0]
    }
    
    if "df_presupuesto" not in st.session_state:
        st.session_state.df_presupuesto = pd.DataFrame(datos_base)

    df_editado = st.data_editor(
        st.session_state.df_presupuesto,
        num_rows="dynamic",
        use_container_width=True,
        key="editor_costos"
    )

    df_editado["Total ($)"] = df_editado["Cantidad"] * df_editado["Precio Unitario ($)"]
    total_presupuesto = df_editado["Total ($)"].sum()

    st.markdown(f"### **Costo Total Estimado:** `${total_presupuesto:,.2f}`")

    st.divider()
    st.subheader("📄 Generación de Informe Completo en PDF")

    puntos = obtener_puntos(proyecto_id=proyecto["id"])
    inspecciones_todas = obtener_inspecciones(proyecto_id=proyecto["id"])

    if st.button("📥 Generar y Descargar Informe PDF"):
        pdf_bytes = generar_pdf_informe(proyecto, puntos, inspecciones_todas, df_editado)
        st.download_button(
            label="Descargar PDF generado",
            data=pdf_bytes,
            file_name=f"Informe_Patologias_{proyecto['nombre'].replace(' ', '_')}.pdf",
            mime="application/pdf"
        )

if __name__ == "__main__":
    main()
