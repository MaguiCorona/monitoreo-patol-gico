import streamlit as st
from supabase import create_client, Client
import pandas as pd

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Monitoreo y Patología Edilicia",
    page_icon="🏗️",
    layout="wide"
)

# -----------------------------------------------------------------------------
# CONEXIÓN CON SUPABASE
# -----------------------------------------------------------------------------
@st.cache_resource
def init_supabase() -> Client:
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
    return create_client(supabase_url, supabase_key)

supabase = init_supabase()

# -----------------------------------------------------------------------------
# FUNCIONES AUXILIARES DE ALMACENAMIENTO (STORAGE)
# -----------------------------------------------------------------------------
def subir_archivo_supabase(bucket: str, path: str, file_bytes: bytes, content_type: str):
    try:
        supabase.storage.from_(bucket).upload(
            path=path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        return supabase.storage.from_(bucket).get_public_url(path)
    except Exception as e:
        try:
            return supabase.storage.from_(bucket).get_public_url(path)
        except Exception:
            st.error(f"Error al subir archivo al bucket '{bucket}': {e}")
            return None

# -----------------------------------------------------------------------------
# FUNCIONES DE CONSULTA (DATABASE)
# -----------------------------------------------------------------------------
def obtener_proyectos():
    res = supabase.table("proyectos").select("*").order("creado_en", desc=True).execute()
    return res.data if res.data else []

def crear_proyecto(nombre, descripcion):
    data = {"nombre": nombre, "descripcion": descripcion}
    res = supabase.table("proyectos").insert(data).execute()
    return res.data

def obtener_planos(proyecto_id):
    res = supabase.table("planos").select("*").eq("proyecto_id", proyecto_id).order("subido_en", desc=True).execute()
    return res.data if res.data else []

def crear_plano(proyecto_id, nombre, url_archivo):
    data = {"proyecto_id": proyecto_id, "nombre": nombre, "ruta_archivo": url_archivo}
    res = supabase.table("planos").insert(data).execute()
    return res.data

def obtener_puntos(plano_id):
    res = supabase.table("puntos").select("*").eq("plano_id", plano_id).order("creado_en", desc=False).execute()
    return res.data if res.data else []

def crear_punto(proyecto_id, plano_id, x_pct, y_pct, etiqueta):
    data = {
        "proyecto_id": proyecto_id,
        "plano_id": plano_id,
        "x_pct": x_pct,
        "y_pct": y_pct,
        "etiqueta": etiqueta
    }
    res = supabase.table("puntos").insert(data).execute()
    return res.data

def obtener_inspecciones(punto_id):
    res = supabase.table("inspecciones").select("*").eq("punto_id", punto_id).order("creado_en", desc=True).execute()
    return res.data if res.data else []

def crear_inspeccion(punto_id, fecha, observacion, url_foto):
    data = {
        "punto_id": punto_id,
        "fecha": str(fecha),
        "descripcion": observacion,
        "foto_path": url_foto
    }
    res = supabase.table("inspecciones").insert(data).execute()
    return res.data

# -----------------------------------------------------------------------------
# INTERFAZ PRINCIPAL
# -----------------------------------------------------------------------------
def main():
    st.title("🏗️ Sistema de Monitoreo y Patología Edilicia")

    proyectos = obtener_proyectos()
    
    st.sidebar.header("📁 Proyectos")
    opcion_proyecto = st.sidebar.selectbox(
        "Seleccionar Proyecto",
        options=["-- Seleccionar --", "+ Crear nuevo proyecto"] + [p["nombre"] for p in proyectos]
    )

    if opcion_proyecto == "+ Crear nuevo proyecto":
        st.subheader("Crear Nuevo Proyecto")
        with st.form("form_nuevo_proyecto"):
            nombre_p = st.text_input("Nombre del Proyecto")
            desc_p = st.text_area("Descripción (opcional)")
            btn_crear = st.form_submit_button("Crear Proyecto")
            
            if btn_crear and nombre_p:
                try:
                    crear_proyecto(nombre_p, desc_p)
                    st.success(f"Proyecto '{nombre_p}' creado con éxito.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear proyecto: {e}")
        return

    if opcion_proyecto == "-- Seleccionar --" or not proyectos:
        st.info("Por favor, selecciona o crea un proyecto en el menú lateral para comenzar.")
        return

    proyecto_actual = next(p for p in proyectos if p["nombre"] == opcion_proyecto)
    proyecto_id = proyecto_actual["id"]

    st.header(f"Proyecto: {proyecto_actual['nombre']}")
    if proyecto_actual.get("descripcion"):
        st.caption(proyecto_actual["descripcion"])

    tab1, tab2 = st.tabs(["📌 Planos y Puntos de Relevamiento", "📊 Historial e Inspecciones"])

    with tab1:
        tab_plano_y_puntos(proyecto_id)

    with tab2:
        tab_historial_e_inspecciones(proyecto_id)

# -----------------------------------------------------------------------------
# PESTAÑAS
# -----------------------------------------------------------------------------
def tab_plano_y_puntos(proyecto_id):
    planos = obtener_planos(proyecto_id)
    col_izq, col_der = st.columns([1, 2])

    with col_izq:
        st.subheader("Planos Cargados")
        
        with st.expander("➕ Cargar Nuevo Plano"):
            nombre_plano = st.text_input("Nombre del Plano")
            archivo_plano = st.file_uploader("Seleccionar imagen del plano", type=["jpg", "jpeg", "png", "webp"])
            
            if st.button("Guardar Plano") and nombre_plano and archivo_plano:
                file_bytes = archivo_plano.getvalue()
                ext = archivo_plano.name.split(".")[-1]
                path_str = f"{proyecto_id}/{nombre_plano.replace(' ', '_')}.{ext}"
                
                url_publica = subir_archivo_supabase("planos", path_str, file_bytes, archivo_plano.type)
                
                if url_publica:
                    crear_plano(proyecto_id, nombre_plano, url_publica)
                    st.success("Plano guardado correctamente.")
                    st.rerun()

        if not planos:
            st.warning("No hay planos cargados en este proyecto.")
            return

        plano_seleccionado_nom = st.selectbox("Seleccionar Plano Activo", [p["nombre"] for p in planos])
        plano_actual = next(p for p in planos if p["nombre"] == plano_seleccionado_nom)
        plano_id = plano_actual["id"]

        st.divider()
        st.subheader("Agregar Punto de Inspección")
        with st.form("form_nuevo_punto"):
            etiqueta = st.text_input("Etiqueta del Punto (Ej: P1, Fischer Norte)")
            coord_x = st.number_input("Coordenada X (%)", min_value=0.0, max_value=100.0, value=50.0, step=0.1)
            coord_y = st.number_input("Coordenada Y (%)", min_value=0.0, max_value=100.0, value=50.0, step=0.1)
            btn_punto = st.form_submit_button("Marcar Punto")

            if btn_punto and etiqueta:
                crear_punto(proyecto_id, plano_id, coord_x, coord_y, etiqueta)
                st.success(f"Punto '{etiqueta}' registrado.")
                st.rerun()

    with col_der:
        st.subheader(f"Plano: {plano_actual['nombre']}")
        puntos = obtener_puntos(plano_actual["id"])
        
        st.image(plano_actual["ruta_archivo"], use_container_width=True)

        if puntos:
            st.write("📍 **Puntos marcados en este plano:**")
            df_puntos = pd.DataFrame(puntos)[["etiqueta", "x_pct", "y_pct", "creado_en"]]
            st.dataframe(df_puntos, use_container_width=True)

def tab_historial_e_inspecciones(proyecto_id):
    planos = obtener_planos(proyecto_id)
    if not planos:
        st.info("Cargá un plano para comenzar a registrar observaciones.")
        return

    plano_nom = st.selectbox("Plano para Inspección", [p["nombre"] for p in planos], key="sel_plano_insp")
    plano_actual = next(p for p in planos if p["nombre"] == plano_nom)
    
    puntos = obtener_puntos(plano_actual["id"])
    if not puntos:
        st.warning("Este plano aún no tiene puntos registrados.")
        return

    punto_etiqueta = st.selectbox("Seleccionar Punto de Monitoreo", [pt["etiqueta"] for pt in puntos])
    punto_actual = next(pt for pt in puntos if pt["etiqueta"] == punto_etiqueta)
    punto_id = punto_actual["id"]

    st.divider()
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader(f"Nueva Inspección - Punto: {punto_actual['etiqueta']}")
        fecha_insp = st.date_input("Fecha de Inspección")
        obs_insp = st.text_area("Observaciones técnicas")
        foto_insp = st.file_uploader("Foto de la patología", type=["jpg", "jpeg", "png", "webp"], key="foto_insp")

        if st.button("Registrar Inspección"):
            if not obs_insp:
                st.error("Ingresá una observación.")
            else:
                url_foto = None
                if foto_insp:
                    file_bytes = foto_insp.getvalue()
                    path_str = f"{punto_id}/{fecha_insp}_{foto_insp.name.replace(' ', '_')}"
                    url_foto = subir_archivo_supabase("fotos", path_str, file_bytes, foto_insp.type)

                crear_inspeccion(punto_id, fecha_insp, obs_insp, url_foto)
                st.success("Inspección guardada correctamente.")
                st.rerun()

    with col2:
        st.subheader("Historial del Punto")
        inspecciones = obtener_inspecciones(punto_id)
        
        if not inspecciones:
            st.caption("No hay inspecciones registradas para este punto.")
        else:
            for insp in inspecciones:
                with st.container(border=True):
                    st.write(f"📅 **Fecha:** {insp['fecha']}")
                    st.write(f"📝 {insp['descripcion']}")
                    if insp.get("foto_path"):
                        st.image(insp["foto_path"], width=300)

if __name__ == "__main__":
    main()
